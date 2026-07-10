from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.wealth import (
    WealthCheckpoint,
    WealthCheckpointCreate,
    WealthProjectionSettings,
    WealthProjectionSettingsUpdate,
)
from app.db.schemas.wealth import WealthCheckpointSchema, WealthProjectionSettingsSchema

DEFAULT_RETURN_MULTIPLIER = Decimal("1.0000")


def wealth_checkpoint_schema_to_model(row: WealthCheckpointSchema) -> WealthCheckpoint:
    return WealthCheckpoint(
        id=row.id,
        checkpoint_date=row.checkpoint_date,
        wealth_amount=row.wealth_amount,
        currency=row.currency,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class WealthRepository:
    def create_checkpoint(
        self,
        session: Session,
        *,
        user_id: str,
        payload: WealthCheckpointCreate,
    ) -> WealthCheckpointSchema:
        row = WealthCheckpointSchema(
            user_id=user_id,
            checkpoint_date=payload.checkpoint_date,
            wealth_amount=payload.wealth_amount,
            currency=payload.currency.upper(),
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as error:
            raise ValueError("A checkpoint already exists for this date and currency") from error

        return row

    def list_checkpoints(
        self,
        session: Session,
        *,
        user_id: str,
        currency: str | None = None,
    ) -> list[WealthCheckpointSchema]:
        statement = select(WealthCheckpointSchema).where(
            WealthCheckpointSchema.user_id == user_id,
        )
        if currency is not None:
            statement = statement.where(WealthCheckpointSchema.currency == currency.upper())
        statement = statement.order_by(
            WealthCheckpointSchema.checkpoint_date.asc(),
            WealthCheckpointSchema.created_at.asc(),
        )

        return list(session.scalars(statement).all())

    def delete_checkpoint(
        self,
        session: Session,
        *,
        user_id: str,
        checkpoint_id: str,
    ) -> bool:
        row = session.get(WealthCheckpointSchema, checkpoint_id)
        if row is None or row.user_id != user_id:
            return False
        session.delete(row)
        return True

    def get_projection_settings(
        self,
        session: Session,
        *,
        user_id: str,
    ) -> WealthProjectionSettings:
        row = self._get_projection_settings_row(session, user_id=user_id)
        if row is None:
            return WealthProjectionSettings(
                average_annual_return_multiplier=DEFAULT_RETURN_MULTIPLIER,
                is_default=True,
            )
        return WealthProjectionSettings(
            average_annual_return_multiplier=row.average_annual_return_multiplier,
            is_default=False,
        )

    def upsert_projection_settings(
        self,
        session: Session,
        *,
        user_id: str,
        payload: WealthProjectionSettingsUpdate,
    ) -> WealthProjectionSettings:
        row = self._get_projection_settings_row(session, user_id=user_id)
        if row is None:
            row = WealthProjectionSettingsSchema(
                user_id=user_id,
                average_annual_return_multiplier=payload.average_annual_return_multiplier,
            )
            session.add(row)
        else:
            row.average_annual_return_multiplier = payload.average_annual_return_multiplier
        session.flush()

        return WealthProjectionSettings(
            average_annual_return_multiplier=row.average_annual_return_multiplier,
            is_default=False,
        )

    def latest_checkpoint_by_month(
        self,
        session: Session,
        *,
        user_id: str,
        start_date: date,
        end_date: date,
        currency: str,
    ) -> dict[str, WealthCheckpointSchema]:
        checkpoints = self.list_checkpoints(session, user_id=user_id, currency=currency)
        latest_by_month: dict[str, WealthCheckpointSchema] = {}
        for checkpoint in checkpoints:
            if checkpoint.checkpoint_date < start_date or checkpoint.checkpoint_date > end_date:
                continue
            month_key = checkpoint.checkpoint_date.strftime("%Y-%m")
            existing = latest_by_month.get(month_key)
            if existing is None or checkpoint.checkpoint_date >= existing.checkpoint_date:
                latest_by_month[month_key] = checkpoint

        return latest_by_month

    def _get_projection_settings_row(
        self,
        session: Session,
        *,
        user_id: str,
    ) -> WealthProjectionSettingsSchema | None:
        statement = select(WealthProjectionSettingsSchema).where(
            WealthProjectionSettingsSchema.user_id == user_id,
        )

        return session.scalars(statement).first()
