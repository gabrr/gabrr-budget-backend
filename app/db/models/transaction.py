from __future__ import annotations

from datetime import date as DateValue
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.db.models.base import TimestampModel
from app.db.models.categories import ExpenseCategory


class Transaction(TimestampModel):
    id: str | None = None
    user_id: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    category: ExpenseCategory | None = None
    source_import_id: str | None = None
    import_job_id: str | None = None
    posted_at: DateValue | None = None
    date: DateValue | None = None
    description: str | None = Field(default=None, min_length=1)
    merchant_name: str | None = None
    merchant: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    payment_method: str | None = None
    installments: int | None = None
    installments_current: int | None = None
    card_name: str | None = None
    comment: str | None = None
    tags: list[str] | None = None
    reverted_at: datetime | None = None
    is_draft: bool = False
    statement_kind: str = "unknown"
    transaction_nature: str = "unknown"
    report_bucket: str = "unknown"
    classification_source: str = "system"
    classification_confidence: Decimal | None = None
    classification_reason: str | None = None
    running_balance: Decimal | None = None

    @field_validator("amount", "classification_confidence", "running_balance", mode="before")
    @classmethod
    def _decimal_fields(cls, value: object) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            normalized = value.strip().replace(",", ".")
            return Decimal(normalized) if normalized else None
        return Decimal(str(value))
