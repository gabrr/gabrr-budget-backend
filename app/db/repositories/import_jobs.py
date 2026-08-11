from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.db.schemas.import_jobs import ImportJobSchema


class ImportJobRepository:
    """Persistence helpers for asynchronous import jobs."""

    def get_by_id(
        self,
        session: Session,
        *,
        job_id: str,
        user_id: str | None = None,
    ) -> ImportJobSchema | None:
        statement = select(ImportJobSchema).where(ImportJobSchema.id == job_id)
        if user_id is not None:
            statement = statement.where(ImportJobSchema.user_id == user_id)

        return session.scalars(statement).first()

    def get_by_idempotency_key(
        self,
        session: Session,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> ImportJobSchema | None:
        statement = select(ImportJobSchema).where(
            ImportJobSchema.user_id == user_id,
            ImportJobSchema.idempotency_key == idempotency_key,
        )

        return session.scalars(statement).first()

    def get_latest_active(
        self,
        session: Session,
        *,
        user_id: str,
    ) -> ImportJobSchema | None:
        return session.scalars(
            select(ImportJobSchema)
            .where(
                ImportJobSchema.user_id == user_id,
                ImportJobSchema.status.in_(["pending", "processing"]),
            )
            .order_by(
                case((ImportJobSchema.status == "processing", 0), else_=1),
                ImportJobSchema.created_at.asc(),
            )
            .limit(1)
        ).first()

    def list_recent(
        self,
        session: Session,
        *,
        user_id: str,
        limit: int = 20,
    ) -> list[ImportJobSchema]:
        return list(
            session.scalars(
                select(ImportJobSchema)
                .where(ImportJobSchema.user_id == user_id)
                .order_by(ImportJobSchema.created_at.desc())
                .limit(limit)
            ).all()
        )

    def create_pending(
        self,
        session: Session,
        *,
        user_id: str,
        idempotency_key: str,
        file_hash: str,
        storage_path: str,
        original_filename: str | None,
        content_type: str | None,
        size_bytes: int | None,
    ) -> ImportJobSchema:
        job = ImportJobSchema(
            user_id=user_id,
            status="pending",
            current_step="Upload received",
            source_type="pdf",
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            file_hash=file_hash,
            idempotency_key=idempotency_key,
        )
        session.add(job)
        session.flush()
        session.refresh(job)

        return job

    def claim_next_pending(
        self,
        session: Session,
        *,
        worker_id: str,
        stale_after: timedelta = timedelta(minutes=15),
        max_attempts: int = 3,
    ) -> ImportJobSchema | None:
        now = datetime.now(UTC)
        stale_before = now - stale_after
        candidate = session.scalars(
            select(ImportJobSchema)
            .where(
                ImportJobSchema.attempts < max_attempts,
                (
                    (ImportJobSchema.status == "pending")
                    | (
                        (ImportJobSchema.status == "processing")
                        & (ImportJobSchema.locked_at.is_not(None))
                        & (ImportJobSchema.locked_at < stale_before)
                    )
                ),
            )
            .order_by(ImportJobSchema.created_at.asc())
            .limit(1)
        ).first()
        if candidate is None:
            return None

        result = session.execute(
            update(ImportJobSchema)
            .where(
                ImportJobSchema.id == candidate.id,
                ImportJobSchema.status.in_(["pending", "processing"]),
                ImportJobSchema.attempts < max_attempts,
            )
            .values(
                status="processing",
                current_step="Processing started",
                attempts=ImportJobSchema.attempts + 1,
                locked_by=worker_id,
                locked_at=now,
                started_at=candidate.started_at or now,
                error_message=None,
            )
            .returning(ImportJobSchema.id)
        )
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            return None

        return self.get_by_id(session, job_id=claimed_id)

    def claim_by_id(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        max_attempts: int = 100,
    ) -> ImportJobSchema | None:
        now = datetime.now(UTC)
        result = session.execute(
            update(ImportJobSchema)
            .where(
                ImportJobSchema.id == job_id,
                ImportJobSchema.status == "pending",
                ImportJobSchema.attempts < max_attempts,
            )
            .values(
                status="processing",
                current_step="Processing started",
                attempts=ImportJobSchema.attempts + 1,
                locked_by=worker_id,
                locked_at=now,
                started_at=case(
                    (ImportJobSchema.started_at.is_(None), now),
                    else_=ImportJobSchema.started_at,
                ),
                error_message=None,
            )
            .returning(ImportJobSchema.id)
        )
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            return None

        return self.get_by_id(session, job_id=claimed_id)

    def mark_step(
        self,
        session: Session,
        job_id: str,
        *,
        current_step: str,
    ) -> None:
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(current_step=current_step)
        )

    def save_agent_input(
        self,
        session: Session,
        job_id: str,
        *,
        input_payload_json: dict,
    ) -> None:
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(agent_input_payload_json=input_payload_json)
        )

    def save_agent_output(
        self,
        session: Session,
        job_id: str,
        *,
        output_payload_json: dict,
    ) -> None:
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(agent_output_payload_json=output_payload_json)
        )

    def save_statement_metadata(
        self,
        session: Session,
        job_id: str,
        *,
        metadata: dict,
    ) -> None:
        allowed_fields = {
            "statement_kind",
            "statement_kind_confidence",
            "statement_kind_reason",
            "statement_period_start",
            "statement_period_end",
            "institution_name",
            "account_hint",
            "statement_kind_source",
        }
        values = {key: metadata[key] for key in allowed_fields if key in metadata}
        if not values:
            return

        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(**values)
        )

    def mark_done(self, session: Session, job_id: str) -> None:
        now = datetime.now(UTC)
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(
                status="done",
                current_step="Draft transactions saved",
                locked_by=None,
                locked_at=None,
                finished_at=now,
                error_message=None,
            )
        )

    def mark_failed(self, session: Session, job_id: str, *, error_message: str) -> None:
        now = datetime.now(UTC)
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(
                status="failed",
                current_step="Failed",
                locked_by=None,
                locked_at=None,
                finished_at=now,
                error_message=error_message[:1000],
            )
        )

    def mark_pending_for_retry(
        self,
        session: Session,
        job_id: str,
        *,
        error_message: str,
    ) -> None:
        session.execute(
            update(ImportJobSchema)
            .where(ImportJobSchema.id == job_id)
            .values(
                status="pending",
                current_step="Waiting to retry",
                locked_by=None,
                locked_at=None,
                finished_at=None,
                error_message=error_message[:1000],
            )
        )

    def delete(
        self,
        session: Session,
        *,
        job: ImportJobSchema,
    ) -> None:
        session.delete(job)
