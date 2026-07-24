from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import LOCAL_CORS_ORIGINS, Settings
from app.main import create_app

DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/test"
VERCEL_ORIGIN = "https://frontend-three-jet-40.vercel.app"


def create_settings(**overrides: object) -> Settings:
    if overrides.get("app_env") == "production":
        overrides.setdefault("supabase_url", "https://project.supabase.co")
        overrides.setdefault("allowed_user_email", "gabe@example.test")
    return Settings(
        _env_file=None,
        database_url=DATABASE_URL,
        **overrides,
    )


def test_settings_use_all_local_cors_origins_by_default() -> None:
    app_settings = create_settings()

    assert app_settings.cors_origins == LOCAL_CORS_ORIGINS
    assert app_settings.parsed_cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


def test_settings_normalize_cors_origins() -> None:
    app_settings = create_settings(
        cors_origins=f" {VERCEL_ORIGIN},,http://localhost:3000,{VERCEL_ORIGIN} ",
    )

    assert app_settings.parsed_cors_origins == [
        VERCEL_ORIGIN,
        "http://localhost:3000",
    ]


def test_production_requires_explicit_non_empty_cors_origins() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS must be explicitly configured"):
        create_settings(app_env="production")

    with pytest.raises(ValidationError, match="CORS_ORIGINS must be explicitly configured"):
        create_settings(app_env="production", cors_origins=" , ")


def test_generic_agent_environment_variables_load(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "https://agent.test")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "45")

    app_settings = create_settings()

    assert app_settings.agent_base_url == "https://agent.test"
    assert app_settings.agent_timeout_seconds == 45


def test_agent_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        create_settings(agent_timeout_seconds=0)


def test_agent_auth_mode_must_be_supported() -> None:
    assert create_settings(agent_auth_mode="none").agent_auth_mode == "none"
    assert create_settings(agent_auth_mode="google").agent_auth_mode == "google"

    with pytest.raises(ValidationError):
        create_settings(agent_auth_mode="shared-secret")


def test_vercel_preflight_is_allowed() -> None:
    client = TestClient(
        create_app(
            create_settings(
                app_env="production",
                cors_origins=VERCEL_ORIGIN,
            )
        )
    )

    response = client.options(
        "/agents/process-file",
        headers={
            "Origin": VERCEL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type,Idempotency-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == VERCEL_ORIGIN
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "idempotency-key" in allowed_headers


def test_production_disables_api_documentation() -> None:
    client = TestClient(
        create_app(
            create_settings(
                app_env="production",
                cors_origins=VERCEL_ORIGIN,
            )
        )
    )

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_disallowed_origin_receives_no_cors_permission() -> None:
    client = TestClient(
        create_app(
            create_settings(
                app_env="production",
                cors_origins=VERCEL_ORIGIN,
            )
        )
    )

    response = client.options(
        "/agents/process-file",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Idempotency-Key",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_internal_task_route_requires_cloud_task_identity() -> None:
    client = TestClient(
        create_app(
            create_settings(
                app_env="production",
                cors_origins=VERCEL_ORIGIN,
                file_storage_backend="gcs",
                gcs_bucket_name="private-imports",
                cloud_tasks_mode="google",
                google_cloud_project="test-project",
                cloud_tasks_invoker_email="tasks@test-project.iam.gserviceaccount.com",
                backend_base_url="https://backend.test",
            )
        )
    )

    response = client.post("/internal/import-jobs/job_test/process")

    assert response.status_code == 401


def test_internal_task_route_is_disabled_without_cloud_tasks() -> None:
    client = TestClient(create_app(create_settings()))

    response = client.post("/internal/import-jobs/job_test/process")

    assert response.status_code == 503
