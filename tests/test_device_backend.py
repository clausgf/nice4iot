"""
Unit tests for app.core.device.backend — device_adapter, rename_device,
get_file_path (project fallback), and list_files helper.
"""
import pytest

from app.core.device.backend import (
    create_device,
    delete_device,
    device_adapter,
    get_device,
    get_device_path,
    get_file_path,
    rename_device,
)
from app.core.device.models import Device
from app.core.project.backend import create_project
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
    rename_device(project, device.name, "dev-renamed")
    d = get_device(project, "dev-renamed")
    assert d.name == "dev-renamed"


def test_rename_device_old_name_gone(device, project):
    rename_device(project, device.name, "dev-renamed")
    with pytest.raises(FileNotFoundError):
        get_device(project, device.name)


def test_rename_device_invalid_name(device, project):
    with pytest.raises(ValueError):
        rename_device(project, device.name, "bad name!")


def test_rename_device_already_exists(device, project):
    other = Device(name="other", project_name=project)
    create_device(other)
    with pytest.raises(FileExistsError):
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
    with pytest.raises(FileNotFoundError):
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
