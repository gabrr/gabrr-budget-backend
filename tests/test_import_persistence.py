from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.repositories.import_jobs import ImportJobRepository
from app.db.repositories.transactions import (
    TransactionRepository,
    transaction_schema_to_model,
)
from app.db.schemas import Base
from app.db.schemas.accounts import AccountSchema
from app.db.schemas.import_jobs import ImportJobSchema
from app.db.schemas.users import UserSchema
from app.workers.import_worker.data_mapping import (
    normalize_imported_amount,
    parse_agent_result_for_persistence,
)


def _valid_agent_result() -> dict:
    return {
        "statement": {
            "kind": "credit_card",
            "kind_confidence": "0.9700",
            "kind_reason": "Statement includes card purchases and installment fields.",
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
            "institution_name": "Rico",
            "account_hint": "Visa final 1234",
        },
        "transactions": [
            {
                "date": "2026-05-10",
                "description": "Grocery Store",
                "amount": "120.45",
                "currency": "brl",
                "payment_method": "credit_card",
                "merchant_name": "Grocery Store",
                "installments": 3,
                "installments_current": 1,
                "running_balance": "500.55",
                "transaction_nature": "expense",
                "report_bucket": "living_cost",
                "classification_confidence": "0.9300",
                "classification_reason": "Recurring grocery purchase.",
            }
        ],
    }


def test_parse_agent_result_maps_statement_and_transaction_metadata() -> None:
    metadata, transactions = parse_agent_result_for_persistence(
        _valid_agent_result(),
        import_job_id="job_123",
    )

    assert metadata == {
        "statement_kind": "credit_card",
        "statement_kind_confidence": Decimal("0.9700"),
        "statement_kind_reason": "Statement includes card purchases and installment fields.",
        "statement_period_start": date(2026, 5, 1),
        "statement_period_end": date(2026, 5, 31),
        "institution_name": "Rico",
        "account_hint": "Visa final 1234",
        "statement_kind_source": "agent",
    }
    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction.import_job_id == "job_123"
    assert transaction.statement_kind == "credit_card"
    assert transaction.amount == Decimal("-120.45")
    assert transaction.transaction_nature == "expense"
    assert transaction.report_bucket == "living_cost"
    assert transaction.classification_source == "agent"
    assert transaction.classification_confidence == Decimal("0.9300")
    assert transaction.classification_reason == "Recurring grocery purchase."
    assert transaction.running_balance == Decimal("500.55")
    assert transaction.currency == "BRL"
    assert transaction.is_draft is True


def test_normalize_imported_amount_flips_credit_card_sign_only() -> None:
    assert normalize_imported_amount(Decimal("39.99"), "credit_card") == Decimal("-39.99")
    assert normalize_imported_amount(Decimal("-39.99"), "credit_card") == Decimal("39.99")
    assert normalize_imported_amount(Decimal("0.00"), "credit_card") == Decimal("0.00")
    assert normalize_imported_amount(Decimal("-75.00"), "instant_payment") == Decimal("-75.00")
    assert normalize_imported_amount(Decimal("5002.56"), "bank_transfer") == Decimal("5002.56")
    assert normalize_imported_amount(Decimal("12.34"), None) == Decimal("12.34")


def test_parse_agent_result_rejects_missing_statement() -> None:
    payload = _valid_agent_result()
    payload.pop("statement")

    with pytest.raises(ValueError, match="statement object"):
        parse_agent_result_for_persistence(payload, import_job_id="job_123")


def test_parse_agent_result_rejects_invalid_transaction_enum_with_index() -> None:
    payload = _valid_agent_result()
    payload["transactions"][0]["report_bucket"] = "maybe_food"

    with pytest.raises(ValueError, match=r"transactions\[0\]\.report_bucket"):
        parse_agent_result_for_persistence(payload, import_job_id="job_123")


def test_parse_agent_result_rejects_invalid_statement_period() -> None:
    payload = _valid_agent_result()
    payload["statement"]["period_start"] = "2026-06-01"
    payload["statement"]["period_end"] = "2026-05-01"

    with pytest.raises(ValueError, match="statement.period_start"):
        parse_agent_result_for_persistence(payload, import_job_id="job_123")


def test_repositories_persist_and_replace_import_classification_fields() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    import_jobs = ImportJobRepository()
    transactions = TransactionRepository()
    metadata, transaction_items = parse_agent_result_for_persistence(
        _valid_agent_result(),
        import_job_id="job_123",
    )

    with Session() as session:
        session.add_all(
            [
                UserSchema(
                    id="user_123",
                    email="user@example.test",
                    display_name="Test User",
                ),
                AccountSchema(
                    id="acct_123",
                    user_id="user_123",
                    name="Checking",
                    type="checking",
                    currency="BRL",
                ),
                ImportJobSchema(
                id="job_123",
                user_id="user_123",
                status="processing",
                storage_path="/tmp/example.pdf",
                file_hash="abc",
                idempotency_key="idem",
                ),
            ]
        )
        session.commit()

    with Session() as session:
        import_jobs.save_statement_metadata(session, "job_123", metadata=metadata)
        transactions.create_many(
            session,
            transaction_items,
            user_id="user_123",
            default_account_id="acct_123",
        )
        session.commit()

    with Session() as session:
        job = import_jobs.get_by_id(session, job_id="job_123")
        assert job is not None
        assert job.statement_kind == "credit_card"
        assert job.statement_kind_source == "agent"

        stored, total = transactions.list_filtered(
            session,
            user_id="user_123",
            is_draft=True,
        )
        assert total == 1
        model = transaction_schema_to_model(stored[0])
        assert model.import_job_id == "job_123"
        assert model.statement_kind == "credit_card"
        assert model.transaction_nature == "expense"
        assert model.report_bucket == "living_cost"
        assert model.classification_source == "agent"
        assert model.classification_confidence == Decimal("0.9300")
        assert model.running_balance == Decimal("500.55")

        deleted = transactions.delete_drafts_for_import_job(session, import_job_id="job_123")
        session.commit()
        assert deleted == 1

    with Session() as session:
        stored, total = transactions.list_filtered(
            session,
            user_id="user_123",
            is_draft=True,
        )
        assert total == 0
        assert stored == []
