import datetime
import secrets

from fastapi import HTTPException, status

from app.core.models import AuthToken


TOKEN_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_!@#$%^&*()-+=<>?'
TOKEN_MIN_LENGTH = 16


def generate_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token of the specified length.

    :param length: The length of the token to generate (default: 32).
    :return: A securely generated random token.
    :raises ValueError: If the specified length is less than the minimum required length.
    """
    if length < TOKEN_MIN_LENGTH:
        raise ValueError("Authentication token length must be at least 16 characters.")
    return ''.join(secrets.choice(TOKEN_CHARS) for _ in range(length))


def create_token(expires_in: datetime.timedelta, length: int = 32) -> AuthToken:
    """
    Create an auth token for a device.

    :param expires_in: The duration for which the token is valid.
    :return: The created authentication token.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    token = generate_token(length)
    return AuthToken(value=token, created_at=now, expires_at=now + expires_in)


def validate_token_str(auth_token: str):
    """
    Validate the authentication token.

    :param auth_token: The token to validate.
    :raises HTTPException: If the token is invalid.
    """
    if not isinstance(auth_token, str) or len(auth_token) < TOKEN_MIN_LENGTH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")
    if not all(char in TOKEN_CHARS for char in auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token contains invalid characters.")


def purge_expired_tokens(tokens: list[AuthToken]) -> list[AuthToken]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return [t for t in tokens if t.is_active and t.expires_at > now]


def validate_token(auth_token: str, valid_tokens: list[AuthToken]) -> AuthToken:
    """
    Check if the authentication token is in the list and not expired.

    :param auth_token: The token to check.
    :raises HTTPException: If the token is invalid or expired.
    """
    validate_token_str(auth_token)
    now = datetime.datetime.now(datetime.timezone.utc)
    for token in valid_tokens:
        if token.value == auth_token:
            if token.is_active and token.expires_at > now:
                # Update the last use time
                token.last_use_at = now
                return token

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token invalid.")
