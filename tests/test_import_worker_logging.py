from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

from app.agents.models import AgentProgressEvent, agent_error_result, agent_success_result

worker = importlib.import_module("app.workers.import_worker.main")


class FakeSession:
    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        return None


def fake_session_local() -> FakeSession:
    return FakeSession()


def fake_job(**overrides: object) -> SimpleNamespace:
    values = {
        "id": "job_1",
        "status": "processing",
        "user_id": "gabe",
        "storage_path": "/tmp/example.pdf",
        "attempts": 2,
        "original_filename": "example.pdf",
        "size_bytes": 1234,
        "created_at": datetime(2026, 5, 28, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class NoJobRepository:
    def claim_next_pending(self, session: FakeSession, *, worker_id: str) -> None:
        return None


class ClaimingRepository:
    def __init__(self) -> None:
        self.job = fake_job(status="processing")

    def claim_next_pending(self, session: FakeSession, *, worker_id: str) -> SimpleNamespace:
        return self.job


class ProcessJobRepository:
    def __init__(self, job: SimpleNamespace | None = None) -> None:
        self.job = job or fake_job()
        self.failed = False

    def get_by_id(self, session: FakeSession, *, job_id: str) -> SimpleNamespace:
        return self.job

    def mark_step(self, session: FakeSession, job_id: str, *, current_step: str) -> None:
        return None

    def save_agent_input(
        self,
        session: FakeSession,
        job_id: str,
        *,
        input_payload_json: dict,
    ) -> None:
        return None

    def save_agent_output(
        self,
        session: FakeSession,
        job_id: str,
        *,
        output_payload_json: dict,
    ) -> None:
        return None

    def mark_failed(self, session: FakeSession, job_id: str, *, error_message: str) -> None:
        self.failed = True


def log_text(caplog) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


def test_run_worker_logs_startup_and_idle_only_at_debug(caplog, monkeypatch) -> None:
    monkeypatch.setattr(worker, "SessionLocal", fake_session_local)
    monkeypatch.setattr(worker, "_import_job_repository", NoJobRepository())

    caplog.set_level(logging.INFO, logger=worker.logger.name)
    asyncio.run(worker.run_worker("worker-1", once=True))

    messages = log_text(caplog)
    assert "worker_started worker_id=worker-1 poll_interval_seconds=2" in messages
    assert "worker_idle worker_id=worker-1" not in messages

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger=worker.logger.name)
    asyncio.run(worker.run_worker("worker-1", once=True))

    assert "worker_idle worker_id=worker-1" in log_text(caplog)


def test_run_worker_logs_claimed_job(caplog, monkeypatch) -> None:
    async def fake_process_job(job_id: str, *, worker_id: str | None, attempt: int | None) -> None:
        return None

    monkeypatch.setattr(worker, "SessionLocal", fake_session_local)
    monkeypatch.setattr(worker, "_import_job_repository", ClaimingRepository())
    monkeypatch.setattr(worker, "process_job", fake_process_job)

    caplog.set_level(logging.INFO, logger=worker.logger.name)
    asyncio.run(worker.run_worker("worker-1", once=True))

    messages = log_text(caplog)
    assert "job_claimed job_id=job_1 worker_id=worker-1 attempt=2" in messages
    assert "filename=example.pdf size_bytes=1234" in messages


def test_process_job_logs_successful_agent_parse_and_save(caplog, monkeypatch) -> None:
    class FakeGateway:
        async def extract_statement_transactions(self, *args: object, **kwargs: object):
            on_progress = kwargs["on_progress"]
            await on_progress(AgentProgressEvent(code="reading", message="Reading PDF"))
            return agent_success_result({"ok": True})

    def fake_parse(agent_data: dict, *, import_job_id: str):
        return {"statement_kind": "credit_card"}, [object(), object()]

    def fake_save(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(worker, "SessionLocal", fake_session_local)
    monkeypatch.setattr(worker, "_import_job_repository", ProcessJobRepository())
    monkeypatch.setattr(worker, "create_agent_gateway", lambda: FakeGateway())
    monkeypatch.setattr(worker, "parse_agent_result_for_persistence", fake_parse)
    monkeypatch.setattr(worker, "save_parsed_import_result", fake_save)

    caplog.set_level(logging.INFO, logger=worker.logger.name)
    asyncio.run(worker.process_job("job_1", worker_id="worker-1", attempt=2))

    messages = log_text(caplog)
    assert "agent_extract_started job_id=job_1" in messages
    assert 'agent_progress job_id=job_1 step="Reading PDF"' in messages
    assert "agent_extract_finished job_id=job_1 status=success" in messages
    assert "agent_result_parsed job_id=job_1 statement_kind=credit_card transaction_count=2" in messages
    assert "draft_transactions_saved job_id=job_1 transaction_count=2" in messages
    assert "job_done job_id=job_1 duration_seconds=" in messages


def test_process_job_logs_failure_with_phase_attempt_and_worker(caplog, monkeypatch) -> None:
    class FailingGateway:
        async def extract_statement_transactions(self, *args: object, **kwargs: object):
            return agent_error_result()

    repository = ProcessJobRepository()
    monkeypatch.setattr(worker, "SessionLocal", fake_session_local)
    monkeypatch.setattr(worker, "_import_job_repository", repository)
    monkeypatch.setattr(worker, "create_agent_gateway", lambda: FailingGateway())

    caplog.set_level(logging.ERROR, logger=worker.logger.name)
    asyncio.run(worker.process_job("job_1", worker_id="worker-1", attempt=2))

    messages = log_text(caplog)
    assert repository.failed is True
    assert "job_failed job_id=job_1 worker_id=worker-1 phase=agent_extract attempt=2" in messages
