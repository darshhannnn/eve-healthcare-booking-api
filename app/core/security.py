"""Password hashing (bcrypt) and JWT issuing/verification (PyJWT)."""

import uuid
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.time import utcnow


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )


def webhook_signature(raw_body: bytes, secret: str) -> str:
    """HMAC-SHA256 hex digest of the raw request body — the format the
    simulated payment provider uses in its ``X-EVE-Signature`` header."""
    import hashlib
    import hmac

    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
