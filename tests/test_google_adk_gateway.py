from __future__ import annotations

import asyncio
import json

import httpx

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
                    prompt="prompt",
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


def test_google_adk_mapper_does_not_expose_local_file_path() -> None:
    event = {
        "content": {
            "parts": [
                {
                    "function_call": {
                        "name": "convert_statement_document_to_markdown",
                        "args": {"file_path": "/Users/gabe/private.pdf"},
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
    assert "/Users/gabe/private.pdf" not in progress.message


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
                                        "args": {"file_path": "/tmp/secret.pdf"},
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
            "/tmp/secret.pdf",
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
