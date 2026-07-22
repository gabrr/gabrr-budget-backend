from __future__ import annotations

from typing import Protocol

from app.agents.models import AgentProgressCallback, StatementImportResult


class AgentGateway(Protocol):
    async def extract_statement_transactions(
        self,
        pdf_bytes: bytes,
        *,
        filename: str,
        user_id: str,
        on_progress: AgentProgressCallback | None = None,
    ) -> StatementImportResult:
        ...
