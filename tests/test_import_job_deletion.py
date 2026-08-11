from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import import_jobs_routes
from app.auth import get_current_user
from app.db.schemas import Base
from app.db.schemas.accounts import AccountSchema
from app.db.schemas.import_jobs import ImportJobSchema
from app.db.schemas.transactions import TransactionSchema
from app.db.schemas.users import UserSchema
from app.db.session import get_session
from app.main import app


class FakeFileStorageService:
    def __init__(self) -> None:
        self.deleted_paths: list[str] = []
        self.error: Exception | None = None

    async def delete_if_exists(self, storage_path: str) -> None:
        self.deleted_paths.append(storage_path)
        if self.error is not None:
            raise self.error


@pytest.fixture()
def deletion_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[
    tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
    None,
    None,
]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    storage = FakeFileStorageService()

    with SessionLocal() as session:
        _seed_deletion_rows(session)
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = lambda: UserSchema(
        id="gabe",
        email="gabe@example.test",
        display_name="Gabe",
    )
    monkeypatch.setattr(
        import_jobs_routes,
        "create_file_storage_service",
        lambda settings: storage,
    )

    try:
        yield TestClient(app, raise_server_exceptions=False), SessionLocal, storage
    finally:
        app.dependency_overrides.clear()


def test_delete_import_job_removes_job_and_all_linked_transactions(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
) -> None:
    client, SessionLocal, storage = deletion_client

    response = client.delete("/import-jobs/job_done")

    assert response.status_code == 204
    assert response.content == b""
    assert storage.deleted_paths == ["/uploads/done.pdf"]
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_done") is None
        assert session.get(TransactionSchema, "tx_done_draft") is None
        assert session.get(TransactionSchema, "tx_done_committed") is None
        assert session.get(TransactionSchema, "tx_unrelated") is not None


def test_delete_failed_import_job_succeeds_when_storage_object_is_already_missing(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
) -> None:
    client, SessionLocal, storage = deletion_client

    response = client.delete("/import-jobs/job_failed")

    assert response.status_code == 204
    assert storage.deleted_paths == ["/uploads/already-missing.pdf"]
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_failed") is None
        assert session.get(TransactionSchema, "tx_failed") is None


@pytest.mark.parametrize("job_id", ["job_pending", "job_processing"])
def test_delete_active_import_job_is_blocked(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
    job_id: str,
) -> None:
    client, SessionLocal, storage = deletion_client

    response = client.delete(f"/import-jobs/{job_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": "Active import cannot be deleted"}
    assert storage.deleted_paths == []
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, job_id) is not None


@pytest.mark.parametrize("job_id", ["job_other_user", "job_unknown"])
def test_delete_missing_or_cross_user_import_job_returns_not_found(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
    job_id: str,
) -> None:
    client, SessionLocal, storage = deletion_client

    response = client.delete(f"/import-jobs/{job_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Import job not found"}
    assert storage.deleted_paths == []
    with SessionLocal() as session:
        if job_id == "job_other_user":
            assert session.get(ImportJobSchema, job_id) is not None


def test_storage_failure_keeps_database_records(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
) -> None:
    client, SessionLocal, storage = deletion_client
    storage.error = RuntimeError("storage unavailable")

    response = client.delete("/import-jobs/job_done")

    assert response.status_code == 500
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_done") is not None
        assert session.get(TransactionSchema, "tx_done_draft") is not None
        assert session.get(TransactionSchema, "tx_done_committed") is not None


def test_database_failure_rolls_back_transaction_deletion(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, storage = deletion_client

    def fail_job_delete(session: Session, *, job: ImportJobSchema) -> None:
        del session, job
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(import_jobs_routes._import_job_repository, "delete", fail_job_delete)

    response = client.delete("/import-jobs/job_done")

    assert response.status_code == 500
    assert storage.deleted_paths == ["/uploads/done.pdf"]
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_done") is not None
        assert session.get(TransactionSchema, "tx_done_draft") is not None
        assert session.get(TransactionSchema, "tx_done_committed") is not None


def test_repeated_delete_returns_not_found(
    deletion_client: tuple[TestClient, sessionmaker[Session], FakeFileStorageService],
) -> None:
    client, _, storage = deletion_client

    first = client.delete("/import-jobs/job_failed")
    second = client.delete("/import-jobs/job_failed")

    assert first.status_code == 204
    assert second.status_code == 404
    assert storage.deleted_paths == ["/uploads/already-missing.pdf"]


def _seed_deletion_rows(session: Session) -> None:
    session.add_all(
        [
            UserSchema(id="gabe", email="gabe@example.test", display_name="Gabe"),
            UserSchema(id="other", email="other@example.test", display_name="Other"),
        ]
    )
    session.flush()
    session.add_all(
        [
            AccountSchema(id="account_gabe", user_id="gabe", name="Checking", type="checking"),
            AccountSchema(id="account_other", user_id="other", name="Checking", type="checking"),
        ]
    )
    session.flush()
    session.add_all(
        [
            _job("job_done", user_id="gabe", status="done", path="/uploads/done.pdf"),
            _job(
                "job_failed",
                user_id="gabe",
                status="failed",
                path="/uploads/already-missing.pdf",
            ),
            _job("job_pending", user_id="gabe", status="pending", path="/uploads/pending.pdf"),
            _job(
                "job_processing",
                user_id="gabe",
                status="processing",
                path="/uploads/processing.pdf",
            ),
            _job(
                "job_other_user",
                user_id="other",
                status="done",
                path="/uploads/other.pdf",
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            _transaction("tx_done_draft", import_job_id="job_done", is_draft=True),
            _transaction("tx_done_committed", import_job_id="job_done", is_draft=False),
            _transaction("tx_failed", import_job_id="job_failed", is_draft=True),
            _transaction("tx_unrelated", import_job_id=None, is_draft=False),
            _transaction(
                "tx_other_user",
                import_job_id="job_other_user",
                is_draft=False,
                user_id="other",
                account_id="account_other",
            ),
        ]
    )


def _job(job_id: str, *, user_id: str, status: str, path: str) -> ImportJobSchema:
    return ImportJobSchema(
        id=job_id,
        user_id=user_id,
        status=status,
        storage_path=path,
        file_hash=f"hash_{job_id}",
        idempotency_key=f"idem_{job_id}",
    )


def _transaction(
    transaction_id: str,
    *,
    import_job_id: str | None,
    is_draft: bool,
    user_id: str = "gabe",
    account_id: str = "account_gabe",
) -> TransactionSchema:
    return TransactionSchema(
        id=transaction_id,
        user_id=user_id,
        account_id=account_id,
        import_job_id=import_job_id,
        posted_at=date(2026, 6, 1),
        description=transaction_id,
        amount=Decimal("10.00"),
        is_draft=is_draft,
    )
