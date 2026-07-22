from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.api import agents_routes
from app.db.schemas.import_jobs import ImportJobSchema
from app.db.schemas.users import UserSchema


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.expire_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def expire_all(self) -> None:
        self.expire_count += 1


class FakeImportJobRepository:
    def __init__(self, existing_job: ImportJobSchema | None = None) -> None:
        self.job = existing_job

    def get_by_idempotency_key(
        self,
        session: object,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> ImportJobSchema | None:
        return self.job

    def create_pending(self, session: object, **values: object) -> ImportJobSchema:
        now = datetime.now(UTC)
        self.job = ImportJobSchema(
            id="job_test",
            status="pending",
            current_step="Upload received",
            created_at=now,
            updated_at=now,
            **values,
        )
        return self.job

    def get_by_id(
        self,
        session: object,
        *,
        job_id: str,
        user_id: str,
    ) -> ImportJobSchema | None:
        return self.job if self.job is not None and self.job.id == job_id else None


class FakeFileSystemService:
    instances: list[FakeFileSystemService] = []

    def __init__(self) -> None:
        self.deleted_paths: list[str] = []
        self.__class__.instances.append(self)

    async def save(self, uploaded_bytes: bytes, **values: object) -> str:
        return "/tmp/request-scoped.pdf"

    def delete_if_exists(self, path: str) -> None:
        self.deleted_paths.append(path)


def _upload() -> UploadFile:
    return UploadFile(
        filename="statement.pdf",
        file=BytesIO(b"%PDF-1.4\n%%EOF"),
        headers=Headers({"content-type": "application/pdf"}),
    )


def test_process_file_completes_job_before_returning(monkeypatch) -> None:
    repository = FakeImportJobRepository()
    session = FakeSession()
    processed_job_ids: list[str] = []
    FakeFileSystemService.instances.clear()

    async def process_job(job_id: str, *, worker_id: str | None = None) -> None:
        processed_job_ids.append(job_id)
        assert repository.job is not None
        repository.job.status = "done"
        repository.job.current_step = "Draft transactions saved"
        repository.job.updated_at = datetime.now(UTC)
        repository.job.finished_at = datetime.now(UTC)

    monkeypatch.setattr(agents_routes, "_import_job_repository", repository)
    monkeypatch.setattr(agents_routes, "FileSystemService", FakeFileSystemService)
    monkeypatch.setattr(agents_routes, "process_job", process_job)

    response = asyncio.run(
        agents_routes.agent_process_file(
            current_user=UserSchema(
                id="user_test",
                email="test@example.test",
                display_name="Test",
            ),
            file=_upload(),
            idempotency_key="idem_test",
            session=session,
        )
    )

    assert response.status == "done"
    assert processed_job_ids == ["job_test"]
    assert session.commit_count == 1
    assert session.expire_count == 1
    assert FakeFileSystemService.instances[0].deleted_paths == [
        "/tmp/request-scoped.pdf"
    ]


def test_process_file_reuses_completed_idempotent_job(monkeypatch) -> None:
    now = datetime.now(UTC)
    existing_job = ImportJobSchema(
        id="job_existing",
        user_id="user_test",
        status="done",
        current_step="Draft transactions saved",
        original_filename="statement.pdf",
        content_type="application/pdf",
        size_bytes=len(b"%PDF-1.4\n%%EOF"),
        storage_path="/tmp/already-processed.pdf",
        file_hash=agents_routes._sha256_bytes(b"%PDF-1.4\n%%EOF"),
        idempotency_key="idem_test",
        created_at=now,
        updated_at=now,
        finished_at=now,
    )
    repository = FakeImportJobRepository(existing_job)
    process_calls: list[str] = []

    async def process_job(job_id: str, *, worker_id: str | None = None) -> None:
        process_calls.append(job_id)

    monkeypatch.setattr(agents_routes, "_import_job_repository", repository)
    monkeypatch.setattr(agents_routes, "process_job", process_job)

    response = asyncio.run(
        agents_routes.agent_process_file(
            current_user=UserSchema(
                id="user_test",
                email="test@example.test",
                display_name="Test",
            ),
            file=_upload(),
            idempotency_key="idem_test",
            session=FakeSession(),
        )
    )

    assert response.status_code == 200
    assert process_calls == []
