from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.agents.providers.google_adk.response_parser import (
    final_text_from_google_adk_events,
    google_adk_event_from_sse_line,
)


class GoogleAdkClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        app_name: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._app_name = app_name

    async def create_session(self, *, user_id: str, session_id: str | None = None) -> str:
        url = f"{self._base_url}/apps/{self._app_name}/users/{user_id}/sessions"
        payload: dict[str, Any] = {} if session_id is None else {"session_id": session_id}
        response = await self._client.post(url, json=payload)
        response.raise_for_status()

        adk_session_id = response.json().get("id")
        if not isinstance(adk_session_id, str) or not adk_session_id:
            raise ValueError("Google ADK create_session response missing string id")

        return adk_session_id

    async def delete_session(self, *, user_id: str, session_id: str) -> None:
        response = await self._client.delete(
            f"{self._base_url}/apps/{self._app_name}/users/{user_id}/sessions/{session_id}"
        )
        response.raise_for_status()

    def _run_payload(
        self,
        *,
        user_id: str,
        session_id: str,
        prompt: str,
        pdf_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if pdf_bytes is not None:
            parts.append(
                {
                    "inlineData": {
                        "displayName": filename or "statement.pdf",
                        "mimeType": "application/pdf",
                        "data": base64.b64encode(pdf_bytes).decode("ascii"),
                    }
                }
            )

        return {
            "appName": self._app_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": {"role": "user", "parts": parts},
        }

    async def run(self, *, user_id: str, session_id: str, prompt: str) -> str:
        response = await self._client.post(
            f"{self._base_url}/run",
            json=self._run_payload(user_id=user_id, session_id=session_id, prompt=prompt),
        )
        response.raise_for_status()

        events = response.json()
        if not isinstance(events, list):
            return ""

        return final_text_from_google_adk_events(events)

    async def run_sse(
        self,
        *,
        user_id: str,
        session_id: str,
        prompt: str,
        pdf_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            **self._run_payload(
                user_id=user_id,
                session_id=session_id,
                prompt=prompt,
                pdf_bytes=pdf_bytes,
                filename=filename,
            ),
            "streaming": True,
        }

        async with self._client.stream("POST", f"{self._base_url}/run_sse", json=payload) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                event = google_adk_event_from_sse_line(line)
                if event is not None:
                    yield event
