from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt

from app.auth.gateway import (
    AuthenticationUnavailableError,
    IdentityClaims,
    InvalidAccessTokenError,
)
from app.config import Settings

JwksFetcher = Callable[[str], Awaitable[dict[str, Any]]]
SUPPORTED_ALGORITHMS = {"ES256", "RS256"}


async def fetch_jwks(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AuthenticationUnavailableError(
            "Supabase signing keys are unavailable"
        ) from error

    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise AuthenticationUnavailableError("Identity provider returned invalid signing keys")

    return payload


class SupabaseTokenVerifier:
    def __init__(
        self,
        settings: Settings,
        *,
        jwks_fetcher: JwksFetcher = fetch_jwks,
        cache_seconds: float = 300.0,
    ) -> None:
        self._settings = settings
        self._jwks_fetcher = jwks_fetcher
        self._cache_seconds = cache_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> IdentityClaims:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as error:
            raise InvalidAccessTokenError("Invalid access token") from error

        key_id = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(key_id, str) or algorithm not in SUPPORTED_ALGORITHMS:
            raise InvalidAccessTokenError("Invalid access token")

        key = await self._get_key(key_id)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._settings.supabase_jwt_audience,
                issuer=self._settings.supabase_jwt_issuer,
            )
            subject = str(UUID(str(claims["sub"])))
            email = str(claims["email"]).strip().lower()
        except (JWTError, KeyError, TypeError, ValueError) as error:
            raise InvalidAccessTokenError("Invalid access token") from error

        if not email:
            raise InvalidAccessTokenError("Invalid access token")

        return IdentityClaims(subject=subject, email=email)

    async def _get_key(self, key_id: str) -> dict[str, Any]:
        now = time.monotonic()
        if now < self._expires_at:
            try:
                return self._keys[key_id]
            except KeyError as error:
                raise InvalidAccessTokenError("Invalid access token") from error

        async with self._lock:
            now = time.monotonic()
            if now < self._expires_at:
                try:
                    return self._keys[key_id]
                except KeyError as error:
                    raise InvalidAccessTokenError("Invalid access token") from error

            payload = await self._jwks_fetcher(self._settings.supabase_jwks_url)
            self._keys = {
                key["kid"]: key
                for key in payload["keys"]
                if isinstance(key, dict) and isinstance(key.get("kid"), str)
            }
            self._expires_at = time.monotonic() + self._cache_seconds

            try:
                return self._keys[key_id]
            except KeyError as error:
                raise InvalidAccessTokenError("Invalid access token") from error
