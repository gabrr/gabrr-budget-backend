from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db.models.import_jobs import ImportJobPublic
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.schemas.import_jobs import ImportJobSchema
from app.db.session import SessionLocal, get_session

import_jobs_router = APIRouter(prefix="/import-jobs", tags=["import-jobs"])
_import_job_repository = ImportJobRepository()


def import_job_event_key(job: ImportJobSchema) -> tuple[str, str | None, str | None, datetime | None]:
    return (job.status, job.current_step, job.error_message, job.finished_at)


def import_job_to_public(job: ImportJobSchema) -> ImportJobPublic:
    return ImportJobPublic(
        job_id=job.id,
        status=job.status,
        current_step=job.current_step,
        error_message=job.error_message,
        original_filename=job.original_filename,
        statement_kind=job.statement_kind or "unknown",
        statement_kind_confidence=job.statement_kind_confidence,
        status_url=f"/import-jobs/{job.id}",
        events_url=f"/import-jobs/{job.id}/events",
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        started_at=_isoformat_or_none(job.started_at),
        finished_at=_isoformat_or_none(job.finished_at),
    )


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@import_jobs_router.get("", response_model=list[ImportJobPublic])
async def list_import_jobs(
    current_user: CurrentUser,
    session: Session = Depends(get_session),
    limit: int = 20,
) -> list[ImportJobPublic]:
    bounded_limit = min(max(limit, 1), 50)
    jobs = _import_job_repository.list_recent(
        session,
        user_id=current_user.id,
        limit=bounded_limit,
    )

    return [import_job_to_public(job) for job in jobs]


@import_jobs_router.get("/active", response_model=ImportJobPublic | None)
async def get_active_import_job(
    current_user: CurrentUser,
    session: Session = Depends(get_session),
) -> Response | ImportJobPublic:
    job = _import_job_repository.get_latest_active(
        session,
        user_id=current_user.id,
    )
    if job is None:
        return Response(status_code=204)

    return import_job_to_public(job)


@import_jobs_router.get("/{job_id}", response_model=ImportJobPublic)
async def get_import_job(
    job_id: str,
    current_user: CurrentUser,
    session: Session = Depends(get_session),
) -> ImportJobPublic:
    job = _import_job_repository.get_by_id(
        session,
        job_id=job_id,
        user_id=current_user.id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")

    return import_job_to_public(job)


@import_jobs_router.get("/{job_id}/events")
async def stream_import_job_events(
    job_id: str,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    user_id = current_user.id

    async def event_stream():
        last_event_key: tuple[str, str | None, str | None, datetime | None] | None = None

        while True:
            if await request.is_disconnected():
                return

            with SessionLocal() as session:
                job = _import_job_repository.get_by_id(
                    session,
                    job_id=job_id,
                    user_id=user_id,
                )

                if job is None:
                    yield 'event: error\ndata: {"message": "Job not found"}\n\n'
                    return

                payload = json.dumps(import_job_to_public(job).model_dump())
                event_key = import_job_event_key(job)

            if event_key != last_event_key:
                yield f"event: progress\ndata: {payload}\n\n"
                last_event_key = event_key

            if job.status in {"done", "failed"}:
                return

            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
