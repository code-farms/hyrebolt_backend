import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cure-password")
    assert hashed != "s3cure-password"
    assert verify_password("s3cure-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_unusable_marker_never_verifies() -> None:
    assert not verify_password("anything", "!")
    assert not verify_password("", "!")


def test_access_token_roundtrip() -> None:
    settings = get_settings()
    token = create_access_token(settings, "user-123")
    payload = decode_token(settings, token, expected_type="access")
    assert payload["sub"] == "user-123"


def test_refresh_token_carries_jti_and_wrong_type_rejected() -> None:
    settings = get_settings()
    refresh, jti = create_refresh_token(settings, "user-123")
    payload = decode_token(settings, refresh, expected_type="refresh")
    assert payload["jti"] == jti
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(settings, refresh, expected_type="access")


def test_expired_token_rejected() -> None:
    settings = get_settings().model_copy(update={"access_token_expire_minutes": -1})
    token = create_access_token(settings, "user-123")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(settings, token, expected_type="access")


def test_tampered_token_rejected() -> None:
    settings = get_settings()
    token = create_access_token(settings, "user-123")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(settings, token + "x", expected_type="access")
