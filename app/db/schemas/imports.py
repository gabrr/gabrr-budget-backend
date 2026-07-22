from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class ImportSchema(TimestampMixin, Base):
    __tablename__ = "imports"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("imp"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_file_id: Mapped[str] = mapped_column(
        ForeignKey("uploaded_files.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), default="uploaded", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent_runs = relationship("AgentRunSchema", back_populates="import_record")
    events = relationship("ImportEventSchema", back_populates="import_record")
    transactions = relationship("TransactionSchema", back_populates="source_import")
    uploaded_file = relationship("UploadedFileSchema", back_populates="imports")
    user = relationship("UserSchema", back_populates="imports")
