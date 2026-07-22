from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserId, new_id


class UploadedFileSchema(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: new_id("file"),
    )
    user_id: Mapped[str] = mapped_column(
        UserId(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None]
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="stored", nullable=False)

    agent_runs = relationship("AgentRunSchema", back_populates="uploaded_file")
    imports = relationship("ImportSchema", back_populates="uploaded_file")
    user = relationship("UserSchema", back_populates="uploaded_files")
