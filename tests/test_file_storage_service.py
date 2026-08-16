from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from app.services.file_storage_service import GoogleCloudStorageService


def google_cloud_storage_service() -> tuple[GoogleCloudStorageService, Mock]:
    client = Mock()
    bucket = Mock()
    bucket.name = "current-import-bucket"
    client.bucket.return_value = bucket

    return GoogleCloudStorageService(bucket.name, client=client), bucket


def test_gcs_delete_treats_legacy_absolute_local_path_as_missing() -> None:
    service, bucket = google_cloud_storage_service()

    asyncio.run(service.delete_if_exists("/app/data/uploads/user/statement.pdf"))

    bucket.blob.assert_not_called()


def test_gcs_delete_rejects_object_from_another_bucket() -> None:
    service, bucket = google_cloud_storage_service()

    with pytest.raises(ValueError, match="not stored in the configured bucket"):
        asyncio.run(
            service.delete_if_exists("gs://previous-import-bucket/imports/user/statement.pdf")
        )

    bucket.blob.assert_not_called()
