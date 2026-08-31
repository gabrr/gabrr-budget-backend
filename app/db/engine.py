from collections.abc import Mapping
from typing import Any

from sqlalchemy import create_engine, engine_from_config, pool
from sqlalchemy.engine import Engine, make_url


def _is_supabase_psycopg_url(database_url: str) -> bool:
    url = make_url(database_url)
    host = (url.host or "").lower()
    return url.drivername == "postgresql+psycopg" and (
        host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com")
    )


def database_connect_args(
    database_url: str,
    *,
    app_env: str,
    connect_args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return connection arguments hardened for the configured DBAPI driver."""
    resolved = dict(connect_args or {})
    if app_env != "production" or not _is_supabase_psycopg_url(database_url):
        return resolved

    existing_threshold = resolved.get("prepare_threshold")
    if "prepare_threshold" in resolved and existing_threshold is not None:
        raise ValueError("psycopg prepare_threshold must be None")

    resolved["prepare_threshold"] = None
    return resolved


def create_database_engine(
    database_url: str,
    *,
    app_env: str,
    connect_args: Mapping[str, Any] | None = None,
    **engine_options: Any,
) -> Engine:
    """Create the application engine without psycopg named prepared statements."""
    return create_engine(
        database_url,
        connect_args=database_connect_args(
            database_url,
            app_env=app_env,
            connect_args=connect_args,
        ),
        **engine_options,
    )


def create_migration_engine(
    section: Mapping[str, Any],
    *,
    database_url: str,
    app_env: str,
    connect_args: Mapping[str, Any] | None = None,
) -> Engine:
    """Create the Alembic engine with the same production connection policy."""
    return engine_from_config(
        {**section, "sqlalchemy.url": database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=database_connect_args(
            database_url,
            app_env=app_env,
            connect_args=connect_args,
        ),
    )
