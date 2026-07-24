"""Google Cloud Tasks dispatch for asynchronous PDF imports."""

from __future__ import annotations

import json
import logging

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from app.config import Settings

logger = logging.getLogger(__name__)


class CloudTasksService:
    def __init__(
        self,
        settings: Settings,
        *,
        client: tasks_v2.CloudTasksAsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def enqueue_import(self, job_id: str, *, attempt: int = 0) -> None:
        if self._settings.cloud_tasks_mode == "none":
            logger.info("import_dispatch_local_worker job_id=%s", job_id)
            return

        client = self._client or tasks_v2.CloudTasksAsyncClient()
        queue_path = client.queue_path(
            self._settings.google_cloud_project,
            self._settings.cloud_tasks_location,
            self._settings.cloud_tasks_queue,
        )
        task_name = client.task_path(
            self._settings.google_cloud_project,
            self._settings.cloud_tasks_location,
            self._settings.cloud_tasks_queue,
            f"import-{job_id}-{attempt}",
        )
        backend_url = self._settings.backend_base_url.rstrip("/")
        task = tasks_v2.Task(
            name=task_name,
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{backend_url}/internal/import-jobs/{job_id}/process",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"version": 1, "job_id": job_id}).encode(),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._settings.cloud_tasks_invoker_email,
                    audience=backend_url,
                ),
            ),
        )

        try:
            await client.create_task(parent=queue_path, task=task)
        except AlreadyExists:
            logger.info("import_task_already_exists job_id=%s", job_id)
            return

        logger.info("import_task_created job_id=%s", job_id)
