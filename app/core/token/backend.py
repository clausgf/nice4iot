import datetime
import fcntl
import secrets
from contextlib import contextmanager
from pathlib import Path

from niceview.dataadapter import JsonListAdapter
from pydantic import TypeAdapter

from app.exceptions import AuthError
from app.paths import project_dir
from app.core.token.models import AuthToken, TOKEN_CHARS, TOKEN_MIN_LENGTH
from niceview.dataadapter import lenient_list_load

###############################################################################

PROVISIONING_FILE_NAME = '.provisioning.json'
DEVICE_TOKEN_FILE_NAME = '.tokens.json'

_token_list_adapter = TypeAdapter(list[AuthToken])

###############################################################################


def generate_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.

    :param length: Token length (default: 32).
    :raises ValueError: If length is below the minimum.
    """
    if length < TOKEN_MIN_LENGTH:
        raise ValueError(f"Token length must be at least {TOKEN_MIN_LENGTH} characters.")
    return ''.join(secrets.choice(TOKEN_CHARS) for _ in range(length))


def create_token(expires_in: datetime.timedelta, length: int = 32, name: str = "") -> AuthToken:
    """Create a new AuthToken with the given expiry and length."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return AuthToken(
        name=name,
        value=generate_token(length),
        expires_at=now + expires_in,
        created_at=now,
        updated_at=now,
        last_use_at=None,
    )


def validate_token_str(auth_token: str) -> None:
    """
    Validate the format of a token string.

    :raises AuthError: If the token is malformed.
    """
    if not isinstance(auth_token, str) or len(auth_token) < TOKEN_MIN_LENGTH:
        raise AuthError("Invalid authentication token.")
    if not all(char in TOKEN_CHARS for char in auth_token):
        raise AuthError("Authentication token contains invalid characters.")


def purge_expired_tokens(tokens: list[AuthToken]) -> list[AuthToken]:
    """Return a new list with all expired tokens removed."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return [t for t in tokens if t.expires_at > now]


def validate_token(auth_token: str, valid_tokens: list[AuthToken]) -> AuthToken:
    """
    Check a token string against a list and return the matching token.

    Mutates the matched token's ``last_use_at`` field in place.

    :raises AuthError: If the token is invalid or expired.
    """
    validate_token_str(auth_token)
    now = datetime.datetime.now(datetime.timezone.utc)
    for token in valid_tokens:
        if token.value == auth_token and token.is_active and token.expires_at > now:
            token.last_use_at = now
            return token
    raise AuthError("Authentication token invalid.")

###############################################################################
# Path helpers and adapters
###############################################################################


def get_provisioning_token_filename(project_name: str) -> Path:
    """Return the path to the provisioning tokens file for a project."""
    return project_dir(project_name) / PROVISIONING_FILE_NAME


def get_provisioning_token_adapter(project_name: str) -> JsonListAdapter:
    """Return a JsonListAdapter for a project's provisioning tokens."""
    return JsonListAdapter(AuthToken, get_provisioning_token_filename(project_name))


def get_device_token_filename(project_name: str, device_name: str) -> Path:
    """Return the path to the device tokens file."""
    return project_dir(project_name) / device_name / DEVICE_TOKEN_FILE_NAME


def get_device_token_adapter(project_name: str, device_name: str) -> JsonListAdapter:
    """Return a JsonListAdapter for a device's bearer tokens."""
    return JsonListAdapter(AuthToken, get_device_token_filename(project_name, device_name))


def load_device_tokens(project_name: str, device_name: str) -> list[AuthToken]:
    """Load device tokens from disk. Returns an empty list if the file does not exist."""
    file = get_device_token_filename(project_name, device_name)
    if not file.exists():
        return []
    return lenient_list_load(AuthToken, file.read_text(), str(file))


def save_device_tokens(project_name: str, device_name: str, tokens: list[AuthToken]) -> None:
    """Atomically write device tokens to disk."""
    file = get_device_token_filename(project_name, device_name)
    temp = file.with_name(file.name + '.tmp')
    temp.write_bytes(_token_list_adapter.dump_json(tokens, indent=2))
    temp.rename(file)


@contextmanager
def device_token_lock(project_name: str, device_name: str):
    """Exclusive file lock around token read-modify-write operations.

    Prevents race conditions when multiple requests provision or authenticate
    the same device concurrently. Uses fcntl.flock (Linux/macOS only).
    """
    lock_path = get_device_token_filename(project_name, device_name).with_suffix('.lock')
    with open(lock_path, 'w') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
