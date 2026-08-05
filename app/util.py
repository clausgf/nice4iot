import datetime
import re
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import pytz

import logging
logger = logging.getLogger('uvicorn.error')


def shadow_merge[T](own: list[T], under: list[T], key: Callable[[T], str]) -> list[T]:
    """Layer *own* over *under*: entries of own hide same-key entries of under.

    The device-over-project rule, in one place. Used for the merged Files listing
    and for deciding which files the MQTT publisher sends to a device — the two
    must agree, or the UI shows something the device never gets.
    """
    shadowed = {key(item) for item in own}
    return own + [item for item in under if key(item) not in shadowed]


def atomic_write(path: Path, data: str | bytes, *, suffix: str = '.tmp') -> None:
    """Write *data* to *path* via a temp file and a rename.

    The rename is atomic, so a reader — a device polling GET /api/file, another
    admin session, the MQTT publisher — never sees a half-written file. Blocking
    IO: callers in async context wrap this in ``anyio.to_thread.run_sync``.

    Raises OSError, having removed the temp file first. *suffix* exists so writers
    that can race on the same target (device upload vs. MQTT vs. the admin UI)
    can keep their temp files apart.
    """
    tmp = path.with_name(path.name + suffix)
    try:
        if isinstance(data, str):
            tmp.write_text(data, encoding='utf-8')
        else:
            tmp.write_bytes(data)
        tmp.rename(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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


def render_datetime_age(dt: datetime.datetime | None) -> str:
    """Render a UTC datetime as a local-time string with an age suffix."""

    def _ago(delta: datetime.timedelta) -> str:
        s = int(delta.total_seconds())
        if s < 60:
            return f'{s}s ago'
        if s < 3600:
            return f'{s // 60}min ago'
        if s < 86400:
            return f'{s // 3600}h ago'
        return f'{s // 86400}d ago'

    if dt is None:
        return 'never'

    now = datetime.datetime.now(datetime.timezone.utc)
    delta = now - dt
    return f'{render_datetime(dt)}  ({_ago(delta)})'
