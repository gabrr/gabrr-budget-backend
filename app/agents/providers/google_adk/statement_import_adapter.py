from __future__ import annotations

import logging

import httpx

from app.agents.auth import AgentTokenProvider, NoAuthAgentTokenProvider
from app.agents.models import (
    AgentProgressCallback,
    AgentProgressEvent,
    StatementImportResult,
    agent_error_result,
    agent_success_result,
)
from app.agents.providers.google_adk.client import GoogleAdkClient
from app.agents.providers.google_adk.event_mapper import map_google_adk_event_to_progress
from app.agents.providers.google_adk.response_parser import (
    google_adk_text_from_event,
    parse_last_json_object,
)

logger = logging.getLogger(__name__)


class GoogleAdkAgentGateway:
    def __init__(
        self,
        *,
        base_url: str,
        app_name: str,
        timeout_seconds: float,
        token_provider: AgentTokenProvider | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._app_name = app_name
        self._timeout_seconds = timeout_seconds
        self._token_provider = token_provider or NoAuthAgentTokenProvider()

    async def extract_statement_transactions(
        self,
        pdf_bytes: bytes,
        *,
        filename: str,
        user_id: str,
        on_progress: AgentProgressCallback | None = None,
    ) -> StatementImportResult:
        prompt = "Process the attached financial statement PDF."
        timeout = httpx.Timeout(self._timeout_seconds)
        emitted_progress_codes: set[str] = set()

        async def emit_progress(event: AgentProgressEvent) -> None:
            if on_progress is None or event.code in emitted_progress_codes:
                return
            emitted_progress_codes.add(event.code)
            await on_progress(event)

        try:
            token = await self._token_provider.get_token(self._base_url)
            headers = {"Authorization": f"Bearer {token}"} if token else {}

            async with httpx.AsyncClient(timeout=timeout, headers=headers) as http_client:
                client = GoogleAdkClient(
                    http_client,
                    base_url=self._base_url,
                    app_name=self._app_name,
                )
                session_id = await client.create_session(user_id=user_id)
                text_parts: list[str] = []
                try:
                    await emit_progress(
                        AgentProgressEvent(
                            code="statement_ingestion.started",
                            message="Starting statement ingestion",
                        )
                    )

                    async for event in client.run_sse(
                        user_id=user_id,
                        session_id=session_id,
                        prompt=prompt,
                        pdf_bytes=pdf_bytes,
                        filename=filename,
                    ):
                        progress = map_google_adk_event_to_progress(event)
                        if progress is not None:
                            await emit_progress(progress)

                        text = google_adk_text_from_event(event)
                        if text:
                            text_parts.append(text)
                finally:
                    try:
                        await client.delete_session(user_id=user_id, session_id=session_id)
                    except httpx.HTTPError as cleanup_error:
                        logger.warning("Google ADK session cleanup failed: %s", cleanup_error)

        except httpx.HTTPError:
            logger.exception("Google ADK transport failure")
            raise

        parsed = parse_last_json_object("".join(text_parts))
        if parsed is None:
            logger.warning("Google ADK returned invalid or non-object JSON")
            return agent_error_result()

        return agent_success_result(parsed)
