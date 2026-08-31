from __future__ import annotations

import asyncio
from unittest.mock import Mock

from app.config import Settings
from app.services import file_storage_service
from app.services.file_storage_service import GoogleCloudStorageService


def test_factory_passes_exact_retired_bucket_allowlist(monkeypatch) -> None:
    client = Mock()
    bucket = Mock()
    bucket.name = "current-import-bucket"
    client.bucket.return_value = bucket
    monkeypatch.setattr(file_storage_service.storage, "Client", lambda: client)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        file_storage_backend="gcs",
        gcs_bucket_name="current-import-bucket",
        gcs_retired_bucket_names="retired-import-bucket",
    )

    service = file_storage_service.create_file_storage_service(settings)

    assert isinstance(service, GoogleCloudStorageService)
    asyncio.run(
        service.delete_if_exists(
            "gs://retired-import-bucket/imports/gabe/already-missing.pdf"
        )
    )
    bucket.blob.assert_not_called()
