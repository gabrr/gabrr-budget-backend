from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import import_jobs_routes
from app.api.import_jobs_routes import import_job_event_key, import_job_to_public
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.schemas import Base
from app.db.schemas.import_jobs import ImportJobSchema


class FakeSessionLocal:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: object) -> None:
        return None


class FakeImportJobRepository:
    def __init__(self, jobs: list[ImportJobSchema] | None = None) -> None:
        self.jobs = jobs or []
        self.latest_active_limit: int | None = None
        self.recent_limit: int | None = None

    def get_latest_active(
        self,
        session: object,
        *,
        user_id: str,
    ) -> ImportJobSchema | None:
        self.latest_active_limit = None
        active_jobs = [
            job
            for job in self.jobs
            if job.user_id == user_id and job.status in {"pending", "processing"}
        ]
        return active_jobs[0] if active_jobs else None

    def list_recent(
        self,
        session: object,
        *,
        user_id: str,
        limit: int = 20,
    ) -> list[ImportJobSchema]:
        self.recent_limit = limit
        return [job for job in self.jobs if job.user_id == user_id][:limit]


def _job(
    job_id: str,
    *,
    status: str,
    created_at: datetime | None = None,
    user_id: str = "gabe",
) -> ImportJobSchema:
    now = created_at or datetime.now(UTC)
    return ImportJobSchema(
        id=job_id,
        user_id=user_id,
        status=status,
        current_step="Reading PDF with agent",
        original_filename=f"{job_id}.pdf",
        storage_path="/tmp/example.pdf",
        file_hash="abc",
        idempotency_key=f"idem_{job_id}",
        created_at=now,
        updated_at=now,
    )


def test_import_job_event_key_tracks_user_visible_timeline_fields() -> None:
    job = ImportJobSchema(
        id="job_1",
        user_id="user_1",
        status="processing",
        current_step="Reading PDF with agent",
        storage_path="/tmp/example.pdf",
        file_hash="abc",
        idempotency_key="idem",
    )

    first_key = import_job_event_key(job)
    job.current_step = "Validating transactions"
    changed_visible_event_key = import_job_event_key(job)
    job.finished_at = datetime.now(UTC)
    terminal_event_key = import_job_event_key(job)

    assert changed_visible_event_key != first_key
    assert terminal_event_key != changed_visible_event_key


def test_import_job_public_response_does_not_include_progress() -> None:
    now = datetime.now(UTC)
    job = ImportJobSchema(
        id="job_1",
        user_id="user_1",
        status="processing",
        current_step="Reading PDF with agent",
        storage_path="/tmp/example.pdf",
        file_hash="abc",
        idempotency_key="idem",
        created_at=now,
        updated_at=now,
    )

    payload = import_job_to_public(job).model_dump()

    assert "progress" not in payload
    assert payload["original_filename"] is None
    assert payload["statement_kind"] == "unknown"


def test_active_import_job_returns_latest_active_job(monkeypatch) -> None:
    repository = FakeImportJobRepository(
        [
            _job("job_processing", status="processing"),
            _job("job_done", status="done"),
        ]
    )
    monkeypatch.setattr(import_jobs_routes, "_import_job_repository", repository)
    monkeypatch.setattr(import_jobs_routes, "SessionLocal", FakeSessionLocal)

    response = asyncio.run(import_jobs_routes.get_active_import_job())

    assert not isinstance(response, Response)
    assert response.job_id == "job_processing"
    assert response.status == "processing"


def test_active_import_job_returns_204_when_no_active_job(monkeypatch) -> None:
    repository = FakeImportJobRepository([_job("job_done", status="done")])
    monkeypatch.setattr(import_jobs_routes, "_import_job_repository", repository)
    monkeypatch.setattr(import_jobs_routes, "SessionLocal", FakeSessionLocal)

    response = asyncio.run(import_jobs_routes.get_active_import_job())

    assert isinstance(response, Response)
    assert response.status_code == 204


def test_list_import_jobs_returns_recent_jobs_with_bounded_limit(monkeypatch) -> None:
    repository = FakeImportJobRepository(
        [
            _job("job_1", status="done"),
            _job("job_2", status="processing"),
            _job("other_user_job", status="pending", user_id="other"),
        ]
    )
    monkeypatch.setattr(import_jobs_routes, "_import_job_repository", repository)
    monkeypatch.setattr(import_jobs_routes, "SessionLocal", FakeSessionLocal)

    response = asyncio.run(import_jobs_routes.list_import_jobs(limit=100))

    assert repository.recent_limit == 50
    assert [job.job_id for job in response] == ["job_1", "job_2"]


def test_import_job_repository_lists_recent_and_latest_active() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    repository = ImportJobRepository()

    older = _job(
        "older_processing",
        status="processing",
        created_at=datetime(2026, 5, 28, tzinfo=UTC),
    )
    newer = _job(
        "newer_pending",
        status="pending",
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    done = _job(
        "done",
        status="done",
        created_at=datetime(2026, 5, 30, tzinfo=UTC),
    )

    with SessionLocal() as session:
        session.add_all([older, newer, done])
        session.commit()

        latest_active = repository.get_latest_active(session, user_id="gabe")
        recent_jobs = repository.list_recent(session, user_id="gabe", limit=3)

    assert latest_active is not None
    assert latest_active.id == "older_processing"
    assert [job.id for job in recent_jobs] == ["done", "newer_pending", "older_processing"]
