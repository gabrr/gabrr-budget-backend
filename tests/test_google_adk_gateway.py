from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from app.agents.models import AgentProgressEvent
from app.agents.providers.google_adk.client import GoogleAdkClient
from app.agents.providers.google_adk.event_mapper import map_google_adk_event_to_progress
from app.agents.providers.google_adk.statement_import_adapter import GoogleAdkAgentGateway


def _sse_event(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _text_event(text: str) -> dict:
    return {"content": {"parts": [{"text": text}]}}


def test_google_adk_client_run_sse_yields_raw_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/run_sse"
        payload = json.loads(request.content)
        assert payload["appName"] == "app"
        assert payload["userId"] == "user"
        assert payload["sessionId"] == "session"
        assert payload["newMessage"]["parts"] == [
            {"text": "Process the attached PDF."},
            {
                "inlineData": {
                    "displayName": "statement.pdf",
                    "mimeType": "application/pdf",
                    "data": base64.b64encode(b"%PDF-1.4\n%%EOF").decode("ascii"),
                }
            },
        ]
        body = (
            ": heartbeat\n\n"
            + _sse_event({"content": {"parts": [{"function_call": {"name": "noop"}}]}})
            + _sse_event(_text_event('{"transactions": []}'))
        )
        return httpx.Response(200, content=body)

    async def run_test() -> list[dict]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://agent.test",
        ) as client:
            adk_client = GoogleAdkClient(
                client,
                base_url="http://agent.test",
                app_name="app",
            )
            return [
                event
                async for event in adk_client.run_sse(
                    user_id="user",
                    session_id="session",
                    prompt="Process the attached PDF.",
                    pdf_bytes=b"%PDF-1.4\n%%EOF",
                    filename="statement.pdf",
                )
            ]

    events = asyncio.run(run_test())

    assert events == [
        {"content": {"parts": [{"function_call": {"name": "noop"}}]}},
        _text_event('{"transactions": []}'),
    ]


def test_google_adk_mapper_skips_chunk_calls_until_count_is_known() -> None:
    event = {
        "content": {
            "parts": [
                {
                    "function_call": {
                        "name": "get_markdown_chunk",
                        "args": {"index": 0},
                    }
                }
            ]
        }
    }

    assert map_google_adk_event_to_progress(event) is None


def test_google_adk_mapper_maps_chunk_response_with_count() -> None:
    event = {
        "content": {
            "parts": [
                {
                    "function_response": {
                        "name": "get_markdown_chunk",
                        "response": {
                            "status": "success",
                            "chunk": "PRIVATE MARKDOWN",
                            "index": 0,
                            "chunk_count": 2,
                        },
                    }
                }
            ]
        }
    }

    progress = map_google_adk_event_to_progress(event)

    assert progress == AgentProgressEvent(
        code="statement.chunk_read",
        message="Reading statement chunk 1 of 2",
    )
    assert "PRIVATE MARKDOWN" not in progress.message


def test_google_adk_converter_event_has_no_file_path_argument() -> None:
    event = {
        "content": {
            "parts": [
                {
                    "function_call": {
                        "name": "convert_statement_document_to_markdown",
                        "args": {},
                    }
                }
            ]
        }
    }

    progress = map_google_adk_event_to_progress(event)

    assert progress == AgentProgressEvent(
        code="pdf.converting",
        message="Converting PDF to Markdown",
    )


def test_google_adk_mapper_does_not_expose_transaction_json() -> None:
    event = _text_event('{"transactions": [{"description": "Secret"}]}')

    progress = map_google_adk_event_to_progress(event)

    assert progress == AgentProgressEvent(
        code="transactions.generating_json",
        message="Generating transaction JSON",
    )
    assert "Secret" not in progress.message


def test_google_adk_gateway_emits_progress_and_parses_streamed_json(
    monkeypatch,
) -> None:
    progress_events: list[AgentProgressEvent] = []

    async def on_progress(event: AgentProgressEvent) -> None:
        progress_events.append(event)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apps/app/users/user/sessions":
            return httpx.Response(200, json={"id": "session"})

        if request.url.path == "/run_sse":
            payload = json.loads(request.content)
            parts = payload["newMessage"]["parts"]
            assert parts[0] == {"text": "Process the attached financial statement PDF."}
            assert base64.b64decode(parts[1]["inlineData"]["data"]) == b"%PDF-test"
            assert parts[1]["inlineData"]["displayName"] == "statement.pdf"
            body = (
                _sse_event(
                    {
                        "content": {
                            "parts": [
                                {
                                    "function_call": {
                                        "name": "transfer_to_agent",
                                        "args": {"agent_name": "statement_ingestion"},
                                    }
                                }
                            ]
                        }
                    }
                )
                + _sse_event(
                    {
                        "content": {
                            "parts": [
                                {
                                    "function_call": {
                                        "name": "convert_statement_document_to_markdown",
                                        "args": {},
                                    }
                                }
                            ]
                        }
                    }
                )
                + _sse_event(
                    {
                        "content": {
                            "parts": [
                                {
                                    "function_response": {
                                        "name": "convert_statement_document_to_markdown",
                                        "response": {"status": "success", "byte_length": 120},
                                    }
                                }
                            ]
                        }
                    }
                )
                + _sse_event(_text_event('{"transactions": []}'))
            )
            return httpx.Response(200, content=body)

        if request.url.path == "/apps/app/users/user/sessions/session":
            assert request.method == "DELETE"
            return httpx.Response(204)

        return httpx.Response(404)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(
                transport=httpx.MockTransport(handler),
                base_url="http://agent.test",
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    async def run_test():
        gateway = GoogleAdkAgentGateway(
            base_url="http://agent.test",
            app_name="app",
            timeout_seconds=1,
        )
        return await gateway.extract_statement_transactions(
            b"%PDF-test",
            filename="statement.pdf",
            user_id="user",
            on_progress=on_progress,
        )

    result = asyncio.run(run_test())

    assert result.status == "success"
    assert result.data == {"transactions": []}
    assert progress_events == [
        AgentProgressEvent(
            code="statement_ingestion.started",
            message="Starting statement ingestion",
        ),
        AgentProgressEvent(code="pdf.converting", message="Converting PDF to Markdown"),
        AgentProgressEvent(code="pdf.converted", message="PDF converted to Markdown"),
        AgentProgressEvent(
            code="transactions.generating_json",
            message="Generating transaction JSON",
        ),
    ]


def test_google_adk_gateway_authenticates_all_requests_with_one_token(monkeypatch) -> None:
    authorization_headers: list[str | None] = []

    class RecordingTokenProvider:
        def __init__(self) -> None:
            self.audiences: list[str] = []

        async def get_token(self, audience: str) -> str:
            self.audiences.append(audience)
            return "signed-token"

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers.get("Authorization"))
        if request.url.path == "/apps/app/users/user/sessions":
            return httpx.Response(200, json={"id": "session"})
        if request.url.path == "/run_sse":
            return httpx.Response(200, content=_sse_event(_text_event('{"transactions": []}')))
        if request.url.path == "/apps/app/users/user/sessions/session":
            assert request.method == "DELETE"
            return httpx.Response(204)
        return httpx.Response(404)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(
                transport=httpx.MockTransport(handler),
                base_url="https://agent.test",
                headers=kwargs.get("headers"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    token_provider = RecordingTokenProvider()

    async def run_test():
        gateway = GoogleAdkAgentGateway(
            base_url="https://agent.test/",
            app_name="app",
            timeout_seconds=1,
            token_provider=token_provider,
        )
        return await gateway.extract_statement_transactions(
            b"%PDF-test",
            filename="statement.pdf",
            user_id="user",
        )

    result = asyncio.run(run_test())

    assert result.status == "success"
    assert token_provider.audiences == ["https://agent.test"]
    assert authorization_headers == [
        "Bearer signed-token",
        "Bearer signed-token",
        "Bearer signed-token",
    ]


def test_google_adk_gateway_does_not_send_request_when_token_fetch_fails(
    monkeypatch,
) -> None:
    request_count = 0

    class FailingTokenProvider:
        async def get_token(self, audience: str) -> str:
            raise RuntimeError("credentials unavailable")

    class UnexpectedAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal request_count
            request_count += 1

    monkeypatch.setattr(httpx, "AsyncClient", UnexpectedAsyncClient)

    gateway = GoogleAdkAgentGateway(
        base_url="https://agent.test",
        app_name="app",
        timeout_seconds=1,
        token_provider=FailingTokenProvider(),
    )

    with pytest.raises(RuntimeError, match="credentials unavailable"):
        asyncio.run(
            gateway.extract_statement_transactions(
                b"%PDF-test",
                filename="statement.pdf",
                user_id="user",
            )
        )

    assert request_count == 0
