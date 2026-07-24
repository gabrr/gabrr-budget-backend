"""Private Google Cloud Tasks routes."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from app.workers.import_worker.main import process_job

internal_tasks_router = APIRouter(prefix="/internal", include_in_schema=False)


async def require_cloud_task(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    settings = request.app.state.settings
    if settings.cloud_tasks_mode != "google":
        raise HTTPException(status_code=503, detail="Cloud Tasks is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing task identity token.")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = await asyncio.to_thread(
            id_token.verify_oauth2_token,
            token,
            GoogleAuthRequest(),
            settings.backend_base_url.rstrip("/"),
        )
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid task identity token.") from error
    except GoogleAuthError as error:
        raise HTTPException(status_code=503, detail="Task identity could not be verified.") from error

    if (
        claims.get("email") != settings.cloud_tasks_invoker_email
        or claims.get("email_verified") is not True
    ):
        raise HTTPException(status_code=403, detail="Task identity is not allowed.")


@internal_tasks_router.post("/import-jobs/{job_id}/process", status_code=204)
async def process_queued_import(
    job_id: str,
    request: Request,
    _: None = Depends(require_cloud_task),
    task_retry_count: int = Header(default=0, alias="X-CloudTasks-TaskRetryCount"),
) -> Response:
    settings = request.app.state.settings
    outcome = await process_job(
        job_id,
        worker_id=f"cloud-task-{uuid.uuid4().hex[:12]}",
        final_attempt=task_retry_count >= settings.cloud_tasks_max_attempts - 1,
    )
    if outcome == "retry":
        raise HTTPException(status_code=503, detail="Temporary processing failure.")
    return Response(status_code=204)
