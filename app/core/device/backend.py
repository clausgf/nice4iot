import datetime
import shutil
import time
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.exceptions import AuthError, ForbiddenError, NotFoundError
from app.paths import device_dir
from app.core.token.backend import (
    create_token, device_token_lock, load_device_tokens,
    purge_expired_tokens, save_device_tokens, validate_token,
)
from app.core.device.models import Device
from app.core.project.backend import get_project, get_project_path
from app.core.project.models import Project
from app.util import logger, is_valid_filename
from niceview.dataadapter import JsonAdapter, lenient_model_load

###############################################################################

DEVICE_FILE_NAME = '.device.json'
_LAST_SEEN_FILE = '.last_seen'

# ---------------------------------------------------------------------------
# In-process device list cache
# ---------------------------------------------------------------------------
# get_devices() reads all .device.json files in a project directory — O(n) file
# reads on every Project Dashboard load. Cache the list for _DEVICE_CACHE_TTL
# seconds and invalidate explicitly on structural changes (create, delete, rename).
# update_device() does NOT invalidate the cache because it runs on every auth
# request (telemetry push); a 60 s staleness in last_seen_at on the project list
# is acceptable. Out-of-band filesystem changes take effect after TTL expiry or
# on SIGUSR1 (see app/main.py).

_device_list_cache: dict[str, tuple[list[Device], float]] = {}
_DEVICE_CACHE_TTL: float = 60.0


def _invalidate_device_list_cache(project_name: str) -> None:
    _device_list_cache.pop(project_name, None)


def flush_device_list_cache() -> None:
    """Flush all cached device lists (call on SIGUSR1 or after out-of-band changes)."""
    _device_list_cache.clear()

###############################################################################
# last_seen_at — stored separately from device.json to eliminate write conflicts
###############################################################################
# device.json is managed by the UI's ModelForm (autosave=True, lock_field='updated_at').
# Storing last_seen_at there caused optimistic-lock conflicts whenever a device pushed
# telemetry while a user had the General tab open. .last_seen holds only the timestamp;
# get_device() reads it and populates the in-memory field.


def write_last_seen(project_name: str, device_name: str, dt: datetime.datetime) -> None:
    """Atomically write last_seen_at to .last_seen (separate from device.json)."""
    path = device_dir(project_name, device_name) / _LAST_SEEN_FILE
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(dt.isoformat())
    tmp.rename(path)


def read_last_seen(project_name: str, device_name: str) -> datetime.datetime | None:
    """Read last_seen_at from .last_seen. Returns None if the file does not exist."""
    path = device_dir(project_name, device_name) / _LAST_SEEN_FILE
    try:
        return datetime.datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None

###############################################################################


def is_device_online(device, threshold_s: int) -> bool:
    """Return True if the device was last seen within threshold_s seconds."""
    if device.last_seen_at is None:
        return False
    delta = datetime.datetime.now(datetime.timezone.utc) - device.last_seen_at
    return delta.total_seconds() <= threshold_s


def get_device_path(project_name: str, device_name: str, check_device_exists: bool = True) -> Path:
    """Return the device directory path, with optional existence check.

    Raises:
        ValueError: Invalid name or path escapes the project directory.
        FileNotFoundError: Project or device does not exist.
    """
    get_project_path(project_name)  # validates project name and existence
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
    project_path = get_project_path(project_name)
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
        temp_file = device_file.with_name(device_file.name + '.tmp')
        temp_file.write_text(device.model_dump_json(indent=2))
        temp_file.rename(device_file)
    except Exception:
        shutil.rmtree(device_path, ignore_errors=True)
        raise
    _invalidate_device_list_cache(device.project_name)

    from app.extensions import notify_device_provisioned
    notify_device_provisioned(device)

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
        device = lenient_model_load(Device, device_file.read_text(), str(device_file))
        device.name = device_name
    else:
        stat_info = device_path.stat()
        device = Device(
            name=device_name,
            project_name=project_name,
            created_at=datetime.datetime.fromtimestamp(stat_info.st_ctime, tz=datetime.timezone.utc),
            updated_at=datetime.datetime.fromtimestamp(stat_info.st_mtime, tz=datetime.timezone.utc),
        )
    # last_seen_at lives in .last_seen (not device.json) to avoid write conflicts
    # with the UI's autosave adapter. Fall back to device.json value during migration
    # (old devices that haven't authenticated yet after the switch).
    fresh = read_last_seen(project_name, device_name)
    if fresh is not None:
        device.last_seen_at = fresh
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
    temp_file = device_file.with_name(device_file.name + '.tmp')
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
    _invalidate_device_list_cache(project_name)


def get_devices(project_name: str) -> list[Device]:
    """Return all devices in a project, silently skipping any that fail to load.

    Results are cached for _DEVICE_CACHE_TTL seconds. Structural changes
    (create, delete, rename) invalidate the cache immediately. Out-of-band
    filesystem changes (bypassing the UI) are reflected after TTL expiry
    or on SIGUSR1 (see flush_device_list_cache).
    """
    cached = _device_list_cache.get(project_name)
    if cached:
        devices, ts = cached
        if time.monotonic() - ts < _DEVICE_CACHE_TTL:
            return devices

    project_path = get_project_path(project_name)
    devices = []
    for device_path in project_path.iterdir():
        if not device_path.is_dir() or not is_valid_filename(device_path.name):
            continue
        try:
            devices.append(get_device(project_name, device_path.name))
        except Exception as e:
            logger.error(f"Error reading device file {device_path}: {e}")
    _device_list_cache[project_name] = (devices, time.monotonic())
    return devices

###############################################################################

def get_auth_project_device(project_name: str, device_name: str, device_token: str) -> tuple[Project, Device]:
    """Authenticate device and return (project, device).

    Raises:
        NotFoundError: Project or device not found, or device inactive.
        ForbiddenError: Project not active or HTTP API disabled.
        AuthError: Token invalid, expired, or malformed.
    """
    try:
        project = get_project(project_name)
    except (ValueError, FileNotFoundError) as e:
        raise NotFoundError(str(e)) from e
    except PermissionError as e:
        raise ForbiddenError(str(e)) from e

    if not project.is_http_enabled:
        raise ForbiddenError(f"HTTP API is disabled for project {project_name}.")

    try:
        device = get_device(project_name, device_name, check_active=True)
    except (ValueError, FileNotFoundError) as e:
        raise NotFoundError(str(e)) from e
    except PermissionError as e:
        raise NotFoundError(str(e)) from e  # normalized to 401 by device_auth anyway

    with device_token_lock(project_name, device_name):
        tokens = load_device_tokens(project_name, device_name)
        validate_token(device_token, tokens)  # raises AuthError
        save_device_tokens(project_name, device_name, tokens)

    now = datetime.datetime.now(datetime.timezone.utc)
    write_last_seen(project_name, device_name, now)
    device.last_seen_at = now

    return project, device


MAX_DEVICE_TOKENS = 32

def device_provision(project: Project, device_name: str):
    """Provision a device and return the new bearer AuthToken.

    Raises:
        NotFoundError: Device not found and autocreate is disabled.
        ForbiddenError: Project or device inactive, or device not approved.
    """
    if not project.is_active:
        raise ForbiddenError(f"Project {project.name} is not active.")

    now = datetime.datetime.now(datetime.timezone.utc)

    try:
        device = get_device(project.name, device_name)
    except FileNotFoundError:
        if not project.is_autocreate_devices:
            raise NotFoundError(f"Device {device_name} does not exist and autocreate is disabled.")
        device = create_device(Device(
            name=device_name,
            project_name=project.name,
            is_provisioning_approved=project.is_provisioning_autoapproval,
        ))

    device.last_provisioning_request_at = now

    if not device.is_active:
        update_device(device)
        raise ForbiddenError(f"Device {device_name} is not active.")

    if not device.is_provisioning_approved:
        update_device(device)
        raise ForbiddenError(f"Device {device_name} is not approved for provisioning.")

    token = create_token(datetime.timedelta(days=project.device_tokens_expire_in), project.device_token_length)

    with device_token_lock(project.name, device_name):
        tokens = load_device_tokens(project.name, device_name)
        tokens = purge_expired_tokens(tokens)

        # Enforce token cap: evict the least-recently-used token when at the limit.
        # Normalise naive datetimes to UTC so the sort key is always comparable.
        _utc = datetime.timezone.utc
        def _lru_key(t: 'AuthToken') -> datetime.datetime:
            dt = t.last_use_at
            if dt is None:
                return datetime.datetime.min.replace(tzinfo=_utc)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=_utc)
        if len(tokens) >= MAX_DEVICE_TOKENS:
            tokens.sort(key=_lru_key)
            tokens = tokens[-(MAX_DEVICE_TOKENS - 1):]

        tokens.append(token)
        save_device_tokens(project.name, device_name, tokens)

    device.last_provisioned_at = now
    update_device(device)

    return token

###############################################################################

def device_adapter(project_name: str, device_name: str) -> JsonAdapter:
    """Return a JsonAdapter for the device JSON file (for UI ModelForm binding)."""
    device_file = get_device_path(project_name, device_name) / DEVICE_FILE_NAME
    return JsonAdapter(Device, device_file, create_if_not_exist=True,
                              created_field='created_at', lock_field='updated_at')


def rename_device(project_name: str, old_device_name: str, new_device_name: str) -> None:
    """Rename a device directory and update the name field in its JSON file.

    Raises:
        ValueError: Invalid new name.
        FileNotFoundError: Old device does not exist.
        FileExistsError: New device name is already taken.
        OSError: Rename failed.
    """
    if not is_valid_filename(new_device_name):
        raise ValueError(f"Invalid device name: {new_device_name}")
    old_path = get_device_path(project_name, old_device_name)
    new_path = device_dir(project_name, new_device_name)
    if new_path.exists():
        raise FileExistsError(f"Device {new_device_name} already exists.")
    old_path.rename(new_path)
    device_json = new_path / DEVICE_FILE_NAME
    if device_json.is_file():
        device = lenient_model_load(Device, device_json.read_text(), str(device_json))
        device.name = new_device_name
        temp = device_json.with_name(device_json.name + '.tmp')
        temp.write_text(device.model_dump_json(indent=2))
        temp.rename(device_json)
    _invalidate_device_list_cache(project_name)
