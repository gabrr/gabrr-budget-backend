from __future__ import annotations

import asyncio
from typing import Protocol

from google.auth.transport.requests import Request
from google.oauth2 import id_token


class AgentTokenProvider(Protocol):
    async def get_token(self, audience: str) -> str | None: ...


class NoAuthAgentTokenProvider:
    async def get_token(self, audience: str) -> None:
        return None


class GoogleAgentTokenProvider:
    async def get_token(self, audience: str) -> str:
        return await asyncio.to_thread(
            id_token.fetch_id_token,
            Request(),
            audience,
        )
