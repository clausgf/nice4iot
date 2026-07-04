from pathlib import Path

from app.config import app_config
from app.util import is_valid_filename


def project_dir(project_name: str) -> Path:
    """Return the project directory path. No existence check.

    Raises:
        ValueError: Invalid name or path escapes the projects directory.
    """
    if not is_valid_filename(project_name):
        raise ValueError(f"Invalid project name: {project_name}")
    base = Path(app_config.projects_dir).resolve()
    path = (base / project_name).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Invalid project path: {path}")
    return path


def device_dir(project_name: str, device_name: str) -> Path:
    """Return the device directory path. No existence check.

    Raises:
        ValueError: Invalid name or path escapes the project directory.
    """
    if not is_valid_filename(device_name):
        raise ValueError(f"Invalid device name: {device_name}")
    base = project_dir(project_name)
    path = (base / device_name).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Invalid device path: {path}")
    return path
