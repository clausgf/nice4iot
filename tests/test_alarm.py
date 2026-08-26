"""
Acceptance tests for core.alarm.

Tests cover:
- Metric alarm rule evaluation (trigger, resolve, re-trigger, inactive rule)
- Built-in device-offline rule
- Event acknowledgment (single and bulk)
- Event persistence (save / load round-trip)
- Query helpers (get_pending_alarms, counts)
- No duplicate events on repeated breaches
- Health registry (set_health / get_health)
"""
import datetime
import pytest

from app.config import app_config
from app.core.project.backend import create_project
from app.core.device.backend import create_device, delete_device, get_device, rename_device, update_device
from app.core.device.models import Device
from app.core.alarm.models import MetricAlarmRule, DeviceOfflineAlarm, ProvisioningTokenExpiryAlarm
from app.core.device.backend import flush_device_list_cache
from app.core.alarm.backend import (
    get_alarm_adapter,
    load_alarm_events,
    evaluate_metric_rules,
    evaluate_device_offline,
    acknowledge_alarm,
    acknowledge_all_alarms,
    get_pending_alarms,
    get_alarm_count,
    get_device_offline_threshold,
    evaluate_provisioning_expiry,
    prune_alarms_for_deleted_devices,
)
from app.health import set_health, get_health, get_project_health

# The built-in rules carry their own fixed name; source it from the models.
BUILTIN_DEVICE_OFFLINE = DeviceOfflineAlarm().name
BUILTIN_PROVISIONING_EXPIRY = ProvisioningTokenExpiryAlarm().name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT = 'alarmtest'
DEVICE = 'sensor1'


@pytest.fixture(autouse=True)
def projects_dir(tmp_path, monkeypatch):
    base = tmp_path / 'projects'
    base.mkdir()
    monkeypatch.setattr(app_config, 'projects_dir', base)
    return base


@pytest.fixture
def project(projects_dir):
    create_project(PROJECT)
    return PROJECT


@pytest.fixture
def device(project):
    create_device(Device(name=DEVICE, project_name=PROJECT))
    return DEVICE


@pytest.fixture
def rule(project):
    """Add one active metric rule: temperature < 5."""
    adapter = get_alarm_adapter(PROJECT)
    config = adapter.read()
    config.rules = [
        MetricAlarmRule(
            name='low_temp',
            is_active=True,
            kind='sensors',
            metric='temperature',
            comparison='<',
            threshold=5.0,
        )
    ]
    adapter.save(config)
    return 'low_temp'


# ---------------------------------------------------------------------------
# Metric rule: trigger and resolve
# ---------------------------------------------------------------------------

def test_metric_rule_triggers_on_breach(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    e = events[0]
    assert e.rule_name == 'low_temp'
    assert e.device_name == DEVICE
    assert e.is_active is True
    assert e.is_acknowledged is False
    assert e.last_value == pytest.approx(2.0)
    # message is auto-generated from the rule now that free-text descriptions are gone
    assert e.message == 'sensors.temperature < 5.0 (got 2.0)'


def test_metric_rule_no_alarm_below_threshold(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 10.0})
    assert load_alarm_events(PROJECT) == []


def test_metric_rule_resolves_when_condition_clears(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 20.0})
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    assert events[0].is_active is False


def test_metric_rule_no_duplicate_on_repeated_breach(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 1.0})
    events = load_alarm_events(PROJECT)
    assert len(events) == 1  # still only one event
    assert events[0].last_value == pytest.approx(1.0)
    assert events[0].is_active is True


def test_metric_rule_retriggers_after_clear(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 20.0})  # clears
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 1.0})   # re-triggers
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    e = events[0]
    assert e.is_active is True
    assert e.is_acknowledged is False  # cleared on re-trigger


def test_metric_rule_inactive_rule_not_evaluated(project, device, project_no_active_rule=None):
    adapter = get_alarm_adapter(PROJECT)
    config = adapter.read()
    config.rules = [
        MetricAlarmRule(
            name='disabled',
            is_active=False,
            kind='sensors',
            metric='temperature',
            comparison='<',
            threshold=100.0,
        )
    ]
    adapter.save(config)
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': -999.0})
    assert load_alarm_events(PROJECT) == []


def test_metric_rule_wrong_kind_ignored(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'system', {'temperature': 2.0})
    assert load_alarm_events(PROJECT) == []


def test_metric_rule_missing_metric_ignored(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'humidity': 30.0})
    assert load_alarm_events(PROJECT) == []


def test_metric_rule_equality(project, device):
    adapter = get_alarm_adapter(PROJECT)
    config = adapter.read()
    config.rules = [
        MetricAlarmRule(name='exact', is_active=True,
                        kind='sensors', metric='code',
                        comparison='=', threshold=42.0)
    ]
    adapter.save(config)
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'code': 42.0})
    events = load_alarm_events(PROJECT)
    assert len(events) == 1 and events[0].is_active is True
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'code': 99.0})
    assert load_alarm_events(PROJECT)[0].is_active is False


def test_metric_rule_greater_than(project, device):
    adapter = get_alarm_adapter(PROJECT)
    config = adapter.read()
    config.rules = [
        MetricAlarmRule(name='high_temp', is_active=True,
                        kind='sensors', metric='temperature',
                        comparison='>', threshold=80.0)
    ]
    adapter.save(config)
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 85.0})
    assert load_alarm_events(PROJECT)[0].is_active is True
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 70.0})
    assert load_alarm_events(PROJECT)[0].is_active is False


# ---------------------------------------------------------------------------
# Device offline rule
# ---------------------------------------------------------------------------

def test_device_offline_triggers(project, device):
    # Mark device as last seen a long time ago (beyond the 1-day default threshold)
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=True)
    get_alarm_adapter(PROJECT).save(config)

    evaluate_device_offline(PROJECT)
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    assert events[0].rule_name == BUILTIN_DEVICE_OFFLINE
    assert events[0].device_name == DEVICE
    assert events[0].is_active is True


def test_device_offline_does_not_trigger_if_online(project, device):
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=True)
    get_alarm_adapter(PROJECT).save(config)

    evaluate_device_offline(PROJECT)
    assert load_alarm_events(PROJECT) == []


def test_device_offline_inactive_rule_skipped(project, device):
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=False)
    get_alarm_adapter(PROJECT).save(config)

    evaluate_device_offline(PROJECT)
    assert load_alarm_events(PROJECT) == []


def test_device_offline_resolves_when_back_online(project, device):
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=True)
    get_alarm_adapter(PROJECT).save(config)

    evaluate_device_offline(PROJECT)
    assert load_alarm_events(PROJECT)[0].is_active is True

    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
    update_device(d)
    flush_device_list_cache()  # bypass the TTL cache so get_devices sees fresh data

    evaluate_device_offline(PROJECT)
    assert load_alarm_events(PROJECT)[0].is_active is False


def test_device_offline_uses_the_threshold_from_the_alarm_config(project, device):
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=True,
                                                     device_offline_threshold=datetime.timedelta(hours=1))
    get_alarm_adapter(PROJECT).save(config)
    assert get_device_offline_threshold(PROJECT) == datetime.timedelta(hours=1)

    evaluate_device_offline(PROJECT)
    assert load_alarm_events(PROJECT) == []  # 5 min < 1 h threshold


def test_device_offline_threshold_falls_back_to_the_default(projects_dir):
    assert get_device_offline_threshold('nosuchproject') == datetime.timedelta(days=1)


def test_device_offline_no_duplicate_on_repeated_eval(project, device):
    d = get_device(PROJECT, DEVICE)
    d.last_seen_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    update_device(d)

    config = get_alarm_adapter(PROJECT).read()
    config.device_offline = DeviceOfflineAlarm(is_active=True)
    get_alarm_adapter(PROJECT).save(config)

    evaluate_device_offline(PROJECT)
    evaluate_device_offline(PROJECT)
    assert len(load_alarm_events(PROJECT)) == 1


# ---------------------------------------------------------------------------
# Built-in rule: provisioning token expiry
# ---------------------------------------------------------------------------

def _set_token_expiry(delta: datetime.timedelta | None) -> None:
    """Record a provisioning-token expiry `delta` from now on the test device."""
    d = get_device(PROJECT, DEVICE)
    now = datetime.datetime.now(datetime.timezone.utc)
    d.last_provisioning_token_fingerprint = 'abc123def456'
    d.last_provisioning_token_expires_at = now + delta if delta is not None else None
    update_device(d)
    flush_device_list_cache()  # bypass the get_devices TTL cache


def test_provisioning_expiry_triggers(project, device):
    _set_token_expiry(datetime.timedelta(days=3))  # within the 7-day default threshold
    evaluate_provisioning_expiry(PROJECT)
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    assert events[0].rule_name == BUILTIN_PROVISIONING_EXPIRY
    assert events[0].device_name == DEVICE
    assert events[0].is_active is True


def test_provisioning_expiry_not_triggered_when_far_out(project, device):
    _set_token_expiry(datetime.timedelta(days=90))  # well beyond the 7-day threshold
    evaluate_provisioning_expiry(PROJECT)
    assert load_alarm_events(PROJECT) == []


def test_provisioning_expiry_resolves_when_reprovisioned(project, device):
    _set_token_expiry(datetime.timedelta(days=3))
    evaluate_provisioning_expiry(PROJECT)
    assert load_alarm_events(PROJECT)[0].is_active is True

    _set_token_expiry(datetime.timedelta(days=90))  # e.g. re-provisioned with a fresh token
    evaluate_provisioning_expiry(PROJECT)
    assert load_alarm_events(PROJECT)[0].is_active is False


def test_provisioning_expiry_skipped_when_device_has_no_token(project, device):
    _set_token_expiry(None)
    evaluate_provisioning_expiry(PROJECT)
    assert load_alarm_events(PROJECT) == []


def test_provisioning_expiry_inactive_rule_skipped(project, device):
    _set_token_expiry(datetime.timedelta(days=3))
    config = get_alarm_adapter(PROJECT).read()
    config.provisioning_expiry.is_active = False
    get_alarm_adapter(PROJECT).save(config)

    evaluate_provisioning_expiry(PROJECT)
    assert load_alarm_events(PROJECT) == []


# ---------------------------------------------------------------------------
# Acknowledgment
# ---------------------------------------------------------------------------

def test_acknowledge_alarm(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    event_id = events[0].id

    result = acknowledge_alarm(PROJECT, event_id)
    assert result is True
    events = load_alarm_events(PROJECT)
    assert events[0].is_acknowledged is True
    assert events[0].acknowledged_at is not None


def test_acknowledge_unknown_id_returns_false(project):
    result = acknowledge_alarm(PROJECT, 'nonexistent')
    assert result is False


def test_acknowledge_all_alarms_for_device(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    count = acknowledge_all_alarms(PROJECT, DEVICE)
    assert count == 1
    assert load_alarm_events(PROJECT)[0].is_acknowledged is True


def test_acknowledge_all_alarms_project_wide(project, device, rule):
    create_device(Device(name='sensor2', project_name=PROJECT))
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, 'sensor2', 'sensors', {'temperature': 2.0})
    count = acknowledge_all_alarms(PROJECT)
    assert count == 2


# ---------------------------------------------------------------------------
# Event persistence round-trip
# ---------------------------------------------------------------------------

def test_alarm_events_persist_and_reload(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    reloaded = load_alarm_events(PROJECT)
    assert len(reloaded) == 1
    assert reloaded[0].rule_name == 'low_temp'


def test_acknowledged_inactive_events_pruned_on_save(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    events = load_alarm_events(PROJECT)
    event_id = events[0].id
    # Mark the event resolved
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 20.0})
    # Acknowledge it — this triggers a prune on save
    acknowledge_alarm(PROJECT, event_id)
    # After prune: inactive+acknowledged events are removed
    assert load_alarm_events(PROJECT) == []


# ---------------------------------------------------------------------------
# Alarm events stay in sync with device deletion/rename
# ---------------------------------------------------------------------------

def test_delete_device_clears_its_alarms(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    assert load_alarm_events(PROJECT) != []

    delete_device(PROJECT, DEVICE)
    assert load_alarm_events(PROJECT) == []


def test_delete_device_leaves_other_devices_alarms(project, device, rule):
    create_device(Device(name='other', project_name=PROJECT))
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, 'other', 'sensors', {'temperature': 2.0})

    delete_device(PROJECT, DEVICE)
    remaining = load_alarm_events(PROJECT)
    assert len(remaining) == 1
    assert remaining[0].device_name == 'other'


def test_rename_device_rekeys_its_alarms(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})

    rename_device(PROJECT, DEVICE, 'renamed')

    events = load_alarm_events(PROJECT)
    assert len(events) == 1
    assert events[0].device_name == 'renamed'


def test_prune_alarms_removes_events_for_devices_deleted_outside_delete_device(project, device, rule):
    # Alarm events for a device that vanished without going through delete_device
    # (e.g. its directory was removed directly) should still be cleaned up by the
    # periodic sweep.
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    assert load_alarm_events(PROJECT) != []

    import shutil
    from app.paths import device_dir
    shutil.rmtree(device_dir(PROJECT, DEVICE))
    flush_device_list_cache()

    prune_alarms_for_deleted_devices(PROJECT)
    assert load_alarm_events(PROJECT) == []


def test_prune_alarms_keeps_events_for_existing_devices(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    prune_alarms_for_deleted_devices(PROJECT)
    assert len(load_alarm_events(PROJECT)) == 1


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def test_get_pending_alarms_active(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    pending = get_pending_alarms(PROJECT)
    assert len(pending) == 1
    assert pending[0].is_active is True


def test_get_pending_alarms_resolved_but_unacked(project, device, rule):
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 20.0})  # resolves
    pending = get_pending_alarms(PROJECT)
    assert len(pending) == 1  # still pending — not yet acknowledged
    assert pending[0].is_active is False


def test_get_pending_alarms_by_device(project, device, rule):
    create_device(Device(name='other', project_name=PROJECT))
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, 'other', 'sensors', {'temperature': 2.0})
    assert len(get_pending_alarms(PROJECT)) == 2
    assert len(get_pending_alarms(PROJECT, device_name=DEVICE)) == 1


def test_get_device_alarm_count(project, device, rule):
    assert get_alarm_count(PROJECT, DEVICE) == 0
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    assert get_alarm_count(PROJECT, DEVICE) == 1
    acknowledge_alarm(PROJECT, load_alarm_events(PROJECT)[0].id)
    assert get_alarm_count(PROJECT, DEVICE) == 0


def test_get_project_alarm_count(project, device, rule):
    create_device(Device(name='sensor2', project_name=PROJECT))
    evaluate_metric_rules(PROJECT, DEVICE, 'sensors', {'temperature': 2.0})
    evaluate_metric_rules(PROJECT, 'sensor2', 'sensors', {'temperature': 2.0})
    assert get_alarm_count(PROJECT) == 2


# ---------------------------------------------------------------------------
# Health registry
# ---------------------------------------------------------------------------

def test_health_set_ok():
    set_health('myproject:telemetry', True)
    h = get_health('myproject:telemetry')
    assert h is not None
    assert h['ok'] is True
    assert h['message'] == ''
    assert 'updated_at' in h


def test_health_set_error():
    set_health('myproject:telemetry', False, 'connection refused')
    h = get_health('myproject:telemetry')
    assert h['ok'] is False
    assert 'connection refused' in h['message']


def test_health_unknown_key_returns_none():
    assert get_health('nonexistent:key') is None


def test_get_project_health_filters_by_prefix():
    set_health('proj1:telemetry', True)
    set_health('proj1:logging', False, 'loki down')
    set_health('proj2:telemetry', True)
    ph = get_project_health('proj1')
    assert 'proj1:telemetry' in ph
    assert 'proj1:logging' in ph
    assert 'proj2:telemetry' not in ph
