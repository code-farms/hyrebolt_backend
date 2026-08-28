import jwt
import redis.asyncio as redis

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.generated.models import User
from app.repositories import ProfileRepository, UserRepository

logger = get_logger(__name__)

_REFRESH_KEY = "refresh:{jti}"
# Every live refresh jti a user holds (one per device/session). Lets a replayed
# token revoke the whole family instead of only itself.
_USER_REFRESH_SET = "refresh_user:{user_id}"

# Verified against when the email is unknown, so "no such user" costs the same
# bcrypt work as "wrong password" — no timing side-channel for enumeration.
_DUMMY_HASH = hash_password("timing-equalizer-placeholder")


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        profiles: ProfileRepository,
        redis_client: redis.Redis,
        settings: Settings,
    ) -> None:
        self._users = users
        self._profiles = profiles
        self._redis = redis_client
        self._settings = settings

    async def register(self, *, email: str, password: str, name: str | None) -> User:
        email = email.strip().lower()
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.", "email_taken")
        user = await self._users.create(
            email=email, password_hash=hash_password(password), name=name
        )
        # Every user gets a profile row immediately so the profile page always
        # has something to load and update.
        await self._profiles.upsert_for_user(user.id, {})
        logger.info("user_registered", user_id=user.id)
        return user

    async def login(self, *, email: str, password: str) -> tuple[str, str, User]:
        """Every failure path returns the same invalid_credentials error so a
        response never reveals whether the email exists or is disabled."""
        user = await self._users.get_by_email(email.strip().lower())
        password_ok = verify_password(password, user.passwordHash if user else _DUMMY_HASH)
        if user is None or not password_ok or not user.isActive or user.deletedAt is not None:
            if user is not None and password_ok:
                logger.warning("login_rejected_disabled_account", user_id=user.id)
            raise UnauthorizedError("Invalid email or password.", "invalid_credentials")
        access, refresh = await self._issue_tokens(user.id)
        logger.info("user_logged_in", user_id=user.id)
        return access, refresh, user

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Validate + rotate: the presented token is revoked and a new pair issued.

        A well-formed, unexpired token whose jti is no longer stored has
        already been rotated — i.e. it is being replayed. Either the legitimate
        client or a thief holds the successor, so every refresh token of that
        user is revoked and all sessions must log in again."""
        payload = self._decode_refresh(refresh_token)
        jti, user_id = payload["jti"], payload["sub"]
        key = _REFRESH_KEY.format(jti=jti)
        stored = await self._redis.get(key)
        if stored != user_id:
            if stored is None:
                await self._revoke_all(user_id)
                logger.warning("refresh_token_reuse_detected", user_id=user_id)
            raise UnauthorizedError("Refresh token is no longer valid.", "invalid_token")
        user = await self._users.get_by_id(user_id)
        if user is None or not user.isActive or user.deletedAt is not None:
            raise UnauthorizedError("Refresh token is no longer valid.", "invalid_token")
        await self._revoke(user_id, jti)
        return await self._issue_tokens(user_id)

    async def logout(self, refresh_token: str | None) -> None:
        """Best effort: revoke the presented refresh token if it's valid."""
        if not refresh_token:
            return
        try:
            payload = self._decode_refresh(refresh_token)
        except UnauthorizedError:
            return
        await self._revoke(payload["sub"], payload["jti"])

    async def _issue_tokens(self, user_id: str) -> tuple[str, str]:
        access = create_access_token(self._settings, user_id)
        refresh, jti = create_refresh_token(self._settings, user_id)
        ttl_seconds = self._settings.refresh_token_expire_days * 86400
        await self._redis.set(_REFRESH_KEY.format(jti=jti), user_id, ex=ttl_seconds)
        family = _USER_REFRESH_SET.format(user_id=user_id)
        await self._redis.sadd(family, jti)
        await self._redis.expire(family, ttl_seconds)
        return access, refresh

    async def _revoke(self, user_id: str, jti: str) -> None:
        await self._redis.delete(_REFRESH_KEY.format(jti=jti))
        await self._redis.srem(_USER_REFRESH_SET.format(user_id=user_id), jti)

    async def _revoke_all(self, user_id: str) -> None:
        family = _USER_REFRESH_SET.format(user_id=user_id)
        jtis = await self._redis.smembers(family)
        if jtis:
            await self._redis.delete(*(_REFRESH_KEY.format(jti=jti) for jti in jtis))
        await self._redis.delete(family)

    def _decode_refresh(self, token: str) -> dict[str, str]:
        try:
            payload = decode_token(self._settings, token, expected_type="refresh")
        except jwt.InvalidTokenError as exc:
            raise UnauthorizedError("Refresh token is no longer valid.", "invalid_token") from exc
        if "jti" not in payload or "sub" not in payload:
            raise UnauthorizedError("Refresh token is no longer valid.", "invalid_token")
        return payload
