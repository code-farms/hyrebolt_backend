import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import Settings

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # Malformed hash — e.g. the seed's unusable "!" marker. Never a match.
        return False


def create_access_token(settings: Settings, user_id: str) -> str:
    return _encode(
        settings,
        user_id,
        token_type="access",
        lifetime=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(settings: Settings, user_id: str) -> tuple[str, str]:
    """Returns (token, jti). The jti is the Redis revocation key."""
    jti = uuid.uuid4().hex
    token = _encode(
        settings,
        user_id,
        token_type="refresh",
        lifetime=timedelta(days=settings.refresh_token_expire_days),
        jti=jti,
    )
    return token, jti


def decode_token(settings: Settings, token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a token, raising jwt.InvalidTokenError on any problem."""
    payload: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


def _encode(
    settings: Settings,
    user_id: str,
    *,
    token_type: TokenType,
    lifetime: timedelta,
    jti: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
