from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import pool

from app.db import engine as db_engine

SUPABASE_URL = (
    "postgresql+psycopg://user:password@db.abcdefghijklmnopqrst.supabase.co:5432/postgres"
)
SUPAVISOR_URL = (
    "postgresql+psycopg://user.ref:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
)


@pytest.mark.parametrize("database_url", [SUPABASE_URL, SUPAVISOR_URL])
def test_production_supabase_explicitly_disables_automatic_prepared_statements(
    database_url: str,
) -> None:
    connect_args = db_engine.database_connect_args(database_url, app_env="production")

    assert connect_args["prepare_threshold"] is None
    assert connect_args["prepare_threshold"] != 0


def test_production_supabase_preserves_existing_connect_args() -> None:
    connect_args = db_engine.database_connect_args(
        SUPABASE_URL,
        app_env="production",
        connect_args={"application_name": "acetate", "prepare_threshold": None},
    )

    assert connect_args == {
        "application_name": "acetate",
        "prepare_threshold": None,
    }


@pytest.mark.parametrize("threshold", [0, 1, False])
def test_production_supabase_rejects_conflicting_prepare_threshold(threshold: object) -> None:
    with pytest.raises(ValueError, match="prepare_threshold must be None"):
        db_engine.database_connect_args(
            SUPAVISOR_URL,
            app_env="production",
            connect_args={"prepare_threshold": threshold},
        )


def test_non_psycopg_driver_is_unchanged() -> None:
    assert db_engine.database_connect_args(
        "sqlite+pysqlite:///:memory:",
        app_env="local",
        connect_args={"check_same_thread": False},
    ) == {"check_same_thread": False}


@pytest.mark.parametrize(
    ("database_url", "app_env"),
    [
        (SUPABASE_URL, "local"),
        ("postgresql+psycopg://user:password@localhost:5432/postgres", "production"),
    ],
)
def test_non_production_or_non_supabase_psycopg_is_unchanged(
    database_url: str,
    app_env: str,
) -> None:
    assert db_engine.database_connect_args(
        database_url,
        app_env=app_env,
        connect_args={"application_name": "local"},
    ) == {"application_name": "local"}


def test_application_engine_retains_pool_pre_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    expected_engine = object()

    def fake_create_engine(database_url: str, **options: Any) -> object:
        captured["database_url"] = database_url
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(db_engine, "create_engine", fake_create_engine)

    actual_engine = db_engine.create_database_engine(
        SUPAVISOR_URL,
        app_env="production",
        pool_pre_ping=True,
        connect_args={"application_name": "acetate"},
    )

    assert actual_engine is expected_engine
    assert captured == {
        "database_url": SUPAVISOR_URL,
        "connect_args": {
            "application_name": "acetate",
            "prepare_threshold": None,
        },
        "pool_pre_ping": True,
    }


def test_alembic_engine_uses_production_connection_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected_engine = object()

    def fake_engine_from_config(
        section: Mapping[str, Any],
        **options: Any,
    ) -> object:
        captured["section"] = section
        captured.update(options)
        return expected_engine

    monkeypatch.setattr(db_engine, "engine_from_config", fake_engine_from_config)

    actual_engine = db_engine.create_migration_engine(
        {"sqlalchemy.echo": "false", "unrelated": "preserved"},
        database_url=SUPABASE_URL,
        app_env="production",
        connect_args={"application_name": "alembic"},
    )

    assert actual_engine is expected_engine
    assert captured == {
        "section": {
            "sqlalchemy.echo": "false",
            "unrelated": "preserved",
            "sqlalchemy.url": SUPABASE_URL,
        },
        "prefix": "sqlalchemy.",
        "poolclass": pool.NullPool,
        "connect_args": {
            "application_name": "alembic",
            "prepare_threshold": None,
        },
    }
