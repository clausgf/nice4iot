import datetime
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from niceview.dataadapter import JsonAdapter

if TYPE_CHECKING:
    from app.core.token.models import AuthToken

from app.exceptions import AlreadyExistsError, ForbiddenError, NotFoundError
from app.paths import device_dir
from app.core.token.backend import (
    create_token, device_token_lock, load_device_tokens,
    purge_expired_tokens, save_device_tokens, validate_token,
)
from app.core.device.models import Device, DeviceRuntime
from app.core.project.backend import get_project, get_project_path
from app.core.project.models import Project
from app.util import atomic_write, logger, is_valid_name
from niceview.dataadapter import lenient_model_load

###############################################################################

DEVICE_FILE_NAME = '.device.json'
_RUNTIME_FILE = '.runtime.json'
_LAST_SEEN_FILE = '.last_seen'  # legacy: bare-timestamp file, read-only migration fallback
_FW_MAX_LEN = 64  # cap device-reported firmware strings (untrusted header input)
_SYSTEM_METRICS_MAX = 32  # cap cached system metrics per device (bounds .runtime.json size)

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
# Device runtime state — stored separately from device.json to eliminate conflicts
###############################################################################
# device.json is managed by the UI's ModelForm (autosave=True, lock_field='updated_at').
# Storing last_seen_at there caused optimistic-lock conflicts whenever a device pushed
# telemetry while a user had the General tab open. .runtime.json holds the fields a
# device updates on every request (last_seen_at) or reports (firmware_version); it is
# never touched by the UI. get_device() reads it and copies the values onto the model.


def _read_legacy_last_seen(project_name: str, device_name: str) -> datetime.datetime | None:
    """Read the pre-.runtime.json bare-timestamp .last_seen file (migration fallback)."""
    path = device_dir(project_name, device_name) / _LAST_SEEN_FILE
    try:
        return datetime.datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_runtime(project_name: str, device_name: str) -> DeviceRuntime:
    """Load the device runtime sidecar. Falls back to the legacy .last_seen file,
    then to an empty DeviceRuntime when neither exists."""
    path = device_dir(project_name, device_name) / _RUNTIME_FILE
    try:
        text = path.read_text()
    except OSError:
        return DeviceRuntime(last_seen_at=_read_legacy_last_seen(project_name, device_name))
    return lenient_model_load(DeviceRuntime, text, str(path))


def write_runtime(project_name: str, device_name: str, *,
                  last_seen_at: datetime.datetime | None = None,
                  firmware_version: str | None = None,
                  system_metrics: dict | None = None,
                  system_labels: dict | None = None,
                  system_reported_at: datetime.datetime | None = None) -> DeviceRuntime:
    """Merge-update the device runtime sidecar and write it atomically.

    Only the provided (non-None) fields are changed; the rest are preserved. Passing
    a firmware_version/commit stamps firmware_reported_at. Firmware strings are
    stripped and length-capped (untrusted device input).

    Passing ``system_reported_at`` records a system-telemetry snapshot: it and the
    accompanying ``system_metrics``/``system_labels`` **replace** the cached values
    wholesale (they are one write's numerics and labels, already normalized and
    label-capped by the telemetry backend), capped to ``_SYSTEM_METRICS_MAX``
    metrics so a device can't bloat the sidecar."""
    rt = read_runtime(project_name, device_name)
    if last_seen_at is not None:
        rt.last_seen_at = last_seen_at
    if firmware_version is not None:
        rt.firmware_version = firmware_version.strip()[:_FW_MAX_LEN]
        rt.firmware_reported_at = datetime.datetime.now(datetime.timezone.utc)
    if system_reported_at is not None:
        rt.system_metrics = dict(sorted((system_metrics or {}).items())[:_SYSTEM_METRICS_MAX])
        rt.system_labels = dict(system_labels or {})
        rt.system_reported_at = system_reported_at
    path = device_dir(project_name, device_name) / _RUNTIME_FILE
    atomic_write(path, rt.model_dump_json(indent=2))
    return rt


def write_last_seen(project_name: str, device_name: str, dt: datetime.datetime) -> None:
    """Update last_seen_at in the runtime sidecar (separate from device.json)."""
    write_runtime(project_name, device_name, last_seen_at=dt)


def read_last_seen(project_name: str, device_name: str) -> datetime.datetime | None:
    """Read last_seen_at from the runtime sidecar. Returns None if unknown."""
    return read_runtime(project_name, device_name).last_seen_at

###############################################################################


def is_device_online(device, threshold: datetime.timedelta) -> bool:
    """Return True if the device was last seen within the offline threshold."""
    if device.last_seen_at is None:
        return False
    delta = datetime.datetime.now(datetime.timezone.utc) - device.last_seen_at
    return delta <= threshold


def get_device_path(project_name: str, device_name: str, check_device_exists: bool = True) -> Path:
    """Return the device directory path, with optional existence check.

    Raises:
        ValueError: Invalid name or path escapes the project directory.
        NotFoundError: Project or device does not exist.
    """
    get_project_path(project_name)  # validates project name and existence
    path = device_dir(project_name, device_name)
    if check_device_exists and not path.is_dir():
        raise NotFoundError(f"Device {project_name}/{device_name} does not exist.")
    return path


def get_file_path(project_name: str, device_name: str, filename: str, check_file_exists: bool = True) -> Path:
    """Return the path for a device file with per-project fallback.

    Raises:
        ValueError: Invalid name or path.
        NotFoundError: Project, device, or file does not exist.
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
            raise NotFoundError(f"File not found: {project_name}/{device_name}/{filename}")
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
        AlreadyExistsError: Device already exists.
        OSError: Directory or file could not be created.
    """
    device_path = get_device_path(device.project_name, device.name, check_device_exists=False)
    try:
        device_path.mkdir(exist_ok=False)
    except FileExistsError as e:
        raise AlreadyExistsError(f"Device {device.project_name}/{device.name} already exists.") from e
    try:
        device_file = device_path / DEVICE_FILE_NAME
        now = datetime.datetime.now(datetime.timezone.utc)
        device.created_at = now
        device.updated_at = now
        atomic_write(device_file, device.model_dump_json(indent=2))
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
        NotFoundError: Device does not exist.
        ForbiddenError: check_active is True and the device is not active.
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
    # Runtime state (last_seen_at, firmware_*) lives in .runtime.json (not device.json)
    # to avoid write conflicts with the UI's autosave adapter. last_seen_at falls back
    # to the device.json value during migration (old devices not yet re-seen); the
    # firmware fields default to empty until the device first reports them.
    rt = read_runtime(project_name, device_name)
    if rt.last_seen_at is not None:
        device.last_seen_at = rt.last_seen_at
    device.firmware_version = rt.firmware_version
    device.firmware_reported_at = rt.firmware_reported_at
    if check_active and not device.is_active:
        raise ForbiddenError(f"Device {project_name}/{device_name} is not active.")
    return device


def update_device(device: Device) -> Device:
    """Write the device JSON file atomically.

    Raises:
        ValueError: Invalid name.
        NotFoundError: Device directory does not exist.
        OSError: File could not be written.
    """
    device_file = get_device_path(device.project_name, device.name) / DEVICE_FILE_NAME
    device.updated_at = datetime.datetime.now(datetime.timezone.utc)
    atomic_write(device_file, device.model_dump_json(indent=2))
    return device


def delete_device(project_name: str, device_name: str) -> None:
    """Delete a device directory and all its contents.

    Raises:
        ValueError: Invalid name.
        NotFoundError: Device does not exist.
        OSError: Directory could not be deleted.
    """
    device_path = get_device_path(project_name, device_name)
    shutil.rmtree(device_path)
    _invalidate_device_list_cache(project_name)
    from app.core.alarm.backend import delete_alarms_for_device
    delete_alarms_for_device(project_name, device_name)


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
        if not device_path.is_dir() or not is_valid_name(device_path.name):
            continue
        try:
            devices.append(get_device(project_name, device_path.name))
        except Exception as e:
            logger.error(f"Error reading device file {device_path}: {e}")
    _device_list_cache[project_name] = (devices, time.monotonic())
    return devices

###############################################################################

def get_auth_project_device(project_name: str, device_name: str, device_token: str,
                            firmware_version: str | None = None) -> tuple[Project, Device]:
    """Authenticate device and return (project, device).

    firmware_version are the values the device optionally reports via
    the X-Firmware-Version request headers; when present they are
    recorded in the runtime sidecar alongside last_seen_at.

    Raises:
        NotFoundError: Project or device not found, or device inactive.
        ForbiddenError: Project not active or HTTP API disabled.
        AuthError: Token invalid, expired, or malformed.
    """
    try:
        project = get_project(project_name)
    except ValueError as e:
        # invalid name — normalized to NotFoundError; NotFoundError and
        # ForbiddenError (project inactive) propagate as-is
        raise NotFoundError(str(e)) from e

    if not project.is_http_enabled:
        raise ForbiddenError(f"HTTP API is disabled for project {project_name}.")

    try:
        device = get_device(project_name, device_name, check_active=True)
    except ValueError as e:
        raise NotFoundError(str(e)) from e
    except ForbiddenError as e:
        raise NotFoundError(str(e)) from e  # device inactive; normalized to 401 by device_auth anyway

    with device_token_lock(project_name, device_name):
        tokens = load_device_tokens(project_name, device_name)
        validate_token(device_token, tokens)  # raises AuthError
        save_device_tokens(project_name, device_name, tokens)

    now = datetime.datetime.now(datetime.timezone.utc)
    rt = write_runtime(project_name, device_name, last_seen_at=now,
                       firmware_version=firmware_version)
    device.last_seen_at = now
    device.firmware_version = rt.firmware_version
    device.firmware_reported_at = rt.firmware_reported_at

    return project, device


MAX_DEVICE_TOKENS = 32

def device_provision(project: Project, device_name: str,
                     firmware_version: str | None = None,
                     provisioning_token: 'AuthToken | None' = None):
    """Provision a device and return the new bearer AuthToken.

    firmware_version are optionally reported by the device at
    provisioning (X-Firmware-Version header); when present they
    are recorded in the runtime sidecar. This guarantees a known version at least at
    every token refresh, even if a device omits the header on regular requests.

    provisioning_token is the project provisioning token that authenticated this
    call. When given, its fingerprint and expiry are recorded on the device so an
    operator can later find which devices are affected by a soon-expiring token.

    Raises:
        NotFoundError: Device not found and autocreate is disabled.
        ForbiddenError: Project or device inactive, or device not approved.
    """
    if not project.is_active:
        raise ForbiddenError(f"Project {project.name} is not active.")

    now = datetime.datetime.now(datetime.timezone.utc)

    try:
        device = get_device(project.name, device_name)
    except NotFoundError:
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

    token = create_token(project.device_tokens_expire_in, project.device_token_length)

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
    if provisioning_token is not None:
        device.last_provisioning_token_fingerprint = provisioning_token.fingerprint
        device.last_provisioning_token_expires_at = provisioning_token.expires_at
    update_device(device)

    if firmware_version is not None:
        write_runtime(project.name, device_name,
                      firmware_version=firmware_version)

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
        NotFoundError: Old device does not exist.
        AlreadyExistsError: New device name is already taken.
        OSError: Rename failed.
    """
    if not is_valid_name(new_device_name):
        raise ValueError(f"Invalid device name: {new_device_name}")
    old_path = get_device_path(project_name, old_device_name)
    new_path = device_dir(project_name, new_device_name)
    if new_path.exists():
        raise AlreadyExistsError(f"Device {new_device_name} already exists.")
    old_path.rename(new_path)
    device_json = new_path / DEVICE_FILE_NAME
    if device_json.is_file():
        device = lenient_model_load(Device, device_json.read_text(), str(device_json))
        device.name = new_device_name
        atomic_write(device_json, device.model_dump_json(indent=2))
    _invalidate_device_list_cache(project_name)
    from app.core.alarm.backend import rename_device_in_alarms
    rename_device_in_alarms(project_name, old_device_name, new_device_name)
