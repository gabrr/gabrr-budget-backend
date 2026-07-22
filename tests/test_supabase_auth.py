from __future__ import annotations

import asyncio
import base64
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.gateway import AuthenticationUnavailableError, InvalidAccessTokenError
from app.auth.supabase import SupabaseTokenVerifier
from app.config import Settings
from app.db.schemas import Base
from app.db.schemas.users import UserSchema
from app.db.session import get_session
from app.main import create_app

USER_ID = "7ca7599a-0ba6-4f2b-b9dd-4e9bbb3a7e80"
UNKNOWN_USER_ID = "2f360265-b130-4d15-8339-308b18c179f2"
ALLOWED_EMAIL = "g.webdevelopr@gmail.com"
SUPABASE_URL = "https://project.supabase.co"
KEY_ID = "test-key"


def _base64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def signing_material() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "kty": "RSA",
        "kid": KEY_ID,
        "use": "sig",
        "alg": "RS256",
        "n": _base64url(numbers.n),
        "e": _base64url(numbers.e),
    }
    return private_key, public_jwk


@pytest.fixture()
def auth_client(
    signing_material: tuple[Any, dict[str, Any]],
) -> Generator[tuple[TestClient, Any], None, None]:
    private_key, public_jwk = signing_material
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        session.add(UserSchema(id=USER_ID, email=ALLOWED_EMAIL, display_name="Gabriel Welzel"))
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        with SessionLocal() as session:
            yield session

    async def fetch_test_jwks(url: str) -> dict[str, Any]:
        assert url == f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        return {"keys": [public_jwk]}

    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite://",
        supabase_url=SUPABASE_URL,
        allowed_user_email=ALLOWED_EMAIL,
    )
    app = create_app(settings)
    app.dependency_overrides[get_session] = override_get_session
    app.state.token_verifier = SupabaseTokenVerifier(
        settings,
        jwks_fetcher=fetch_test_jwks,
    )

    try:
        yield TestClient(app), private_key
    finally:
        app.dependency_overrides.clear()


def _token(
    private_key: Any,
    *,
    subject: str = USER_ID,
    email: str = ALLOWED_EMAIL,
    expires_at: datetime | None = None,
    issuer: str = f"{SUPABASE_URL}/auth/v1",
    key_id: str = KEY_ID,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": email,
            "aud": "authenticated",
            "iss": issuer,
            "iat": int(now.timestamp()),
            "exp": int((expires_at or now + timedelta(minutes=5)).timestamp()),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def test_business_route_requires_authentication(
    auth_client: tuple[TestClient, Any],
) -> None:
    client, _ = auth_client

    response = client.get("/transactions")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_supabase_token_resolves_application_user(
    auth_client: tuple[TestClient, Any],
) -> None:
    client, private_key = auth_client

    response = client.get(
        "/transactions",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "token_overrides",
    [
        {"expires_at": datetime.now(UTC) - timedelta(minutes=1)},
        {"issuer": "https://untrusted.example/auth/v1"},
    ],
)
def test_invalid_supabase_claims_are_rejected(
    auth_client: tuple[TestClient, Any],
    token_overrides: dict[str, Any],
) -> None:
    client, private_key = auth_client

    response = client.get(
        "/transactions",
        headers={"Authorization": f"Bearer {_token(private_key, **token_overrides)}"},
    )

    assert response.status_code == 401


def test_valid_but_disallowed_email_is_forbidden(
    auth_client: tuple[TestClient, Any],
) -> None:
    client, private_key = auth_client

    response = client.get(
        "/transactions",
        headers={
            "Authorization": f"Bearer {_token(private_key, email='other@example.test')}"
        },
    )

    assert response.status_code == 403


def test_valid_but_unregistered_user_is_forbidden(
    auth_client: tuple[TestClient, Any],
) -> None:
    client, private_key = auth_client

    response = client.get(
        "/transactions",
        headers={"Authorization": f"Bearer {_token(private_key, subject=UNKNOWN_USER_ID)}"},
    )

    assert response.status_code == 403


def test_signing_key_outage_returns_service_unavailable(
    auth_client: tuple[TestClient, Any],
) -> None:
    client, private_key = auth_client

    async def unavailable_jwks(url: str) -> dict[str, Any]:
        raise AuthenticationUnavailableError("unavailable")

    client.app.state.token_verifier = SupabaseTokenVerifier(
        client.app.state.settings,
        jwks_fetcher=unavailable_jwks,
    )
    response = client.get(
        "/transactions",
        headers={"Authorization": f"Bearer {_token(private_key)}"},
    )

    assert response.status_code == 503


def test_unknown_key_id_does_not_bypass_fresh_jwks_cache(
    signing_material: tuple[Any, dict[str, Any]],
) -> None:
    private_key, public_jwk = signing_material
    fetch_count = 0

    async def counted_fetch(_url: str) -> dict[str, Any]:
        nonlocal fetch_count
        fetch_count += 1
        return {"keys": [public_jwk]}

    verifier = SupabaseTokenVerifier(
        Settings(
            _env_file=None,
            database_url="sqlite+pysqlite://",
            supabase_url=SUPABASE_URL,
        ),
        jwks_fetcher=counted_fetch,
    )

    asyncio.run(verifier.verify(_token(private_key)))
    with pytest.raises(InvalidAccessTokenError, match="Invalid access token"):
        asyncio.run(verifier.verify(_token(private_key, key_id="attacker-key")))

    assert fetch_count == 1
