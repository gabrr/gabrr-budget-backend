from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import NotFound
from pydantic import ValidationError

from app.config import Settings
from app.services.file_storage_service import GoogleCloudStorageService

DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/test"
CURRENT_BUCKET = "gen-lang-client-0570264410-acetate-imports"
RETIRED_BUCKET = "gen-lang-client-0570264410-gabrr-imports"
RETIRED_PATH = f"gs://{RETIRED_BUCKET}/imports/gabe/legacy.pdf"


def create_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url=DATABASE_URL, **overrides)


def storage_service() -> tuple[GoogleCloudStorageService, Mock]:
    client = Mock()
    bucket = Mock()
    bucket.name = CURRENT_BUCKET
    client.bucket.return_value = bucket
    service = GoogleCloudStorageService(
        CURRENT_BUCKET,
        retired_bucket_names=frozenset({RETIRED_BUCKET}),
        client=client,
    )
    return service, bucket


def test_retired_bucket_settings_default_to_empty_and_normalize_exact_names() -> None:
    assert create_settings().parsed_gcs_retired_bucket_names == frozenset()
    configured = create_settings(
        gcs_retired_bucket_names=f" {RETIRED_BUCKET},,archive-bucket,{RETIRED_BUCKET} "
    )
    assert configured.parsed_gcs_retired_bucket_names == frozenset(
        {RETIRED_BUCKET, "archive-bucket"}
    )


@pytest.mark.parametrize(
    "invalid_value",
    [
        f"gs://{RETIRED_BUCKET}",
        f"{RETIRED_BUCKET}/imports",
        "gabrr-*",
        "UPPERCASE-BUCKET",
        "ab",
    ],
)
def test_retired_bucket_settings_reject_non_exact_names(invalid_value: str) -> None:
    with pytest.raises(ValidationError, match="must contain bare exact GCS bucket names"):
        create_settings(gcs_retired_bucket_names=invalid_value)


def test_retired_bucket_settings_reject_current_bucket() -> None:
    with pytest.raises(ValidationError, match="Current GCS bucket cannot be marked as retired"):
        create_settings(
            file_storage_backend="gcs",
            gcs_bucket_name=CURRENT_BUCKET,
            gcs_retired_bucket_names=CURRENT_BUCKET,
        )


def test_exact_retired_bucket_delete_is_no_op_without_gcs_access() -> None:
    service, bucket = storage_service()
    asyncio.run(service.delete_if_exists(RETIRED_PATH))
    bucket.blob.assert_not_called()


@pytest.mark.parametrize(
    "foreign_path",
    [
        "gs://unknown-bucket/imports/gabe/legacy.pdf",
        f"gs://{RETIRED_BUCKET}-copy/imports/gabe/legacy.pdf",
        f"gs://prefix-{RETIRED_BUCKET}/imports/gabe/legacy.pdf",
    ],
)
def test_unknown_and_lookalike_deletes_fail_closed(foreign_path: str) -> None:
    service, bucket = storage_service()
    with pytest.raises(ValueError, match="not stored in the configured bucket"):
        asyncio.run(service.delete_if_exists(foreign_path))
    bucket.blob.assert_not_called()


@pytest.mark.parametrize(
    "malformed_path",
    ["legacy.pdf", "s3://legacy/imports/file.pdf", "gs://", f"gs://{RETIRED_BUCKET}"],
)
def test_malformed_paths_fail_closed(malformed_path: str) -> None:
    service, bucket = storage_service()
    with pytest.raises(ValueError, match="not stored in an allowed bucket"):
        asyncio.run(service.delete_if_exists(malformed_path))
    bucket.blob.assert_not_called()


def test_current_bucket_delete_is_unchanged() -> None:
    service, bucket = storage_service()
    asyncio.run(service.delete_if_exists(f"gs://{CURRENT_BUCKET}/imports/gabe/current.pdf"))
    bucket.blob.assert_called_once_with("imports/gabe/current.pdf")
    bucket.blob.return_value.delete.assert_called_once_with()


def test_current_bucket_missing_delete_remains_idempotent() -> None:
    service, bucket = storage_service()
    bucket.blob.return_value.delete.side_effect = NotFound("missing")
    asyncio.run(service.delete_if_exists(f"gs://{CURRENT_BUCKET}/imports/gabe/missing.pdf"))
    bucket.blob.return_value.delete.assert_called_once_with()


def test_retired_bucket_read_remains_rejected() -> None:
    service, bucket = storage_service()
    with pytest.raises(ValueError, match="not stored in the configured bucket"):
        asyncio.run(service.read(RETIRED_PATH))
    bucket.blob.assert_not_called()


def test_current_bucket_save_and_read_are_unchanged() -> None:
    service, bucket = storage_service()
    saved_path = asyncio.run(
        service.save(
            b"%PDF-current",
            original_filename="statement.pdf",
            content_type="application/pdf",
            user_id="gabe",
            accepts="pdf",
        )
    )
    asyncio.run(service.read(f"gs://{CURRENT_BUCKET}/imports/gabe/current.pdf"))
    assert saved_path.startswith(f"gs://{CURRENT_BUCKET}/imports/gabe/")
    bucket.blob.return_value.upload_from_string.assert_called_once()
    bucket.blob.assert_any_call("imports/gabe/current.pdf")
    bucket.blob.return_value.download_as_bytes.assert_called_once_with()
