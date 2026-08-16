"""Local or Google Cloud Storage persistence for PDF imports."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from google.api_core.exceptions import NotFound
from google.cloud import storage

if TYPE_CHECKING:
    from app.config import Settings


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _user_upload_directory(user_id: str) -> Path:
    return _backend_root() / "data" / "uploads" / user_id


PDF_FILE_MAGIC_PREFIX = b"%PDF-"
ALLOWED_PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


class FileSystemService:
    """Persist imports on the local filesystem for development."""

    def _ensure_pdf_or_raise(
        self,
        original_filename: str,
        content_type: str | None,
        uploaded_bytes: bytes,
        *,
        accepts: Literal["pdf"],
    ) -> None:
        if accepts != "pdf":
            raise ValueError("Only accepts='pdf' is supported for now.")

        filename_lower = original_filename.lower()
        if not filename_lower.endswith(".pdf"):
            raise ValueError("Only PDF uploads are accepted (filename must end with .pdf).")

        normalized_content_type = (content_type or "").lower()
        if normalized_content_type and normalized_content_type not in ALLOWED_PDF_CONTENT_TYPES:
            raise ValueError("Only PDF uploads are accepted (unexpected Content-Type).")

        if not uploaded_bytes.startswith(PDF_FILE_MAGIC_PREFIX):
            raise ValueError("Only PDF uploads are accepted (file does not look like a PDF).")

    async def save(
        self,
        uploaded_bytes: bytes,
        *,
        original_filename: str,
        content_type: str | None,
        user_id: str,
        accepts: Literal["pdf"],
    ) -> str:
        self._ensure_pdf_or_raise(
            original_filename,
            content_type,
            uploaded_bytes,
            accepts=accepts,
        )

        user_upload_directory = _user_upload_directory(user_id)
        user_upload_directory.mkdir(parents=True, exist_ok=True)

        filename_stem = Path(original_filename or "upload").stem
        destination_path = user_upload_directory / f"{uuid.uuid4().hex}_{filename_stem}.pdf"
        destination_path.write_bytes(uploaded_bytes)

        return str(destination_path.resolve())

    async def read(self, storage_path: str) -> bytes:
        return Path(storage_path).read_bytes()

    async def delete_if_exists(self, storage_path: str) -> None:
        path = Path(storage_path)
        if path.exists() and path.is_file():
            path.unlink()


class GoogleCloudStorageService:
    """Persist imports in a private Google Cloud Storage bucket."""

    def __init__(
        self,
        bucket_name: str,
        *,
        client: storage.Client | None = None,
    ) -> None:
        self._bucket = (client or storage.Client()).bucket(bucket_name)
        self._validator = FileSystemService()

    async def save(
        self,
        uploaded_bytes: bytes,
        *,
        original_filename: str,
        content_type: str | None,
        user_id: str,
        accepts: Literal["pdf"],
    ) -> str:
        self._validator._ensure_pdf_or_raise(
            original_filename,
            content_type,
            uploaded_bytes,
            accepts=accepts,
        )

        filename_stem = Path(original_filename or "upload").stem
        object_name = f"imports/{user_id}/{uuid.uuid4().hex}_{filename_stem}.pdf"
        blob = self._bucket.blob(object_name)
        await asyncio.to_thread(
            blob.upload_from_string,
            uploaded_bytes,
            content_type="application/pdf",
        )
        return f"gs://{self._bucket.name}/{object_name}"

    async def read(self, storage_path: str) -> bytes:
        return await asyncio.to_thread(self._blob(storage_path).download_as_bytes)

    async def delete_if_exists(self, storage_path: str) -> None:
        if Path(storage_path).is_absolute():
            return

        try:
            await asyncio.to_thread(self._blob(storage_path).delete)
        except NotFound:
            return

    def _blob(self, storage_path: str):
        prefix = f"gs://{self._bucket.name}/"
        if not storage_path.startswith(prefix):
            raise ValueError("Import object is not stored in the configured bucket.")
        return self._bucket.blob(storage_path.removeprefix(prefix))


def create_file_storage_service(
    settings: Settings,
) -> FileSystemService | GoogleCloudStorageService:
    if settings.file_storage_backend == "gcs":
        return GoogleCloudStorageService(settings.gcs_bucket_name)
    return FileSystemService()
