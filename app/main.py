"""FastAPI application for Gabrr Budget transaction parsing."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.auth.supabase import SupabaseTokenVerifier
from app.config import Settings, settings
from app.logging_config import configure_logging

configure_logging()


def create_app(app_settings: Settings | None = None) -> FastAPI:
    resolved_settings = app_settings or settings
    app = FastAPI(
        title="Gabrr Budget API",
        description="Parse financial documents (CSV/PDF) into normalized transactions",
        version="0.1.0",
        docs_url=None if resolved_settings.app_env == "production" else "/docs",
        redoc_url=None if resolved_settings.app_env == "production" else "/redoc",
        openapi_url=None if resolved_settings.app_env == "production" else "/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.token_verifier = SupabaseTokenVerifier(resolved_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)

    return app


app = create_app()
