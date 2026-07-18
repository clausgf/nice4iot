from pathlib import Path

from app.config import app_config
from app.util import is_valid_filename, is_valid_name


def project_dir(project_name: str) -> Path:
    """Return the project directory path. No existence check.

    Raises:
        ValueError: Invalid name or path escapes the projects directory.
    """
    if not is_valid_name(project_name):
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
    if not is_valid_name(device_name):
        raise ValueError(f"Invalid device name: {device_name}")
    base = project_dir(project_name)
    path = (base / device_name).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Invalid device path: {path}")
    return path


def extension_project_dir(project_name: str, extension_name: str) -> Path:
    """Return an extension's private directory within a project. No existence check.

    Extensions may store their own files under `<project>/.{extension_name}/`
    (see docs/extensions.md). Callers create the directory themselves
    (mkdir(exist_ok=True)) — this function only computes the path.

    Raises:
        ValueError: Invalid name or path escapes the project directory.
    """
    if not is_valid_filename(extension_name):
        raise ValueError(f"Invalid extension name: {extension_name}")
    base = project_dir(project_name)
    path = (base / f'.{extension_name}').resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Invalid extension path: {path}")
    return path
