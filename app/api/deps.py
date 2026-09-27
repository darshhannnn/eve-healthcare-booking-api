"""Shared FastAPI dependencies: authentication, admin guard, pagination."""

import jwt as pyjwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole

# auto_error=False so a missing header yields our own 401 shape.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the JWT bearer token to an active user, or 401."""
    if not token:
        raise _unauthorized()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise _unauthorized("Invalid or expired token")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User account not found or inactive")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required for this operation",
        )
    return user


def get_pagination(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int | None = Query(
        None, ge=1, le=get_settings().MAX_PAGE_SIZE, description="Items per page"
    ),
) -> tuple[int, int]:
    settings = get_settings()
    return page, page_size or settings.DEFAULT_PAGE_SIZE
