import datetime
import logging
import re

import pytz

logger = logging.getLogger('uvicorn.error')


FILENAME_REGEX = r'^[a-zA-Z0-9_\-+]+$'
URL_REGEX = r'^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$'
UPLOAD_FILENAME_REGEX = r'^[a-zA-Z0-9][a-zA-Z0-9_\-.]*$'

def is_valid_filename(filename: str) -> bool:
    """
    Check if the filename consists of alphanumeric characters, underscores, hyphens, and plus signs.
    """
    return re.match(FILENAME_REGEX, filename) is not None


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


def clean_path_parameter(path_element: str) -> str:
    """
    Clean the path_element to prevent path traversal.
    """
    return path_element.replace('/', '').replace('..', '')


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


def flatten_dict(d, parent_key: str = "", sep: str = "_"):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

