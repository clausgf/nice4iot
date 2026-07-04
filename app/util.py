import datetime
import logging
import re

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


def render_datetime(dt: datetime.datetime) -> str:
    """
    Render a datetime object to a string in ISO format.
    """
    return dt.astimezone().strftime("%d.%m.%y %H:%M:%S") if dt else "never"


def flatten_dict(d, parent_key: str = "", sep: str = "_"):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

