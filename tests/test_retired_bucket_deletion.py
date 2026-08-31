from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import import_jobs_routes
from app.auth import get_current_user
from app.config import Settings
from app.db.schemas import Base
from app.db.schemas.accounts import AccountSchema
from app.db.schemas.import_jobs import ImportJobSchema
from app.db.schemas.transactions import TransactionSchema
from app.db.schemas.users import UserSchema
from app.db.session import get_session
from app.main import create_app
from app.services.file_storage_service import GoogleCloudStorageService

DATABASE_URL = "sqlite+pysqlite://"
CURRENT_BUCKET = "gen-lang-client-0570264410-acetate-imports"
RETIRED_BUCKET = "gen-lang-client-0570264410-gabrr-imports"
RETIRED_PATH = f"gs://{RETIRED_BUCKET}/imports/gabe/legacy.pdf"


@pytest.fixture()
def retired_deletion_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session], Mock, object], None, None]:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    _seed_rows(SessionLocal)

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

    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://postgres:postgres@localhost/test",
        app_env="production",
        auth_mode="supabase",
        cors_origins="https://www.acetate.me",
        supabase_url="https://project.supabase.co",
        allowed_user_email="gabe@example.test",
        file_storage_backend="gcs",
        gcs_bucket_name=CURRENT_BUCKET,
        gcs_retired_bucket_names=RETIRED_BUCKET,
    )
    test_app = create_app(settings)
    test_app.dependency_overrides[get_session] = override_get_session
    test_app.dependency_overrides[get_current_user] = lambda: UserSchema(
        id="gabe",
        email="gabe@example.test",
        display_name="Gabe",
    )

    client_mock = Mock()
    bucket = Mock()
    bucket.name = CURRENT_BUCKET
    client_mock.bucket.return_value = bucket
    storage = GoogleCloudStorageService(
        CURRENT_BUCKET,
        retired_bucket_names=frozenset({RETIRED_BUCKET}),
        client=client_mock,
    )
    monkeypatch.setattr(
        import_jobs_routes,
        "create_file_storage_service",
        lambda settings: storage,
    )

    try:
        yield TestClient(test_app, raise_server_exceptions=False), SessionLocal, bucket, test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.mark.parametrize("job_id", ["job_done", "job_failed"])
def test_owner_can_delete_terminal_retired_bucket_job(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
    job_id: str,
) -> None:
    client, SessionLocal, bucket, _ = retired_deletion_client
    response = client.delete(f"/import-jobs/{job_id}")
    assert response.status_code == 204
    assert response.content == b""
    bucket.blob.assert_not_called()
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, job_id) is None
        assert session.query(TransactionSchema).filter_by(import_job_id=job_id).count() == 0
        assert session.get(TransactionSchema, "tx_unrelated") is not None


def test_linked_transactions_are_deleted_before_job(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _, _ = retired_deletion_client
    original_delete = import_jobs_routes._import_job_repository.delete

    def assert_transactions_deleted_first(session: Session, *, job: ImportJobSchema) -> None:
        assert session.query(TransactionSchema).filter_by(import_job_id=job.id).count() == 0
        original_delete(session, job=job)

    monkeypatch.setattr(
        import_jobs_routes._import_job_repository,
        "delete",
        assert_transactions_deleted_first,
    )
    assert client.delete("/import-jobs/job_done").status_code == 204


def test_database_failure_rolls_back_linked_deletion(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, SessionLocal, bucket, _ = retired_deletion_client

    def fail_job_delete(session: Session, *, job: ImportJobSchema) -> None:
        del session, job
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(import_jobs_routes._import_job_repository, "delete", fail_job_delete)
    assert client.delete("/import-jobs/job_done").status_code == 500
    bucket.blob.assert_not_called()
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_done") is not None
        assert session.get(TransactionSchema, "tx_done_one") is not None
        assert session.get(TransactionSchema, "tx_done_two") is not None


@pytest.mark.parametrize("job_id", ["job_pending", "job_processing"])
def test_active_job_remains_blocked(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
    job_id: str,
) -> None:
    client, SessionLocal, bucket, _ = retired_deletion_client
    assert client.delete(f"/import-jobs/{job_id}").status_code == 409
    bucket.blob.assert_not_called()
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, job_id) is not None


def test_cross_user_job_remains_hidden(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
) -> None:
    client, SessionLocal, bucket, _ = retired_deletion_client
    assert client.delete("/import-jobs/job_other").status_code == 404
    bucket.blob.assert_not_called()
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_other") is not None
        assert session.get(TransactionSchema, "tx_other") is not None


def test_unauthenticated_delete_is_rejected_before_storage(
    retired_deletion_client: tuple[TestClient, sessionmaker[Session], Mock, object],
) -> None:
    client, SessionLocal, bucket, test_app = retired_deletion_client
    test_app.dependency_overrides.pop(get_current_user)
    response = client.delete("/import-jobs/job_done")
    assert response.status_code == 401
    bucket.blob.assert_not_called()
    with SessionLocal() as session:
        assert session.get(ImportJobSchema, "job_done") is not None
        assert session.get(TransactionSchema, "tx_done_one") is not None


def _seed_rows(SessionLocal: sessionmaker[Session]) -> None:
    with SessionLocal() as session:
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
                _job("job_done", "gabe", "done"),
                _job("job_failed", "gabe", "failed"),
                _job("job_pending", "gabe", "pending"),
                _job("job_processing", "gabe", "processing"),
                _job("job_other", "other", "done"),
            ]
        )
        session.flush()
        session.add_all(
            [
                _transaction("tx_done_one", "job_done"),
                _transaction("tx_done_two", "job_done"),
                _transaction("tx_unrelated", None),
                _transaction("tx_other", "job_other", "other", "account_other"),
            ]
        )
        session.commit()


def _job(job_id: str, user_id: str, status: str) -> ImportJobSchema:
    return ImportJobSchema(
        id=job_id,
        user_id=user_id,
        status=status,
        storage_path=RETIRED_PATH,
        file_hash=f"hash_{job_id}",
        idempotency_key=f"idem_{job_id}",
    )


def _transaction(
    transaction_id: str,
    import_job_id: str | None,
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
        is_draft=True,
    )
