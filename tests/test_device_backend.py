"""
Unit tests for app.core.device.backend — device_adapter, rename_device,
get_file_path (project fallback), list_files helper, and last_seen_at separation.
"""
import datetime
import json
import pytest

from app.core.device.backend import (
    DEVICE_FILE_NAME,
    _FW_MAX_LEN,
    _RUNTIME_FILE,
    _SYSTEM_METRICS_MAX,
    create_device,
    device_adapter,
    device_status_key,
    get_auth_project_device,
    get_device,
    get_device_path,
    get_file_path,
    project_device_rows,
    read_last_seen,
    read_runtime,
    rename_device,
    write_last_seen,
    write_runtime,
)
from app.core.device.models import Device
from app.core.project.backend import create_project, project_adapter
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
# create_device — is_provisioning_approved uniformly from the project
# ---------------------------------------------------------------------------

def test_create_device_applies_project_autoapproval_true(project):
    p = project_adapter(project).read()
    p.is_provisioning_autoapproval = True
    project_adapter(project).save(p)
    d = create_device(Device(name="auto1", project_name=project))
    assert d.is_provisioning_approved is True


def test_create_device_applies_project_autoapproval_false(project):
    p = project_adapter(project).read()
    p.is_provisioning_autoapproval = False
    project_adapter(project).save(p)
    d = create_device(Device(name="auto2", project_name=project))
    assert d.is_provisioning_approved is False


def test_create_device_ignores_caller_supplied_approval(project):
    """create_device() owns is_provisioning_approved uniformly, overriding
    whatever the caller passed -- so manual "New Device" creation can't
    diverge from the autocreate paths (MQTT, HTTP provisioning) by simply
    forgetting to apply project.is_provisioning_autoapproval itself."""
    p = project_adapter(project).read()
    p.is_provisioning_autoapproval = False
    project_adapter(project).save(p)
    d = create_device(Device(name="auto3", project_name=project, is_provisioning_approved=True))
    assert d.is_provisioning_approved is False


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


# ---------------------------------------------------------------------------
# firmware runtime state — stored in .runtime.json, reported by the device
# ---------------------------------------------------------------------------

def test_write_runtime_records_firmware(device, project):
    write_runtime(project, device.name, firmware_version='v1.2.3')
    rt = read_runtime(project, device.name)
    assert rt.firmware_version == 'v1.2.3'
    assert rt.firmware_reported_at is not None


def test_write_runtime_merges_last_seen_and_firmware(device, project):
    """last_seen and firmware are updated independently; each preserves the other."""
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_last_seen(project, device.name, now)
    write_runtime(project, device.name, firmware_version='v2')  # no last_seen
    rt = read_runtime(project, device.name)
    assert rt.last_seen_at == now  # preserved
    assert rt.firmware_version == 'v2'


def test_firmware_string_is_stripped_and_capped(device, project):
    write_runtime(project, device.name, firmware_version='  ' + 'x' * (_FW_MAX_LEN + 20) + '  ')
    rt = read_runtime(project, device.name)
    assert rt.firmware_version == 'x' * _FW_MAX_LEN


def test_write_runtime_records_system_snapshot(device, project):
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_runtime(project, device.name,
                  system_metrics={'battery_V': 3.71, 'wifi_rssi': -67.0},
                  system_labels={'firmware_id': 'app', 'firmware_sha256': 'abc'},
                  system_reported_at=now)
    rt = read_runtime(project, device.name)
    assert rt.system_metrics == {'battery_V': 3.71, 'wifi_rssi': -67.0}
    assert rt.system_labels == {'firmware_id': 'app', 'firmware_sha256': 'abc'}
    assert rt.system_reported_at == now


def test_system_snapshot_convenience_properties(device, project):
    """battery_voltage/rssi/firmware_id/board are derived from system_metrics/
    system_labels, not stored fields of their own."""
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_runtime(project, device.name,
                  system_metrics={'battery_V': 3.71, 'wifi_rssi': -67.0},
                  system_labels={'firmware_id': 'app', 'board': 'esp32paper'},
                  system_reported_at=now)
    rt = read_runtime(project, device.name)
    assert rt.battery_voltage == 3.71
    assert rt.rssi == -67.0
    assert rt.firmware_id == 'app'
    assert rt.board == 'esp32paper'


def test_system_snapshot_convenience_properties_default_when_unreported(device, project):
    rt = read_runtime(project, device.name)
    assert rt.battery_voltage is None
    assert rt.rssi is None
    assert rt.firmware_id == ''
    assert rt.board == ''


def test_system_snapshot_replaces_wholesale(device, project):
    """A later system push replaces the whole snapshot — a field it omits is gone,
    not stale (replace semantics, not merge)."""
    t1 = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2025, 6, 1, 13, 0, 0, tzinfo=datetime.timezone.utc)
    write_runtime(project, device.name, system_metrics={'battery_V': 3.7, 'wifi_rssi': -60.0},
                  system_reported_at=t1)
    write_runtime(project, device.name, system_metrics={'wifi_rssi': -70.0},
                  system_reported_at=t2)
    rt = read_runtime(project, device.name)
    assert rt.system_metrics == {'wifi_rssi': -70.0}  # battery_V dropped
    assert rt.system_reported_at == t2


def test_system_snapshot_preserved_by_other_writes(device, project):
    """last_seen/firmware writes (no system_reported_at) keep the snapshot untouched."""
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    write_runtime(project, device.name, system_metrics={'battery_V': 3.7},
                  system_reported_at=now)
    write_runtime(project, device.name, firmware_version='v2')
    rt = read_runtime(project, device.name)
    assert rt.system_metrics == {'battery_V': 3.7}
    assert rt.firmware_version == 'v2'


def test_system_metrics_capped(device, project):
    now = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    many = {f'm{i:03d}': float(i) for i in range(_SYSTEM_METRICS_MAX + 10)}
    write_runtime(project, device.name, system_metrics=many, system_reported_at=now)
    rt = read_runtime(project, device.name)
    assert len(rt.system_metrics) == _SYSTEM_METRICS_MAX


def test_get_device_populates_firmware(device, project):
    write_runtime(project, device.name, firmware_version='v9.9')
    d = get_device(project, device.name)
    assert d.firmware_version == 'v9.9'
    assert d.firmware_reported_at is not None


def test_device_active_alarms_counts_active_unacknowledged(device, project):
    from app.core.alarm.backend import acknowledge_alarm, load_alarm_events, save_alarm_events
    from app.core.alarm.models import AlarmEvent

    assert device.active_alarms == 0

    now = datetime.datetime.now(datetime.timezone.utc)
    save_alarm_events(project, [
        AlarmEvent(rule_name='low_temp', device_name=device.name, triggered_at=now, last_seen_at=now),
        AlarmEvent(rule_name='high_temp', device_name=device.name, triggered_at=now, last_seen_at=now,
                  is_active=False),  # resolved: not counted
        AlarmEvent(rule_name='low_temp', device_name='other', triggered_at=now, last_seen_at=now),  # different device
    ])
    assert device.active_alarms == 1

    acknowledge_alarm(project, load_alarm_events(project)[0].id)
    assert device.active_alarms == 0


def test_device_json_not_touched_on_runtime_write(device, project):
    """Writing firmware to .runtime.json must not modify device.json."""
    json_path = get_device_path(project, device.name) / DEVICE_FILE_NAME
    mtime_before = json_path.stat().st_mtime
    write_runtime(project, device.name, firmware_version='v1')
    assert json_path.stat().st_mtime == mtime_before
    assert (get_device_path(project, device.name) / _RUNTIME_FILE).is_file()


def test_auth_records_reported_firmware(provisioned):
    """get_auth_project_device stores the header-reported firmware and returns it."""
    p = provisioned
    _, d = get_auth_project_device(
        p["project_name"], p["device_name"], p["device_token"],
        firmware_version=' v1.4.0 ',
    )
    assert d.firmware_version == 'v1.4.0'
    rt = read_runtime(p["project_name"], p["device_name"])
    assert rt.firmware_version == 'v1.4.0'


def test_auth_without_firmware_preserves_previous(provisioned):
    """A request that omits the header leaves a previously reported version intact."""
    p = provisioned
    write_runtime(p["project_name"], p["device_name"], firmware_version='v1.0.0')
    get_auth_project_device(p["project_name"], p["device_name"], p["device_token"])
    rt = read_runtime(p["project_name"], p["device_name"])
    assert rt.firmware_version == 'v1.0.0'  # unchanged, not wiped


# ---------------------------------------------------------------------------
# device_status_key / project_device_rows — ProjectDevicesTable's status dot
# ---------------------------------------------------------------------------

def test_status_key_inactive_beats_everything(device):
    device.is_active = False
    device.is_provisioning_approved = True
    assert device_status_key(device, online=True) == 'inactive'


def test_status_key_pending_when_not_provisioned(device):
    device.is_active = True
    device.is_provisioning_approved = False
    assert device_status_key(device, online=True) == 'pending'
    assert device_status_key(device, online=False) == 'pending'


def test_status_key_online(device):
    device.is_active = True
    device.is_provisioning_approved = True
    assert device_status_key(device, online=True) == 'online'


def test_status_key_offline(device):
    device.is_active = True
    device.is_provisioning_approved = True
    assert device_status_key(device, online=False) == 'offline'


def test_project_device_rows_shape(device, project):
    device.is_provisioning_approved = True
    device_adapter(project, device.name).save(device)
    write_runtime(project, device.name, system_metrics={'wifi_rssi': -65.4, 'battery_V': 3.9},
                 system_labels={'board': 'esp32'},
                 system_reported_at=datetime.datetime.now(datetime.timezone.utc))

    rows = project_device_rows(project)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == device.name
    status_key, rssi, battery_voltage = row.status
    assert status_key == 'offline'  # never seen -> not online
    assert rssi == -65
    assert battery_voltage == pytest.approx(3.9)
    assert row.board == 'esp32'


def test_project_device_rows_empty_for_empty_project(projects_dir):
    # A project name distinct from the `project` fixture's "proj": get_devices()
    # caches by project name (module-level, not fixture-scoped, see
    # _device_list_cache), so reusing "proj" here could see a stale hit from
    # another test's device within the same TTL window.
    create_project("empty_proj")
    assert project_device_rows("empty_proj") == []


def test_project_device_row_adapter_reload(projects_dir):
    from app.core.device.ui import _ProjectDeviceRowAdapter
    from niceview.dataadapter import ReloadableAdapter

    create_project("reload_proj")
    create_device(Device(name="dev1", project_name="reload_proj"))

    adapter = _ProjectDeviceRowAdapter("reload_proj")
    assert isinstance(adapter, ReloadableAdapter)
    assert [r.name for r in adapter] == ["dev1"]

    # Add second device directly, reload adapter and ensure newly read
    create_device(Device(name="dev2", project_name="reload_proj"))
    adapter.reload()
    assert sorted(r.name for r in adapter) == ["dev1", "dev2"]
