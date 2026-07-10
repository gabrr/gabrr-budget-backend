from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models.transaction import Transaction
from app.db.schemas import Base
from app.db.schemas.accounts import AccountSchema
from app.db.schemas.categories import CategorySchema
from app.db.schemas.transactions import TransactionSchema
from app.db.schemas.users import UserSchema
from app.db.session import get_session
from app.main import app


@pytest.fixture()
def client_session() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as session:
        _seed_transaction_correction_rows(session)
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
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.clear()


def test_patch_classification_defaults_user_metadata(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, SessionLocal = client_session

    response = client.patch("/transactions/tx_correction", json={"report_bucket": "fixed_cost"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_bucket"] == "fixed_cost"
    assert payload["classification_source"] == "user"
    assert payload["classification_confidence"] == "1.0000"
    assert payload["classification_reason"] == "User corrected classification."

    with SessionLocal() as session:
        stored = session.get(TransactionSchema, "tx_correction")
        assert stored is not None
        assert stored.report_bucket == "fixed_cost"
        assert stored.classification_source == "user"


def test_patch_classification_preserves_explicit_confidence_and_reason(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.patch(
        "/transactions/tx_correction",
        json={
            "transaction_nature": "refund",
            "classification_confidence": "0.9000",
            "classification_reason": "  User marked this as a refund.  ",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_nature"] == "refund"
    assert payload["classification_source"] == "user"
    assert payload["classification_confidence"] == "0.9000"
    assert payload["classification_reason"] == "User marked this as a refund."


def test_patch_review_fields_does_not_change_classification_metadata(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.patch(
        "/transactions/tx_correction",
        json={"is_draft": False, "category_id": "cat_food"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_draft"] is False
    assert payload["category_id"] == "cat_food"
    assert payload["classification_source"] == "agent"
    assert payload["classification_confidence"] == "0.7000"
    assert payload["classification_reason"] == "Agent classified this transaction."


def test_patch_category_id_can_clear_category(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session
    client.patch("/transactions/tx_correction", json={"category_id": "cat_food"})

    response = client.patch("/transactions/tx_correction", json={"category_id": None})

    assert response.status_code == 200
    assert response.json()["category_id"] is None


def test_patch_rejects_invalid_classification_values(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.patch("/transactions/tx_correction", json={"report_bucket": "food"})

    assert response.status_code == 422
    assert "Invalid report_bucket" in response.json()["detail"]


def test_patch_rejects_direct_protected_fields(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.patch(
        "/transactions/tx_correction",
        json={"classification_source": "agent"},
    )

    assert response.status_code == 422
    assert "classification_source" in response.json()["detail"]


def test_patch_rejects_unauthorized_category(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.patch(
        "/transactions/tx_correction",
        json={"category_id": "cat_other_user"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "category_id is not available to this user"


def test_transaction_model_rejects_string_is_draft() -> None:
    with pytest.raises(ValidationError):
        Transaction(is_draft="false")


def test_list_transactions_filters_drafts_by_import_job(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.get("/transactions?is_draft=true&import_job_id=job_a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert {item["id"] for item in payload["items"]} == {
        "tx_job_a_food",
        "tx_job_a_uncategorized",
    }
    assert all(item["import_job_id"] == "job_a" for item in payload["items"])
    assert all(item["is_draft"] is True for item in payload["items"])


def test_list_transactions_filters_import_job_with_category(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.get("/transactions?is_draft=true&import_job_id=job_a&category=food")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "tx_job_a_food"
    assert payload["items"][0]["category"] == "food"


def test_list_transactions_filters_committed_by_import_job(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.get("/transactions?is_draft=false&import_job_id=job_a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "tx_job_a_committed"
    assert payload["items"][0]["is_draft"] is False


def test_list_transactions_without_import_job_still_lists_drafts(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    response = client.get("/transactions?is_draft=true")

    assert response.status_code == 200
    payload = response.json()
    item_ids = {item["id"] for item in payload["items"]}
    assert payload["total"] == 4
    assert "tx_other_user_job_a" not in item_ids
    assert {"tx_correction", "tx_job_a_food", "tx_job_a_uncategorized", "tx_job_b"}.issubset(
        item_ids
    )


def _seed_transaction_correction_rows(session: Session) -> None:
    session.add_all(
        [
            UserSchema(id="gabe", email="gabe@example.test", display_name="Gabe"),
            UserSchema(id="other_user", email="other@example.test", display_name="Other"),
            AccountSchema(
                id="acct_demo_checking",
                user_id="gabe",
                name="Demo Checking",
                type="checking",
                currency="BRL",
            ),
            AccountSchema(
                id="acct_other_checking",
                user_id="other_user",
                name="Other Checking",
                type="checking",
                currency="BRL",
            ),
            CategorySchema(
                id="cat_food",
                user_id="gabe",
                key="food",
                name="Food",
                is_system=False,
            ),
            CategorySchema(
                id="cat_other_user",
                user_id="other_user",
                key="food",
                name="Other Food",
                is_system=False,
            ),
            TransactionSchema(
                id="tx_correction",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 10),
                description="Original transaction",
                amount=Decimal("-100.00"),
                currency="BRL",
                is_draft=True,
                statement_kind="credit_card",
                transaction_nature="expense",
                report_bucket="living_cost",
                classification_source="agent",
                classification_confidence=Decimal("0.7000"),
                classification_reason="Agent classified this transaction.",
            ),
            TransactionSchema(
                id="tx_job_a_food",
                user_id="gabe",
                account_id="acct_demo_checking",
                category_id="cat_food",
                import_job_id="job_a",
                posted_at=date(2026, 5, 12),
                description="Job A food",
                amount=Decimal("-42.00"),
                currency="BRL",
                is_draft=True,
                statement_kind="credit_card",
                transaction_nature="expense",
                report_bucket="living_cost",
                classification_source="agent",
                classification_confidence=Decimal("0.8600"),
                classification_reason="Bucket set to living_cost.",
            ),
            TransactionSchema(
                id="tx_job_a_uncategorized",
                user_id="gabe",
                account_id="acct_demo_checking",
                import_job_id="job_a",
                posted_at=date(2026, 5, 11),
                description="Job A uncategorized",
                amount=Decimal("-12.00"),
                currency="BRL",
                is_draft=True,
                statement_kind="credit_card",
                transaction_nature="expense",
                report_bucket="unknown",
                classification_source="system",
                classification_confidence=None,
                classification_reason=None,
            ),
            TransactionSchema(
                id="tx_job_a_committed",
                user_id="gabe",
                account_id="acct_demo_checking",
                import_job_id="job_a",
                posted_at=date(2026, 5, 9),
                description="Job A committed",
                amount=Decimal("-15.00"),
                currency="BRL",
                is_draft=False,
                statement_kind="credit_card",
                transaction_nature="expense",
                report_bucket="fixed_cost",
                classification_source="user",
                classification_confidence=Decimal("1.0000"),
                classification_reason="User corrected classification.",
            ),
            TransactionSchema(
                id="tx_job_b",
                user_id="gabe",
                account_id="acct_demo_checking",
                import_job_id="job_b",
                posted_at=date(2026, 5, 8),
                description="Job B draft",
                amount=Decimal("-22.00"),
                currency="BRL",
                is_draft=True,
                statement_kind="checking_account",
                transaction_nature="expense",
                report_bucket="living_cost",
                classification_source="agent",
                classification_confidence=Decimal("0.7400"),
                classification_reason="Bucket set to living_cost.",
            ),
            TransactionSchema(
                id="tx_other_user_job_a",
                user_id="other_user",
                account_id="acct_other_checking",
                import_job_id="job_a",
                posted_at=date(2026, 5, 7),
                description="Other user same job id",
                amount=Decimal("-99.00"),
                currency="BRL",
                is_draft=True,
                statement_kind="credit_card",
                transaction_nature="expense",
                report_bucket="living_cost",
                classification_source="agent",
                classification_confidence=Decimal("0.8000"),
                classification_reason="Should not leak.",
            ),
        ]
    )
