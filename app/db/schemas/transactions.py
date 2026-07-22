from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class TransactionSchema(TimestampMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("tx"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    source_import_id: Mapped[str | None] = mapped_column(ForeignKey("imports.id"))
    import_job_id: Mapped[str | None] = mapped_column(ForeignKey("import_jobs.id"))
    posted_at: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(40))
    installments: Mapped[int | None]
    installments_current: Mapped[int | None]
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_draft: Mapped[bool] = mapped_column(default=False, nullable=False)
    statement_kind: Mapped[str] = mapped_column(
        String(40),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    transaction_nature: Mapped[str] = mapped_column(
        String(40),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    report_bucket: Mapped[str] = mapped_column(
        String(40),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    classification_source: Mapped[str] = mapped_column(
        String(40),
        default="system",
        server_default="system",
        nullable=False,
    )
    classification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    classification_reason: Mapped[str | None] = mapped_column(String(1000))
    running_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    account = relationship("AccountSchema", back_populates="transactions")
    category = relationship("CategorySchema", back_populates="transactions")
    source_import = relationship("ImportSchema", back_populates="transactions")
    user = relationship("UserSchema", back_populates="transactions")

    __table_args__ = (
        CheckConstraint(
            "statement_kind in ('checking_account', 'credit_card', 'unknown')",
            name="ck_transactions_statement_kind",
        ),
        CheckConstraint(
            "transaction_nature in ('income', 'expense', 'transfer', 'refund', "
            "'card_payment', 'unknown')",
            name="ck_transactions_transaction_nature",
        ),
        CheckConstraint(
            "report_bucket in ('income', 'debt_installment', 'fixed_cost', "
            "'living_cost', 'excluded', 'unknown')",
            name="ck_transactions_report_bucket",
        ),
        CheckConstraint(
            "classification_source in ('agent', 'user', 'system')",
            name="ck_transactions_classification_source",
        ),
        CheckConstraint(
            "classification_confidence is null or "
            "(classification_confidence >= 0 and classification_confidence <= 1)",
            name="ck_transactions_classification_confidence_range",
        ),
        Index("ix_transactions_import_job_id", "import_job_id"),
        Index(
            "ix_transactions_report_readiness",
            "user_id",
            "is_draft",
            "reverted_at",
            "posted_at",
            "report_bucket",
        ),
    )
