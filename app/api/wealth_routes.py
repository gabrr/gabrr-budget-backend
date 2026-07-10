from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.wealth import (
    WealthCheckpoint,
    WealthCheckpointCreate,
    WealthCheckpointList,
    WealthProjectionSettings,
    WealthProjectionSettingsUpdate,
)
from app.db.repositories.wealth import WealthRepository, wealth_checkpoint_schema_to_model
from app.db.session import get_session

wealth_router = APIRouter(prefix="/wealth", tags=["wealth"])
_wealth_repository = WealthRepository()


@wealth_router.post("/checkpoints", response_model=WealthCheckpoint, status_code=201)
async def create_wealth_checkpoint(
    payload: WealthCheckpointCreate,
    session: Session = Depends(get_session),
) -> WealthCheckpoint:
    try:
        row = _wealth_repository.create_checkpoint(
            session,
            user_id=settings.default_user_id,
            payload=payload,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return wealth_checkpoint_schema_to_model(row)


@wealth_router.get("/checkpoints", response_model=WealthCheckpointList)
async def list_wealth_checkpoints(
    session: Session = Depends(get_session),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
) -> WealthCheckpointList:
    rows = _wealth_repository.list_checkpoints(
        session,
        user_id=settings.default_user_id,
        currency=currency.upper() if currency is not None else None,
    )

    return WealthCheckpointList(
        checkpoints=[wealth_checkpoint_schema_to_model(row) for row in rows]
    )


@wealth_router.delete("/checkpoints/{checkpoint_id}", status_code=204)
async def delete_wealth_checkpoint(
    checkpoint_id: str,
    session: Session = Depends(get_session),
) -> Response:
    deleted = _wealth_repository.delete_checkpoint(
        session,
        user_id=settings.default_user_id,
        checkpoint_id=checkpoint_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Wealth checkpoint not found")

    return Response(status_code=204)


@wealth_router.get("/projection-settings", response_model=WealthProjectionSettings)
async def get_projection_settings(
    session: Session = Depends(get_session),
) -> WealthProjectionSettings:
    return _wealth_repository.get_projection_settings(
        session,
        user_id=settings.default_user_id,
    )


@wealth_router.put("/projection-settings", response_model=WealthProjectionSettings)
async def upsert_projection_settings(
    payload: WealthProjectionSettingsUpdate,
    session: Session = Depends(get_session),
) -> WealthProjectionSettings:
    return _wealth_repository.upsert_projection_settings(
        session,
        user_id=settings.default_user_id,
        payload=payload,
    )
