"""
Unit tests for app.core.device.backend — device_adapter and rename_device.
"""
import pytest

from app.core.device.backend import (
    create_device,
    delete_device,
    device_adapter,
    get_device,
    rename_device,
)
from app.core.device.models import Device
from app.core.project.backend import create_project


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
