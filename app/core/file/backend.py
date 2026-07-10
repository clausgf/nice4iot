"""
File transfer backend — state tracking, watcher loop, and publish trigger.

Tracks per-device file publication state in .mqtt_file_state.json and
periodically pushes changed files to devices via MQTT.

The actual MQTT publish is performed through a registered callback to avoid a
circular import with app.mqtt.backend.
"""
import asyncio
import datetime
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import anyio

from niceview.dataadapter import JsonAdapter

from app.config import app_config
from app.paths import project_dir as get_project_dir, device_dir as get_device_dir
from app.core.file.models import FileConfig
from app.util import logger, is_valid_upload_filename
from app.util_json import LenientJsonAdapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILE_STATE_FILENAME = '.mqtt_file_state.json'
_FILE_CONFIG_FILENAME = '.file_config.json'

# ---------------------------------------------------------------------------
# Config adapter
# ---------------------------------------------------------------------------

def get_file_adapter(project_name: str) -> LenientJsonAdapter:
    """Return a LenientJsonAdapter for the per-project file configuration."""
    return LenientJsonAdapter(FileConfig,
                              get_project_dir(project_name) / _FILE_CONFIG_FILENAME,
                              create_if_not_exist=True, lock_field='updated_at')


def get_file_config(project_name: str) -> FileConfig:
    """Load and return the file configuration for a project."""
    return get_file_adapter(project_name).read()


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------

def _state_path(project_name: str, device_name: str) -> Path:
    """Return the path to the per-device MQTT file state JSON."""
    return get_device_dir(project_name, device_name) / FILE_STATE_FILENAME


def load_file_state(project_name: str, device_name: str) -> dict:
    """Load the per-device file publish state. Returns {} on any error."""
    path = _state_path(project_name, device_name)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def save_file_state(project_name: str, device_name: str, state: dict) -> None:
    """Atomically write the per-device file publish state."""
    path = _state_path(project_name, device_name)
    tmp = path.with_name(FILE_STATE_FILENAME + '.tmp')
    try:
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')
        tmp.rename(path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        logger.error(f"Failed to save file state for {project_name}/{device_name}: {e}")


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

def _list_publishable_files(directory: Path) -> list[Path]:
    """Return non-dot files with valid upload filenames, sorted alphabetically."""
    if not directory.is_dir():
        return []
    return sorted(
        [p for p in directory.iterdir()
         if p.is_file() and is_valid_upload_filename(p.name)],
        key=lambda p: p.name,
    )


# ---------------------------------------------------------------------------
# Publish callback
# ---------------------------------------------------------------------------

_publish_callback: Callable | None = None


def register_publish_callback(callback: Callable) -> None:
    """Register the async callback used to publish files via MQTT.

    Expected signature:
        async def callback(project_name, device_name, topic_base, filename,
                           content, qos, retain) -> bool
    """
    global _publish_callback
    _publish_callback = callback


# ---------------------------------------------------------------------------
# Publish a single file
# ---------------------------------------------------------------------------

async def publish_file_now(project_name: str, device_name: str,
                           file_path: Path) -> bool:
    """Read *file_path* and publish it to *device_name* via MQTT.

    Updates the per-device state on success. Returns True if published.
    Silently returns False when no publish callback is registered (MQTT not set up).
    """
    from app.core.project.backend import get_project

    if _publish_callback is None:
        return False

    try:
        project = await anyio.to_thread.run_sync(
            lambda: get_project(project_name, check_active=False)
        )
    except Exception as e:
        logger.error(f"publish_file_now: cannot load project {project_name}: {e}")
        return False

    if not project.is_mqtt_enabled:
        return False

    config = await anyio.to_thread.run_sync(lambda: get_file_config(project_name))

    try:
        content = await anyio.to_thread.run_sync(file_path.read_bytes)
    except OSError as e:
        logger.error(f"publish_file_now: cannot read {file_path}: {e}")
        return False

    filename = file_path.name
    try:
        published = await _publish_callback(
            project_name, device_name, project.mqtt_topic_base, filename,
            content, config.mqtt_qos, config.mqtt_retain,
        )
    except Exception as e:
        logger.error(f"publish_file_now: callback error for "
                     f"{project_name}/{device_name}/{filename}: {e}")
        return False

    if published:
        # Update state
        mtime = await anyio.to_thread.run_sync(lambda: os.path.getmtime(str(file_path)))
        state = await anyio.to_thread.run_sync(
            lambda: load_file_state(project_name, device_name)
        )
        state[filename] = {
            'mtime': mtime,
            'published_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        await anyio.to_thread.run_sync(
            lambda: save_file_state(project_name, device_name, state)
        )
    return published


# ---------------------------------------------------------------------------
# Project-level check and publish
# ---------------------------------------------------------------------------

async def check_and_publish_project(project_name: str) -> None:
    """Check all files for a project and publish changed ones to active devices.

    For each active device: compares current mtime against the stored state
    for both device-specific files and project-wide files. Publishes any file
    whose mtime has changed (or that has never been published).
    """
    from app.core.project.backend import get_project
    from app.core.device.backend import get_devices

    try:
        project = await anyio.to_thread.run_sync(
            lambda: get_project(project_name, check_active=False)
        )
    except Exception as e:
        logger.error(f"check_and_publish_project: cannot load project {project_name}: {e}")
        return

    if not project.is_mqtt_enabled:
        return

    try:
        devices = await anyio.to_thread.run_sync(lambda: get_devices(project_name))
    except Exception as e:
        logger.error(f"check_and_publish_project: cannot list devices "
                     f"for {project_name}: {e}")
        return

    project_path = get_project_dir(project_name)
    project_files = await anyio.to_thread.run_sync(
        lambda: _list_publishable_files(project_path)
    )

    for device in devices:
        if not device.is_active:
            continue

        device_path = get_device_dir(project_name, device.name)
        device_files = await anyio.to_thread.run_sync(
            lambda dp=device_path: _list_publishable_files(dp)
        )

        state = await anyio.to_thread.run_sync(
            lambda: load_file_state(project_name, device.name)
        )

        # Build a merged list: device-specific files take priority over project files
        device_filenames = {p.name for p in device_files}
        files_to_check: list[Path] = list(device_files)
        for pf in project_files:
            if pf.name not in device_filenames:
                files_to_check.append(pf)

        for file_path in files_to_check:
            fname = file_path.name
            try:
                current_mtime = await anyio.to_thread.run_sync(
                    lambda fp=file_path: os.path.getmtime(str(fp))
                )
            except OSError:
                continue

            stored = state.get(fname, {})
            stored_mtime = stored.get('mtime')
            if stored_mtime is None or current_mtime != stored_mtime:
                await publish_file_now(project_name, device.name, file_path)


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------

_last_check: dict[str, float] = {}


async def file_watcher_loop() -> None:
    """Background loop that periodically checks and publishes changed files.

    Runs every 10 seconds; for each MQTT-enabled project checks whether the
    configured check interval has elapsed and, if so, calls
    check_and_publish_project.
    """
    from app.core.project.backend import get_projects

    while True:
        try:
            projects = await anyio.to_thread.run_sync(get_projects)
        except Exception as e:
            logger.error(f"file_watcher_loop: cannot list projects: {e}")
            projects = []

        now = time.monotonic()
        for project in projects:
            if not project.is_mqtt_enabled:
                continue
            try:
                config = await anyio.to_thread.run_sync(
                    lambda pn=project.name: get_file_config(pn)
                )
                interval = max(10, config.mqtt_check_interval_s)
            except Exception:
                interval = 60

            last = _last_check.get(project.name, 0.0)
            if now - last < interval:
                continue

            _last_check[project.name] = now
            try:
                await check_and_publish_project(project.name)
            except Exception as e:
                logger.exception(f"file_watcher_loop: error for {project.name}: {e}")

        await asyncio.sleep(10)
