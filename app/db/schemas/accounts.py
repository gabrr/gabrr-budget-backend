from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class AccountSchema(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("acct"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    institution_name: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    user = relationship("UserSchema", back_populates="accounts")
    budgets = relationship("BudgetSchema", back_populates="account")
    transactions = relationship("TransactionSchema", back_populates="account")
