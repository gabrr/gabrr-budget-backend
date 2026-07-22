from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class WealthCheckpointSchema(TimestampMixin, Base):
    __tablename__ = "wealth_checkpoints"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("wch"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    checkpoint_date: Mapped[date] = mapped_column(Date, nullable=False)
    wealth_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)

    user = relationship("UserSchema", back_populates="wealth_checkpoints")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "checkpoint_date",
            "currency",
            name="uq_wealth_checkpoints_user_date_currency",
        ),
        Index("ix_wealth_checkpoints_user_date", "user_id", "checkpoint_date"),
    )


class WealthProjectionSettingsSchema(TimestampMixin, Base):
    __tablename__ = "wealth_projection_settings"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("wps"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    average_annual_return_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        default=Decimal("1.0000"),
        nullable=False,
    )

    user = relationship("UserSchema", back_populates="wealth_projection_settings")
