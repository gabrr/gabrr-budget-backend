from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId


class UserSchema(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UserId(), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))

    accounts = relationship("AccountSchema", back_populates="user")
    activity_events = relationship("ActivityEventSchema", back_populates="user")
    budgets = relationship("BudgetSchema", back_populates="user")
    imports = relationship("ImportSchema", back_populates="user")
    learned_rules = relationship("LearnedRuleSchema", back_populates="user")
    transactions = relationship("TransactionSchema", back_populates="user")
    uploaded_files = relationship("UploadedFileSchema", back_populates="user")
    wealth_checkpoints = relationship("WealthCheckpointSchema", back_populates="user")
    wealth_projection_settings = relationship(
        "WealthProjectionSettingsSchema",
        back_populates="user",
        uselist=False,
    )
