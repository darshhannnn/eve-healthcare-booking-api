"""Authentication: signup, login (JSON *and* OAuth2 form), current user."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import ConflictError, UnprocessableError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import SignupRequest, UserOut
from app.utils.rate_limit import rate_limit

router = APIRouter()


@router.post(
    "/auth/signup",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    dependencies=[Depends(rate_limit("auth"))],
)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> User:
    email = payload.email.lower()
    existing = db.scalar(select(func.count()).select_from(User).where(User.email == email))
    if existing:
        raise ConflictError("This email is already registered")

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # concurrent duplicate signup
        db.rollback()
        raise ConflictError("This email is already registered")
    db.refresh(user)
    return user


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Log in and receive a JWT access token (JSON body or OAuth2 form)",
    dependencies=[Depends(rate_limit("auth"))],
)
async def login(request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Accepts either:

    * ``application/json`` — ``{"email": "...", "password": "..."}``
    * ``application/x-www-form-urlencoded`` — ``username``/``password``
      (the OAuth2 password flow, so Swagger UI's Authorize button works).
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = LoginRequest.model_validate(await request.json())
        except (json.JSONDecodeError, ValidationError, TypeError):
            raise UnprocessableError(
                'Expected a JSON body like {"email": "...", "password": "..."}'
            )
        email, password = data.email.lower(), data.password
    else:
        form = await request.form()
        username = form.get("username") or form.get("email")
        raw_password = form.get("password")
        if not username or raw_password is None:
            raise UnprocessableError(
                "Send JSON {email, password} or OAuth2 form fields (username, password)"
            )
        email, password = str(username).lower(), str(raw_password)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.hashed_password):
        # Deliberately vague: do not reveal whether the account exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled"
        )

    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/auth/me", response_model=UserOut, summary="Profile of the authenticated user")
def me(user: User = Depends(get_current_user)) -> User:
    return user
