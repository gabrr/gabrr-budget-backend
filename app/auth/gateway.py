from dataclasses import dataclass
from typing import Protocol


class InvalidAccessTokenError(ValueError):
    pass


class AuthenticationUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class IdentityClaims:
    subject: str
    email: str


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> IdentityClaims: ...
