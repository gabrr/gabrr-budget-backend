from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.db.schemas import Base
from app.db.schemas.accounts import AccountSchema
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
        _seed_rows(session)
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
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.clear()


def test_wealth_checkpoint_lifecycle(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    created = client.post(
        "/wealth/checkpoints",
        json={
            "checkpoint_date": "2026-05-18",
            "wealth_amount": "100000.00",
            "currency": "brl",
        },
    )
    assert created.status_code == 201
    checkpoint = created.json()
    assert checkpoint["wealth_amount"] == "100000.00"
    assert checkpoint["currency"] == "BRL"

    duplicate = client.post(
        "/wealth/checkpoints",
        json={
            "checkpoint_date": "2026-05-18",
            "wealth_amount": "100000.00",
            "currency": "BRL",
        },
    )
    assert duplicate.status_code == 409

    listed = client.get("/wealth/checkpoints")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["checkpoints"]] == [checkpoint["id"]]

    deleted = client.delete(f"/wealth/checkpoints/{checkpoint['id']}")
    assert deleted.status_code == 204
    assert client.get("/wealth/checkpoints").json()["checkpoints"] == []


def test_projection_settings_default_and_upsert(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session

    default_response = client.get("/wealth/projection-settings")
    assert default_response.status_code == 200
    assert default_response.json() == {
        "average_annual_return_multiplier": "1.0000",
        "is_default": True,
    }

    saved_response = client.put(
        "/wealth/projection-settings",
        json={"average_annual_return_multiplier": "1.0800"},
    )
    assert saved_response.status_code == 200
    assert saved_response.json() == {
        "average_annual_return_multiplier": "1.0800",
        "is_default": False,
    }


def test_monthly_capacity_report_aggregates_and_projects(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session
    client.post(
        "/wealth/checkpoints",
        json={"checkpoint_date": "2026-05-18", "wealth_amount": "100000.00"},
    )
    client.put(
        "/wealth/projection-settings",
        json={"average_annual_return_multiplier": "1.0800"},
    )

    response = client.get("/reports/monthly-capacity?anchor_month=2026-05&months=4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["average_annual_return_multiplier"] == "1.0800"
    assert "annotations" not in payload
    assert len(payload["months"]) == 4

    may = payload["months"][0]
    assert may["month"] == "2026-05"
    assert may["income"] == "18000.00"
    assert may["fixed_costs"] == "2500.00"
    assert may["living_costs"] == "3200.00"
    assert may["debt_installments"] == "3305.00"
    assert may["investment_capacity"] == "8995.00"
    assert may["projected_wealth"] == "100000.00"
    assert may["has_debt_pressure"] is True

    june = payload["months"][1]
    assert june["debt_installments"] == "0.00"
    assert june["has_debt_drop"] is True
    assert june["has_investment_capacity"] is True
    assert Decimal(june["projected_wealth"]) > Decimal("100000.00")

    preview_response = client.get(
        "/reports/monthly-capacity?anchor_month=2026-05&months=1&include_drafts=true"
    )
    assert preview_response.status_code == 200
    preview_may = preview_response.json()["months"][0]
    assert preview_may["living_costs"] == "4199.00"
    assert preview_may["investment_capacity"] == "7996.00"


def test_monthly_capacity_report_uses_null_projection_before_checkpoint(
    client_session: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_session
    client.post(
        "/wealth/checkpoints",
        json={"checkpoint_date": "2026-06-10", "wealth_amount": "100000.00"},
    )

    response = client.get("/reports/monthly-capacity?anchor_month=2026-05&months=2")

    assert response.status_code == 200
    months = response.json()["months"]
    assert months[0]["projected_wealth"] is None
    assert months[1]["projected_wealth"] == "100000.00"


def _seed_rows(session: Session) -> None:
    session.add_all(
        [
            UserSchema(id="gabe", email="gabe@example.test", display_name="Gabe"),
            AccountSchema(
                id="acct_demo_checking",
                user_id="gabe",
                name="Demo Checking",
                type="checking",
                currency="BRL",
            ),
            TransactionSchema(
                id="tx_income_may",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 1),
                description="Income",
                amount=Decimal("18000.00"),
                report_bucket="income",
                transaction_nature="income",
            ),
            TransactionSchema(
                id="tx_fixed_may",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 2),
                description="Rent",
                amount=Decimal("-2500.00"),
                report_bucket="fixed_cost",
                transaction_nature="expense",
            ),
            TransactionSchema(
                id="tx_living_may",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 3),
                description="Living",
                amount=Decimal("-3200.00"),
                report_bucket="living_cost",
                transaction_nature="expense",
            ),
            TransactionSchema(
                id="tx_debt_may",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 4),
                description="Card installment",
                amount=Decimal("-3305.00"),
                report_bucket="debt_installment",
                transaction_nature="expense",
            ),
            TransactionSchema(
                id="tx_income_june",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 6, 1),
                description="Income",
                amount=Decimal("18000.00"),
                report_bucket="income",
                transaction_nature="income",
            ),
            TransactionSchema(
                id="tx_draft_ignored",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 8),
                description="Draft ignored",
                amount=Decimal("-999.00"),
                report_bucket="living_cost",
                transaction_nature="expense",
                is_draft=True,
            ),
            TransactionSchema(
                id="tx_reverted_ignored",
                user_id="gabe",
                account_id="acct_demo_checking",
                posted_at=date(2026, 5, 9),
                description="Reverted ignored",
                amount=Decimal("-999.00"),
                report_bucket="living_cost",
                transaction_nature="expense",
                reverted_at=datetime(2026, 5, 10),
            ),
        ]
    )
