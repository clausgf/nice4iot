import datetime
import logging
import re
from importlib.metadata import PackageNotFoundError, version

import pytz

logger = logging.getLogger('uvicorn.error')


def app_version() -> str:
    """nice4iot's version from its installed package metadata (single source of
    truth: pyproject.toml). Falls back when the project isn't installed (e.g. a
    container built with `uv sync --no-install-project`)."""
    try:
        return version("nice4iot")
    except PackageNotFoundError:
        return "0.0.0+source"


FILENAME_REGEX = r'^[a-zA-Z0-9_\-+]+$'
NAME_REGEX = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
URL_REGEX = r'^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$'
UPLOAD_FILENAME_REGEX = r'^[a-zA-Z0-9][a-zA-Z0-9_\-.]*$'

def is_valid_filename(filename: str) -> bool:
    """
    Check if the filename consists of alphanumeric characters, underscores, hyphens, and plus signs.
    """
    return re.match(FILENAME_REGEX, filename) is not None


def is_valid_name(name: str) -> bool:
    """Check a project or device name.

    Stricter than is_valid_filename: a valid identifier
    (``[a-zA-Z_][a-zA-Z0-9_]*``) with no ``-``, ``+`` or leading digit. This
    guarantees the telemetry metric name ``<project>_<field>`` is always a
    valid Prometheus metric name and that names need no backend-specific
    escaping, avoiding problematic characters at the source.
    """
    return re.match(NAME_REGEX, name) is not None


def is_valid_upload_filename(filename: str) -> bool:
    """
    Check if the filename is safe for device file uploads.

    Allowed: alphanumeric, ``_``, ``-``, ``.``; must start with alphanumeric.
    Rejected: empty, ``..``, path separators, leading dots.
    """
    return (
        bool(re.match(UPLOAD_FILENAME_REGEX, filename))
        and '..' not in filename
    )



def render_datetime(dt: datetime.datetime | None) -> str:
    """Render a UTC datetime as a local-time string using the configured timezone.

    Falls back to system local time if the configured timezone is invalid.
    Returns "never" for None.
    """
    if not dt:
        return "never"
    from app.config import app_config
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    try:
        tz = pytz.timezone(app_config.timezone)
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc
    return dt.astimezone(tz).strftime("%d.%m.%y %H:%M:%S")

