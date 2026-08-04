from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.gateway import (
    AuthenticationUnavailableError,
    InvalidAccessTokenError,
    TokenVerifier,
)
from app.db.schemas.users import UserSchema
from app.db.session import get_session

bearer = HTTPBearer(auto_error=False)


def _token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> UserSchema:
    if request.app.state.settings.auth_mode == "local":
        local_email = request.app.state.settings.local_user_email.strip().lower()
        user = session.scalar(
            select(UserSchema).where(UserSchema.email == local_email)
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Local user {local_email} is not registered",
            )
        return user

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = await _token_verifier(request).verify(credentials.credentials)
    except InvalidAccessTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except AuthenticationUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from error

    allowed_email = request.app.state.settings.allowed_user_email.strip().lower()
    if claims.email != allowed_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not allowed")

    user = session.get(UserSchema, claims.subject)
    if user is None or (user.email or "").strip().lower() != allowed_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not registered")

    return user


CurrentUser = Annotated[UserSchema, Depends(get_current_user)]
