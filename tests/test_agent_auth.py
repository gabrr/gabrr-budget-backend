from __future__ import annotations

import asyncio

from app.agents import auth
from app.agents.auth import GoogleAgentTokenProvider, NoAuthAgentTokenProvider


def test_no_auth_provider_returns_no_token() -> None:
    token = asyncio.run(NoAuthAgentTokenProvider().get_token("http://agent.test"))

    assert token is None


def test_google_provider_fetches_token_for_audience(monkeypatch) -> None:
    captured_audiences: list[str] = []

    def fetch_id_token(request: object, audience: str) -> str:
        captured_audiences.append(audience)
        return "signed-token"

    monkeypatch.setattr(auth.id_token, "fetch_id_token", fetch_id_token)

    token = asyncio.run(GoogleAgentTokenProvider().get_token("https://agent.test"))

    assert token == "signed-token"
    assert captured_audiences == ["https://agent.test"]
