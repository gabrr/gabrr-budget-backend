from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserId, new_id


class ImportJobSchema(TimestampMixin, Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("job"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(40), default="pdf", nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_input_payload_json: Mapped[dict | None] = mapped_column(JSON)
    agent_output_payload_json: Mapped[dict | None] = mapped_column(JSON)
    statement_kind: Mapped[str] = mapped_column(
        String(40),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    statement_kind_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    statement_kind_reason: Mapped[str | None] = mapped_column(String(1000))
    statement_period_start: Mapped[date | None] = mapped_column(Date)
    statement_period_end: Mapped[date | None] = mapped_column(Date)
    institution_name: Mapped[str | None] = mapped_column(String(255))
    account_hint: Mapped[str | None] = mapped_column(String(255))
    statement_kind_source: Mapped[str] = mapped_column(
        String(40),
        default="system",
        server_default="system",
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_import_jobs_user_idempotency_key"),
        CheckConstraint(
            "statement_kind in ('checking_account', 'credit_card', 'unknown')",
            name="ck_import_jobs_statement_kind",
        ),
        CheckConstraint(
            "statement_kind_source in ('agent', 'user', 'system')",
            name="ck_import_jobs_statement_kind_source",
        ),
        CheckConstraint(
            "statement_kind_confidence is null or "
            "(statement_kind_confidence >= 0 and statement_kind_confidence <= 1)",
            name="ck_import_jobs_statement_kind_confidence_range",
        ),
    )
