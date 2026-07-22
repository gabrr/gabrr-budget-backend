from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import time
import uuid
from pathlib import Path

from app.agents.factory import create_agent_gateway
from app.agents.models import AgentProgressEvent
from app.config import settings
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.repositories.transactions import TransactionRepository
from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.workers.import_worker.data_mapping import parse_agent_result_for_persistence
from app.workers.import_worker.data_persistence import save_parsed_import_result

_import_job_repository = ImportJobRepository()
_transaction_repository = TransactionRepository()
logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 2


def _read_pdf_bytes(storage_path: str) -> bytes:
    return Path(storage_path).read_bytes()


async def process_job(
    job_id: str,
    *,
    worker_id: str | None = None,
    attempt: int | None = None,
) -> None:
    started_at = time.monotonic()
    phase = "loading_job"
    current_attempt = attempt

    with SessionLocal() as session:
        job = _import_job_repository.get_by_id(session, job_id=job_id)
        if job is None:
            logger.warning("job_missing job_id=%s worker_id=%s", job_id, worker_id)
            return
        if job.status == "done":
            logger.info("job_skipped_done job_id=%s worker_id=%s", job_id, worker_id)
            return

        user_id = job.user_id
        storage_path = job.storage_path
        current_attempt = current_attempt or job.attempts
        logger.info(
            "job_processing_started job_id=%s worker_id=%s attempt=%s filename=%s",
            job_id,
            worker_id,
            current_attempt,
            job.original_filename,
        )
        _import_job_repository.mark_step(
            session,
            job_id,
            current_step="Processing started",
        )
        session.commit()

    agent_input = {
        "filename": job.original_filename,
        "size_bytes": job.size_bytes,
    }

    try:
        phase = "saving_agent_input"
        with SessionLocal() as session:
            _import_job_repository.save_agent_input(
                session,
                job_id,
                input_payload_json=agent_input,
            )
            _import_job_repository.mark_step(
                session,
                job_id,
                current_step="Reading PDF with agent",
            )
            session.commit()

        last_agent_step: str | None = None

        async def handle_agent_progress(event: AgentProgressEvent) -> None:
            nonlocal last_agent_step

            if event.message == last_agent_step:
                return

            last_agent_step = event.message
            logger.info(
                'agent_progress job_id=%s step="%s"',
                job_id,
                event.message,
            )
            with SessionLocal() as session:
                _import_job_repository.mark_step(
                    session,
                    job_id,
                    current_step=event.message,
                )
                session.commit()

        agent_gateway = create_agent_gateway()
        phase = "agent_extract"
        logger.info("agent_extract_started job_id=%s", job_id)
        result = await agent_gateway.extract_statement_transactions(
            _read_pdf_bytes(storage_path),
            filename=job.original_filename or "statement.pdf",
            user_id=user_id,
            on_progress=handle_agent_progress,
        )
        logger.info("agent_extract_finished job_id=%s status=%s", job_id, result.status)

        if result.status != "success":
            raise ValueError("Agent failed to return valid JSON.")

        agent_data = result.data
        if not isinstance(agent_data, dict):
            raise ValueError("Agent result data must be a JSON object.")

        phase = "saving_agent_output"
        with SessionLocal() as session:
            _import_job_repository.save_agent_output(
                session,
                job_id,
                output_payload_json={"status": result.status, "data": result.data},
            )
            _import_job_repository.mark_step(
                session,
                job_id,
                current_step="Validating transactions",
            )
            session.commit()

        phase = "parsing_agent_result"
        statement_metadata, transactions = parse_agent_result_for_persistence(
            agent_data,
            import_job_id=job_id,
        )
        transaction_count = len(transactions)
        logger.info(
            "agent_result_parsed job_id=%s statement_kind=%s transaction_count=%s",
            job_id,
            statement_metadata.get("statement_kind"),
            transaction_count,
        )

        phase = "saving_draft_transactions"
        with SessionLocal() as session:
            save_parsed_import_result(
                session,
                job_id=job_id,
                user_id=user_id,
                default_account_id=settings.default_account_id,
                statement_metadata=statement_metadata,
                transactions=transactions,
                import_job_repository=_import_job_repository,
                transaction_repository=_transaction_repository,
            )
            session.commit()
        logger.info(
            "draft_transactions_saved job_id=%s transaction_count=%s",
            job_id,
            transaction_count,
        )
        logger.info(
            "job_done job_id=%s duration_seconds=%.3f",
            job_id,
            time.monotonic() - started_at,
        )
    except Exception as error:
        with SessionLocal() as session:
            _import_job_repository.mark_failed(session, job_id, error_message=str(error))
            session.commit()
        logger.exception(
            "job_failed job_id=%s worker_id=%s phase=%s attempt=%s",
            job_id,
            worker_id,
            phase,
            current_attempt,
        )


async def run_worker(
    worker_id: str,
    *,
    once: bool = False,
    poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> None:
    logger.info(
        "worker_started worker_id=%s poll_interval_seconds=%s",
        worker_id,
        poll_interval_seconds,
    )
    while True:
        with SessionLocal() as session:
            job = _import_job_repository.claim_next_pending(session, worker_id=worker_id)
            session.commit()

        if job is None:
            logger.debug("worker_idle worker_id=%s", worker_id)
            if once:
                return
            await asyncio.sleep(poll_interval_seconds)
            continue

        logger.info(
            "job_claimed job_id=%s worker_id=%s attempt=%s filename=%s size_bytes=%s created_at=%s",
            job.id,
            worker_id,
            job.attempts,
            job.original_filename,
            job.size_bytes,
            job.created_at,
        )
        await process_job(job.id, worker_id=worker_id, attempt=job.attempts)
        if once:
            return


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Process pending PDF import jobs.")
    parser.add_argument("--worker-id", default=_default_worker_id())
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    args = parser.parse_args()

    asyncio.run(run_worker(args.worker_id, once=args.once))
