from __future__ import annotations

from app.agents.gateway import AgentGateway
from app.agents.providers.google_adk.statement_import_adapter import GoogleAdkAgentGateway
from app.config import settings


def create_agent_gateway() -> AgentGateway:
    return GoogleAdkAgentGateway(
        base_url=settings.agent_base_url,
        app_name=settings.adk_app_name,
        timeout_seconds=settings.agent_timeout_seconds,
    )
