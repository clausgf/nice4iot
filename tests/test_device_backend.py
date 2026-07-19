"""
Unit tests for app.core.device.backend — device_adapter, rename_device,
get_file_path (project fallback), list_files helper, and last_seen_at separation.
"""
import datetime
import json
import pytest

from app.core.device.backend import (
    DEVICE_FILE_NAME,
    create_device,
    device_adapter,
    get_device,
    get_device_path,
    get_file_path,
    read_last_seen,
    rename_device,
    write_last_seen,
)
from app.core.device.models import Device
from app.core.project.backend import create_project
from app.exceptions import AlreadyExistsError, NotFoundError
from app.paths import project_dir
from app.util import is_valid_upload_filename


@pytest.fixture
def project(projects_dir):
    create_project("proj")
    return "proj"


@pytest.fixture
def device(project):
    d = Device(name="dev1", project_name=project)
    return create_device(d)


# ---------------------------------------------------------------------------
# device_adapter
# ---------------------------------------------------------------------------

def test_device_adapter_reads_device(device, project):
    adapter = device_adapter(project, device.name)
    d = adapter.read()
    assert d.name == device.name
    assert d.project_name == project


def test_device_adapter_save_roundtrip(device, project):
    adapter = device_adapter(project, device.name)
    d = adapter.read()
    d.description = "hello"
    adapter.save(d)
    d2 = adapter.read()
    assert d2.description == "hello"


# ---------------------------------------------------------------------------
# rename_device
# ---------------------------------------------------------------------------

def test_rename_device_updates_name(device, project):
    rename_device(project, device.name, "dev_renamed")
    d = get_device(project, "dev_renamed")
    assert d.name == "dev_renamed"


def test_rename_device_old_name_gone(device, project):
    rename_device(project, device.name, "dev_renamed")
    with pytest.raises(NotFoundError):
        get_device(project, device.name)


def test_rename_device_invalid_name(device, project):
    with pytest.raises(ValueError):
        rename_device(project, device.name, "bad name!")


def test_rename_device_rejects_hyphen(device, project):
    # Hyphens are no longer valid in device names (Prometheus identifier rule).
    with pytest.raises(ValueError):
        rename_device(project, device.name, "dev-renamed")


def test_rename_device_already_exists(device, project):
    other = Device(name="other", project_name=project)
    create_device(other)
    with pytest.raises(AlreadyExistsError):
        rename_device(project, device.name, "other")


# ---------------------------------------------------------------------------
# get_file_path — project-level fallback
# ---------------------------------------------------------------------------

def test_get_file_path_falls_back_to_project_file(device, project):
    """When no device-specific file exists, project file is returned."""
    proj_path = project_dir(project)
    (proj_path / 'config.json').write_text('{"shared": true}')

    path = get_file_path(project, device.name, 'config.json')
    assert path == proj_path / 'config.json'


def test_get_file_path_device_overrides_project(device, project):
    """Device-specific file takes precedence over the project fallback."""
    proj_path = project_dir(project)
    (proj_path / 'config.json').write_text('{"shared": true}')

    dev_path = get_device_path(project, device.name)
    (dev_path / 'config.json').write_text('{"device": true}')

    path = get_file_path(project, device.name, 'config.json')
    assert path == dev_path / 'config.json'


def test_get_file_path_raises_when_missing(device, project):
    with pytest.raises(NotFoundError):
        get_file_path(project, device.name, 'missing.json')


# ---------------------------------------------------------------------------
# _list_files semantics (tested via filesystem, no NiceGUI import needed)
# ---------------------------------------------------------------------------

def _list_files(directory):
    """Replicate _list_files logic for testing without importing NiceGUI."""
    from pathlib import Path
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(
        [p for p in d.iterdir() if p.is_file() and is_valid_upload_filename(p.name)],
        key=lambda p: p.name,
    )


def test_list_files_excludes_hidden(project):
    proj_path = project_dir(project)
    (proj_path / 'visible.json').write_text('{}')
    (proj_path / '.hidden').write_text('secret')

    names = [p.name for p in _list_files(proj_path)]
    assert 'visible.json' in names
    assert '.hidden' not in names


def test_list_files_excludes_device_directories(device, project):
    """Device subdirectories must not appear in the project file list."""
    proj_path = project_dir(project)
    names = [p.name for p in _list_files(proj_path)]
    assert device.name not in names


def test_list_files_returns_empty_for_nonexistent_dir(project):
    from pathlib import Path
    assert _list_files(Path('/nonexistent/path')) == []


# ---------------------------------------------------------------------------
# last_seen_at — stored in .last_seen, not device.json
# ---------------------------------------------------------------------------

def test_last_seen_none_for_new_device(device, project):
    """Freshly created device has no .last_seen file → last_seen_at is None."""
    assert device.last_seen_at is None
    assert read_last_seen(project, device.name) is None


def test_write_and_read_last_seen(device, project):
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_last_seen(project, device.name, now)
    assert read_last_seen(project, device.name) == now


def test_get_device_reads_last_seen(device, project):
    """get_device() populates last_seen_at from .last_seen, not device.json."""
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_last_seen(project, device.name, now)
    d = get_device(project, device.name)
    assert d.last_seen_at == now


def test_device_json_not_touched_on_last_seen_write(device, project):
    """Writing .last_seen must not modify device.json (no updated_at bump)."""
    dev_path = get_device_path(project, device.name)
    json_path = dev_path / DEVICE_FILE_NAME
    mtime_before = json_path.stat().st_mtime

    write_last_seen(project, device.name, datetime.datetime.now(datetime.timezone.utc))

    assert json_path.stat().st_mtime == mtime_before


def test_last_seen_falls_back_to_device_json_during_migration(device, project):
    """If .last_seen absent but device.json has last_seen_at, preserve it (migration)."""
    # Manually inject last_seen_at into device.json (simulates pre-migration state).
    dev_path = get_device_path(project, device.name)
    json_path = dev_path / DEVICE_FILE_NAME
    data = json.loads(json_path.read_text())
    migrated_ts = "2024-01-01T10:00:00+00:00"
    data['last_seen_at'] = migrated_ts
    json_path.write_text(json.dumps(data))

    d = get_device(project, device.name)
    assert d.last_seen_at is not None
    assert d.last_seen_at.year == 2024
