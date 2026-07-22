from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class BudgetSchema(TimestampMixin, Base):
    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("bdg"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), nullable=False)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)

    account = relationship("AccountSchema", back_populates="budgets")
    category = relationship("CategorySchema", back_populates="budgets")
    user = relationship("UserSchema", back_populates="budgets")
