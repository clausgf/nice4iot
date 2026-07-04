from pathlib import Path
import datetime
import shutil

from fastapi import HTTPException, status

from app.paths import device_dir
from app.core.token.backend import create_token, load_device_tokens, purge_expired_tokens, save_device_tokens, validate_token
from app.core.device.models import Device
from app.core.project.backend import get_project, project_dir_exists
from app.core.project.models import Project
from app.util import logger, is_valid_filename

###############################################################################

DEVICE_FILE_NAME = '.device.json'

###############################################################################

def get_device_path(project_name: str, device_name: str, check_device_exists: bool = True) -> Path:
    """Return the device directory path, with optional existence check.

    Raises:
        ValueError: Invalid name or path escapes the project directory.
        FileNotFoundError: Project or device does not exist.
    """
    project_dir_exists(project_name)  # validates project name and existence
    path = device_dir(project_name, device_name)
    if check_device_exists and not path.is_dir():
        raise FileNotFoundError(f"Device {project_name}/{device_name} does not exist.")
    return path


def get_file_path(project_name: str, device_name: str, filename: str, check_file_exists: bool = True) -> Path:
    """Return the path for a device file with per-project fallback.

    Raises:
        ValueError: Invalid name or path.
        FileNotFoundError: File does not exist.
    """
    project_path = project_dir_exists(project_name)
    device_path = get_device_path(project_name, device_name)

    project_file_path = (project_path / filename).resolve()
    device_file_path = (device_path / filename).resolve()
    if not device_file_path.is_relative_to(device_path) or not project_file_path.is_relative_to(project_path):
        raise ValueError(f"Invalid file path: {filename}")

    if check_file_exists:
        path = device_file_path if device_file_path.is_file() else project_file_path
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {project_name}/{device_name}/{filename}")
    else:
        path = device_file_path
    return path

###############################################################################
# Device CRUD operations
###############################################################################

def create_device(device: Device) -> Device:
    """Create a new device directory and write the initial JSON file.

    Raises:
        ValueError: Invalid name.
        FileExistsError: Device already exists.
        OSError: Directory or file could not be created.
    """
    device_path = get_device_path(device.project_name, device.name, check_device_exists=False)
    device_path.mkdir(exist_ok=False)
    try:
        device_file = device_path / DEVICE_FILE_NAME
        now = datetime.datetime.now(datetime.timezone.utc)
        device.created_at = now
        device.updated_at = now
        temp_file = device_file.with_suffix('.tmp')
        temp_file.write_text(device.model_dump_json(indent=2))
        temp_file.rename(device_file)
    except Exception:
        shutil.rmtree(device_path, ignore_errors=True)
        raise
    return device


def get_device(project_name: str, device_name: str, check_active: bool = False) -> Device:
    """Load and return a device by name.

    Raises:
        ValueError: Invalid name.
        FileNotFoundError: Device does not exist.
        PermissionError: check_active is True and the device is not active.
        OSError: Device file could not be read.
    """
    device_path = get_device_path(project_name, device_name)
    device_file = device_path / DEVICE_FILE_NAME
    if device_file.is_file():
        device = Device.model_validate_json(device_file.read_text())
        device.name = device_name
    else:
        stat_info = device_path.stat()
        device = Device(
            name=device_name,
            project_name=project_name,
            created_at=datetime.datetime.fromtimestamp(stat_info.st_ctime),
            updated_at=datetime.datetime.fromtimestamp(stat_info.st_mtime),
        )
    if check_active and not device.is_active:
        raise PermissionError(f"Device {project_name}/{device_name} is not active.")
    return device


def update_device(device: Device) -> Device:
    """Write the device JSON file atomically.

    Raises:
        ValueError: Invalid name.
        FileNotFoundError: Device directory does not exist.
        OSError: File could not be written.
    """
    device_file = get_device_path(device.project_name, device.name) / DEVICE_FILE_NAME
    device.updated_at = datetime.datetime.now(datetime.timezone.utc)
    temp_file = device_file.with_suffix('.tmp')
    temp_file.write_text(device.model_dump_json(indent=2))
    temp_file.rename(device_file)
    return device


def delete_device(project_name: str, device_name: str) -> None:
    """Delete a device directory and all its contents.

    Raises:
        ValueError: Invalid name.
        FileNotFoundError: Device does not exist.
        OSError: Directory could not be deleted.
    """
    device_path = get_device_path(project_name, device_name)
    shutil.rmtree(device_path)


def get_devices(project_name: str) -> list[Device]:
    """Return all devices in a project, silently skipping any that fail to load."""
    project_path = project_dir_exists(project_name)
    devices = []
    for device_path in project_path.iterdir():
        if not device_path.is_dir() or not is_valid_filename(device_path.name):
            continue
        try:
            devices.append(get_device(project_name, device_path.name))
        except Exception as e:
            logger.error(f"Error reading device file {device_path}: {e}")
    return devices

###############################################################################

def get_auth_project_device(project_name: str, device_name: str, device_token: str) -> tuple[Project, Device]:
    """Authenticate device and return (project, device).

    API boundary: raises HTTPException for all error cases.
    """
    try:
        project = get_project(project_name)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    try:
        device = get_device(project_name, device_name, check_active=True)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    tokens = load_device_tokens(project_name, device_name)
    validate_token(device_token, tokens)
    save_device_tokens(project_name, device_name, tokens)

    device.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
    device = update_device(device)

    return project, device


MAX_DEVICE_TOKENS = 32

def device_provision(project: Project, device_name: str):
    """Provision a device and return the new bearer AuthToken.

    API boundary: raises HTTPException for all error cases.
    """
    if not project.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Project {project.name} is not active.")

    now = datetime.datetime.now(datetime.timezone.utc)

    try:
        device = get_device(project.name, device_name)
    except FileNotFoundError:
        if not project.is_autocreate_devices:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device {device_name} does not exist and autocreate is disabled.")
        device = create_device(Device(name=device_name, project_name=project.name, is_provisioning_approved=project.is_provisioning_autoapproval))

    device.last_provisioning_request_at = now

    if not device.is_active:
        update_device(device)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Device {device_name} is not active.")

    if not device.is_provisioning_approved:
        update_device(device)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Device {device_name} is not approved for provisioning.")

    tokens = load_device_tokens(project.name, device_name)
    tokens = purge_expired_tokens(tokens)

    # Enforce token cap: evict the least-recently-used token when at the limit.
    if len(tokens) >= MAX_DEVICE_TOKENS:
        tokens.sort(key=lambda t: t.last_use_at or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
        tokens = tokens[-(MAX_DEVICE_TOKENS - 1):]

    token = create_token(datetime.timedelta(days=project.device_tokens_expire_in), project.device_token_length)
    tokens.append(token)
    save_device_tokens(project.name, device_name, tokens)
    device.last_provisioned_at = now
    update_device(device)

    return token
