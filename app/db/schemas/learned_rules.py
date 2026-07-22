from __future__ import annotations

from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class LearnedRuleSchema(TimestampMixin, Base):
    __tablename__ = "learned_rules"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("rule"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False)
    match_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    result_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    user = relationship("UserSchema", back_populates="learned_rules")
