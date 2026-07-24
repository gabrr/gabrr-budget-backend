"""Agent upload routes."""

import hashlib
import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.import_jobs_routes import import_job_to_public
from app.auth import CurrentUser
from app.config import settings
from app.db.models.import_jobs import ImportJobPublic
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.session import get_session
from app.services.cloud_tasks_service import CloudTasksService
from app.services.file_storage_service import create_file_storage_service
from app.utils.files import ensure_not_empty, read_upload_bytes

agents_router = APIRouter(prefix="/agents", tags=["agents"])
_import_job_repository = ImportJobRepository()
logger = logging.getLogger(__name__)


def _sha256_bytes(uploaded_bytes: bytes) -> str:
    return hashlib.sha256(uploaded_bytes).hexdigest()


async def _fail_dispatch(
    session: Session,
    job,
    file_storage_service,
) -> None:
    _import_job_repository.mark_failed(
        session,
        job.id,
        error_message="Import could not be scheduled.",
    )
    session.commit()
    try:
        await file_storage_service.delete_if_exists(job.storage_path)
    except Exception:
        logger.warning("import_dispatch_cleanup_failed job_id=%s", job.id, exc_info=True)


@agents_router.post("/process-file", response_model=None, status_code=202)
async def agent_process_file(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ImportJobPublic | JSONResponse:
    user_id = current_user.id
    maximum_bytes = settings.max_file_upload_bytes
    uploaded_bytes = await read_upload_bytes(file, maximum_bytes, settings.max_file_upload_mb)
    ensure_not_empty(uploaded_bytes)

    file_storage_service = create_file_storage_service(settings)
    cloud_tasks_service = CloudTasksService(settings)
    file_hash = _sha256_bytes(uploaded_bytes)
    existing_job = _import_job_repository.get_by_idempotency_key(
        session,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )

    if existing_job is not None:
        if existing_job.file_hash != file_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key reused with different file content.",
            )

        logger.info(
            "import_job_reused job_id=%s idempotency_key=%s filename=%s size_bytes=%s",
            existing_job.id,
            idempotency_key,
            existing_job.original_filename,
            existing_job.size_bytes,
        )
        if existing_job.status == "pending":
            try:
                await cloud_tasks_service.enqueue_import(
                    existing_job.id,
                    attempt=existing_job.attempts,
                )
            except Exception as error:
                logger.exception("import_dispatch_failed job_id=%s", existing_job.id)
                await _fail_dispatch(session, existing_job, file_storage_service)
                raise HTTPException(
                    status_code=503,
                    detail="Import could not be scheduled.",
                ) from error

        status_code = 202 if existing_job.status in {"pending", "processing"} else 200
        return JSONResponse(
            status_code=status_code,
            content=import_job_to_public(existing_job).model_dump(mode="json"),
        )

    try:
        storage_path = await file_storage_service.save(
            uploaded_bytes,
            original_filename=file.filename or "upload.pdf",
            content_type=file.content_type,
            user_id=user_id,
            accepts="pdf",
        )

    except ValueError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error

    try:
        job = _import_job_repository.create_pending(
            session,
            user_id=user_id,
            idempotency_key=idempotency_key,
            file_hash=file_hash,
            original_filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(uploaded_bytes),
            storage_path=storage_path,
        )
        logger.info(
            "import_job_created job_id=%s filename=%s size_bytes=%s file_hash_prefix=%s",
            job.id,
            job.original_filename,
            job.size_bytes,
            file_hash[:12],
        )

    except IntegrityError as error:
        session.rollback()
        await file_storage_service.delete_if_exists(storage_path)
        if getattr(error.orig, "sqlstate", None) != "23505":
            raise HTTPException(
                status_code=422,
                detail="Upload user is not configured in the database.",
            ) from error

        existing_job = _import_job_repository.get_by_idempotency_key(
            session,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )

        if existing_job is not None and existing_job.file_hash == file_hash:
            logger.info(
                "import_job_reused job_id=%s idempotency_key=%s filename=%s size_bytes=%s",
                existing_job.id,
                idempotency_key,
                existing_job.original_filename,
                existing_job.size_bytes,
            )
            if existing_job.status == "pending":
                try:
                    await cloud_tasks_service.enqueue_import(
                        existing_job.id,
                        attempt=existing_job.attempts,
                    )
                except Exception as dispatch_error:
                    logger.exception("import_dispatch_failed job_id=%s", existing_job.id)
                    await _fail_dispatch(session, existing_job, file_storage_service)
                    raise HTTPException(
                        status_code=503,
                        detail="Import could not be scheduled.",
                    ) from dispatch_error

            status_code = 202 if existing_job.status in {"pending", "processing"} else 200
            return JSONResponse(
                status_code=status_code,
                content=import_job_to_public(existing_job).model_dump(mode="json"),
            )

        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key reused with different file content.",
        ) from error

    except Exception:
        await file_storage_service.delete_if_exists(storage_path)
        raise

    session.commit()
    try:
        await cloud_tasks_service.enqueue_import(job.id, attempt=job.attempts)
    except Exception as error:
        logger.exception("import_dispatch_failed job_id=%s", job.id)
        await _fail_dispatch(session, job, file_storage_service)
        raise HTTPException(
            status_code=503,
            detail="Import could not be scheduled.",
        ) from error

    return JSONResponse(
        status_code=202,
        content=import_job_to_public(job).model_dump(mode="json"),
    )
