from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import uuid

from app.agents.factory import create_agent_gateway
from app.agents.models import AgentProgressEvent
from app.config import settings
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.repositories.transactions import TransactionRepository
from app.db.session import SessionLocal
from app.workers.import_worker.data_mapping import parse_agent_result_for_persistence
from app.workers.import_worker.data_persistence import save_parsed_import_result

_import_job_repository = ImportJobRepository()
_transaction_repository = TransactionRepository()
logger = logging.getLogger(__name__)


async def process_job(job_id: str) -> None:
    with SessionLocal() as session:
        job = _import_job_repository.get_by_id(session, job_id=job_id)
        if job is None:
            return
        if job.status == "done":
            return

        user_id = job.user_id
        storage_path = job.storage_path
        _import_job_repository.mark_step(
            session,
            job_id,
            current_step="Processing started",
        )
        session.commit()

    agent_input = {"storage_path": storage_path}

    try:
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
            with SessionLocal() as session:
                _import_job_repository.mark_step(
                    session,
                    job_id,
                    current_step=event.message,
                )
                session.commit()

        agent_gateway = create_agent_gateway()
        result = await agent_gateway.extract_statement_transactions(
            storage_path,
            user_id=user_id,
            on_progress=handle_agent_progress,
        )

        if result.status != "success":
            raise ValueError("Agent failed to return valid JSON.")

        agent_data = result.data
        if not isinstance(agent_data, dict):
            raise ValueError("Agent result data must be a JSON object.")

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

        statement_metadata, transactions = parse_agent_result_for_persistence(
            agent_data,
            import_job_id=job_id,
        )

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
    except Exception as error:
        with SessionLocal() as session:
            _import_job_repository.mark_failed(session, job_id, error_message=str(error))
            session.commit()
        logger.exception("Import job %s failed", job_id)


async def run_worker(worker_id: str, *, once: bool = False) -> None:
    while True:
        with SessionLocal() as session:
            job = _import_job_repository.claim_next_pending(session, worker_id=worker_id)
            session.commit()

        if job is None:
            if once:
                return
            await asyncio.sleep(2)
            continue

        await process_job(job.id)
        if once:
            return


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Process pending PDF import jobs.")
    parser.add_argument("--worker-id", default=_default_worker_id())
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    args = parser.parse_args()

    asyncio.run(run_worker(args.worker_id, once=args.once))
