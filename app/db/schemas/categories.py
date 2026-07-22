from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class CategorySchema(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_categories_user_key"),)

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("cat"),
    )
    user_id: Mapped[str | None] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)

    budgets = relationship("BudgetSchema", back_populates="category")
    transactions = relationship("TransactionSchema", back_populates="category")
