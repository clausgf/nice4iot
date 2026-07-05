"""
Unit tests for authentication primitives.

These tests are pure (no I/O, no fixtures) and cover the security-critical
token generation, validation, and housekeeping functions.
"""
import datetime
import pytest

from app.exceptions import AuthError
from app.core.token.backend import (
    generate_token,
    create_token,
    validate_token,
    purge_expired_tokens,
)
from app.core.token.models import AuthToken, TOKEN_CHARS, TOKEN_MIN_LENGTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_token(
    *,
    expired: bool = False,
    inactive: bool = False,
    length: int = 32,
) -> tuple[AuthToken, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = datetime.timedelta(seconds=-1) if expired else datetime.timedelta(days=7)
    value = generate_token(length)
    token = AuthToken(
        value=value,
        expires_at=now + delta,
        is_active=not inactive,
    )
    return token, value


# ---------------------------------------------------------------------------
# generate_token
# ---------------------------------------------------------------------------

class TestGenerateToken:
    def test_correct_length(self):
        assert len(generate_token(32)) == 32

    def test_custom_length(self):
        assert len(generate_token(64)) == 64

    def test_only_allowed_chars(self):
        token = generate_token(200)
        assert all(c in TOKEN_CHARS for c in token)

    def test_tokens_are_unique(self):
        tokens = {generate_token(32) for _ in range(200)}
        assert len(tokens) == 200

    def test_minimum_length_enforced(self):
        with pytest.raises(ValueError):
            generate_token(TOKEN_MIN_LENGTH - 1)

    def test_minimum_length_accepted(self):
        token = generate_token(TOKEN_MIN_LENGTH)
        assert len(token) == TOKEN_MIN_LENGTH


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------

class TestCreateToken:
    def test_expires_at_is_set(self):
        token = create_token(datetime.timedelta(days=7), length=32)
        now = datetime.datetime.now(datetime.timezone.utc)
        assert token.expires_at > now

    def test_expires_at_matches_duration(self):
        token = create_token(datetime.timedelta(hours=1), length=32)
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = token.expires_at - now
        assert 3590 < delta.total_seconds() < 3610

    def test_token_is_active_by_default(self):
        token = create_token(datetime.timedelta(days=1), length=32)
        assert token.is_active is True


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------

class TestValidateToken:
    def test_valid_token_accepted(self):
        token, value = _make_auth_token()
        result = validate_token(value, [token])
        assert result.value == value

    def test_last_use_at_updated(self):
        token, value = _make_auth_token()
        assert token.last_use_at is None
        validate_token(value, [token])
        assert token.last_use_at is not None

    def test_correct_token_among_many(self):
        others = [_make_auth_token()[0] for _ in range(5)]
        target, value = _make_auth_token()
        result = validate_token(value, others + [target])
        assert result.value == value

    def test_expired_token_rejected(self):
        token, value = _make_auth_token(expired=True)
        with pytest.raises(AuthError):
            validate_token(value, [token])

    def test_inactive_token_rejected(self):
        token, value = _make_auth_token(inactive=True)
        with pytest.raises(AuthError):
            validate_token(value, [token])

    def test_wrong_value_rejected(self):
        token, _ = _make_auth_token()
        with pytest.raises(AuthError):
            validate_token("x" * 32, [token])

    def test_too_short_rejected(self):
        with pytest.raises(AuthError):
            validate_token("short", [])

    def test_empty_list_rejected(self):
        with pytest.raises(AuthError):
            validate_token("x" * 32, [])


# ---------------------------------------------------------------------------
# purge_expired_tokens
# Note: purge_expired_tokens removes tokens past their expiry date only.
# Inactive tokens are NOT removed by purge — they are rejected at validate_token time.
# ---------------------------------------------------------------------------

class TestPurgeExpiredTokens:
    def test_removes_expired(self):
        expired, _ = _make_auth_token(expired=True)
        valid, _ = _make_auth_token()
        result = purge_expired_tokens([expired, valid])
        assert len(result) == 1
        assert result[0].value == valid.value

    def test_keeps_inactive_tokens(self):
        """Inactive tokens are not removed by purge (only rejected at auth time)."""
        inactive, _ = _make_auth_token(inactive=True)
        valid, _ = _make_auth_token()
        result = purge_expired_tokens([inactive, valid])
        assert len(result) == 2

    def test_removes_expired_keeps_inactive(self):
        tokens = [
            _make_auth_token(expired=True)[0],
            _make_auth_token(inactive=True)[0],
            _make_auth_token()[0],
        ]
        result = purge_expired_tokens(tokens)
        assert len(result) == 2  # inactive + valid remain; only expired is removed

    def test_keeps_all_valid(self):
        tokens = [_make_auth_token()[0] for _ in range(5)]
        assert len(purge_expired_tokens(tokens)) == 5

    def test_empty_list(self):
        assert purge_expired_tokens([]) == []

    def test_all_expired_returns_empty(self):
        tokens = [_make_auth_token(expired=True)[0] for _ in range(3)]
        assert purge_expired_tokens(tokens) == []
