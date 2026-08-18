"""
Alarm backend — rule evaluation and event persistence.

Rule evaluation is always synchronous so it can be called from
anyio.to_thread.run_sync in async handlers without nested async/await.

Storage layout
--------------
  <project>/.alarm_config.json  — AlarmConfig (rules + built-in thresholds)
  <project>/.alarm_events.json  — list[AlarmEvent] (current event state)
"""
import datetime
from niceview import JsonListAdapter
from pydantic import TypeAdapter
from niceview.dataadapter import JsonAdapter, lenient_list_load

from app.paths import project_dir
from app.core.alarm.models import AlarmConfig, AlarmEvent, MetricAlarmRule, DeviceOfflineAlarm
from app.util import atomic_write, logger, render_datetime

# ---------------------------------------------------------------------------
# File names and adapters
# ---------------------------------------------------------------------------

ALARM_CONFIG_FILE = '.alarm_config.json'
ALARM_EVENTS_FILE = '.alarm_events.json'
ALARM_RULES_CONFIG_FILE = '.alarm_rules.json'

_events_ta = TypeAdapter(list[AlarmEvent])


def get_alarm_adapter(project_name: str) -> JsonAdapter:
    """Return a JsonAdapter for the project alarm configuration."""
    return JsonAdapter(
        AlarmConfig,
        project_dir(project_name) / ALARM_CONFIG_FILE,
        create_if_not_exist=True,
        lock_field='updated_at',
    )

def get_alarm_rules_adapter(project_name: str) -> JsonListAdapter:
    """Return a JsonListAdapter for the project alarm rules configuration."""
    return JsonListAdapter(
        MetricAlarmRule,
        project_dir(project_name) / ALARM_RULES_CONFIG_FILE,
        create_if_not_exist=True,
    )

def get_device_offline_threshold(project_name: str) -> datetime.timedelta:
    """Time since last contact after which a device counts as offline."""
    try:
        return get_alarm_adapter(project_name).read().device_offline.device_offline_threshold
    except Exception:
        return DeviceOfflineAlarm().device_offline_threshold


# ---------------------------------------------------------------------------
# Event persistence
# ---------------------------------------------------------------------------

def load_alarm_events(project_name: str) -> list[AlarmEvent]:
    """Load all alarm events for a project. Returns [] on missing/corrupt file."""
    path = project_dir(project_name) / ALARM_EVENTS_FILE
    if not path.is_file():
        return []
    return lenient_list_load(AlarmEvent, path.read_text(), str(path))


def save_alarm_events(project_name: str, events: list[AlarmEvent]) -> None:
    """Atomically write the event list.  Prunes acknowledged+inactive events."""
    # Keep only events that are still active OR not yet acknowledged.
    pruned = [e for e in events if e.is_active or not e.is_acknowledged]
    path = project_dir(project_name) / ALARM_EVENTS_FILE
    try:
        atomic_write(path, _events_ta.dump_json(pruned, indent=2))
    except OSError as e:
        logger.error(f"Failed to save alarm events for {project_name!r}: {e}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _matches(value: float, comparison: str, threshold: float) -> bool:
    if comparison == '<':
        return value < threshold
    if comparison == '>':
        return value > threshold
    return abs(value - threshold) < 1e-9  # '='


def _find(events: list[AlarmEvent], rule_name: str, device_name: str) -> AlarmEvent | None:
    return next(
        (e for e in events if e.rule_name == rule_name and e.device_name == device_name),
        None,
    )


def _reconcile_alarm_event(
    events: list[AlarmEvent],
    *,
    rule_name: str,
    device_name: str,
    active: bool,
    now: datetime.datetime,
    message: str,
    last_value: float | None = None,
) -> bool:
    """Insert / re-open / touch / clear the single event for ``(rule_name, device_name)``
    so it reflects ``active``. Mutates ``events`` in place; returns True if it changed.

    This is the shared trigger→re-open→touch→clear state machine of every rule type;
    each caller only computes ``active``, ``message`` and ``last_value``. A new event is
    created only when ``len(events)`` grows, which is how callers know to log it.
    """
    existing = _find(events, rule_name, device_name)
    if active:
        if existing is None:
            events.append(AlarmEvent(
                rule_name=rule_name,
                device_name=device_name,
                triggered_at=now,
                last_seen_at=now,
                last_value=last_value,
                message=message,
            ))
            return True
        existing.last_seen_at = now
        existing.last_value = last_value
        if not existing.is_active:              # condition re-triggered after a clear: re-open
            existing.is_active = True
            existing.triggered_at = now
            existing.message = message
            existing.is_acknowledged = False
            existing.acknowledged_at = None
        return True
    if existing and existing.is_active:
        existing.is_active = False
        return True
    return False


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def evaluate_metric_rules(project_name: str, device_name: str,
                           kind: str, values: dict) -> None:
    """Evaluate all active metric alarm rules against incoming telemetry.

    Called synchronously from write_telemetry (via anyio thread).
    """
    try:
        config = get_alarm_adapter(project_name).read()
    except Exception:
        return

    active_rules = [r for r in config.rules if r.is_active and r.kind == kind]
    if not active_rules:
        return

    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    changed = False

    for rule in active_rules:
        raw = values.get(rule.metric)
        if raw is None or not isinstance(raw, (int, float)):
            continue
        value = float(raw)
        active = _matches(value, rule.comparison, rule.threshold)
        msg = f"{rule.kind}.{rule.metric} {rule.comparison} {rule.threshold} (got {value})"
        before = len(events)
        if _reconcile_alarm_event(events, rule_name=rule.name, device_name=device_name,
                                  active=active, now=now, message=msg, last_value=value):
            changed = True
            if len(events) > before:  # a fresh event was appended
                logger.warning(f"Alarm triggered [{project_name}/{device_name}] "
                               f"rule={rule.kind!r}.{rule.name!r}: {msg}")

    if changed:
        save_alarm_events(project_name, events)


def evaluate_device_offline(project_name: str) -> None:
    """Evaluate the built-in device-offline rule for all active devices.

    Called synchronously from the background alarm check loop.
    """
    from app.core.device.backend import get_devices, is_device_online

    try:
        config = get_alarm_adapter(project_name).read()
    except Exception:
        return

    if not config.device_offline.is_active:
        return

    try:
        devices = get_devices(project_name)
    except Exception:
        return

    threshold = config.device_offline.device_offline_threshold
    rule_name = config.device_offline.name
    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    changed = False

    for device in devices:
        if not device.is_active:
            continue

        active = not is_device_online(device, threshold)
        offline_for_s = (now - device.last_seen_at).total_seconds() if device.last_seen_at else None
        msg = f"Device not seen for >{threshold} (last seen at {render_datetime(device.last_seen_at)})"
        before = len(events)
        if _reconcile_alarm_event(events, rule_name=rule_name, device_name=device.name,
                                  active=active, now=now, message=msg, last_value=offline_for_s):
            changed = True
            if len(events) > before:  # a fresh event was appended
                logger.warning(f"Alarm triggered [{project_name}/{device.name}] "
                               f"rule={rule_name}: {msg}")

    if changed:
        save_alarm_events(project_name, events)


def evaluate_provisioning_expiry(project_name: str) -> None:
    """Evaluate the built-in provisioning-token-expiry rule.

    Fires one alarm per active device whose last-used provisioning token expires
    within the configured lead time.
    Called synchronously from the background alarm check loop.
    """
    from app.core.device.backend import get_devices

    try:
        config = get_alarm_adapter(project_name).read()
    except Exception:
        return

    cfg = config.provisioning_expiry
    if not cfg.is_active:
        return

    try:
        devices = get_devices(project_name)
    except Exception:
        return

    threshold = cfg.token_expiration_threshold
    rule_name = cfg.name
    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    changed = False

    def _evaluate(key: str, expires_at: datetime.datetime | None, subject: str) -> None:
        """Trigger / re-open / touch / clear one provisioning-expiry event, keyed by `key`."""
        nonlocal changed
        active = expires_at is not None and expires_at - now <= threshold
        time_left_s = (expires_at - now).total_seconds() if expires_at else None
        msg = f"Provisioning token {subject} expires at {render_datetime(expires_at)}" if expires_at else ""
        before = len(events)
        if _reconcile_alarm_event(events, rule_name=rule_name, device_name=key,
                                  active=active, now=now, message=msg, last_value=time_left_s):
            changed = True
            if len(events) > before:  # a fresh event was appended
                logger.warning(f"Alarm triggered [{project_name}/{key}] "
                               f"rule={rule_name}: {msg}")

    used_fingerprints: set[str] = set()
    for device in devices:
        if not device.is_active:
            continue
        if device.last_provisioning_token_fingerprint:
            used_fingerprints.add(device.last_provisioning_token_fingerprint)
        _evaluate(device.name, device.last_provisioning_token_expires_at, f"{device.last_provisioning_token_fingerprint} used by device {device.name}")

    # Optionally also flag project tokens that are expiring but no device uses.
    if not cfg.only_tokens_in_active_use:
        from app.core.token.backend import get_provisioning_token_adapter
        try:
            tokens = list(get_provisioning_token_adapter(project_name))
        except Exception:
            tokens = []
        for token in tokens:
            if not token.is_active or token.fingerprint in used_fingerprints:
                continue
            _evaluate(f'token:{token.fingerprint}', token.expires_at, f"{token.fingerprint}")

    if changed:
        save_alarm_events(project_name, events)


# ---------------------------------------------------------------------------
# Queries and actions
# ---------------------------------------------------------------------------

def acknowledge_alarm(project_name: str, event_id: str) -> bool:
    """Mark an alarm event as acknowledged. Returns True if found and changed."""
    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    for event in events:
        if event.id == event_id and not event.is_acknowledged:
            event.is_acknowledged = True
            event.acknowledged_at = now
            save_alarm_events(project_name, events)
            return True
    return False


def acknowledge_all_alarms(project_name: str, device_name: str | None = None) -> int:
    """Acknowledge all unacknowledged alarms, optionally filtered by device. Returns count."""
    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    for event in events:
        if event.is_acknowledged:
            continue
        if device_name is not None and event.device_name != device_name:
            continue
        event.is_acknowledged = True
        event.acknowledged_at = now
        count += 1
    if count:
        save_alarm_events(project_name, events)
    return count


def get_pending_alarms(project_name: str,
                       device_name: str | None = None) -> list[AlarmEvent]:
    """Return events that are active or not yet acknowledged (need attention)."""
    events = load_alarm_events(project_name)
    return [
        e for e in events
        if (e.is_active or not e.is_acknowledged)
        and (device_name is None or e.device_name == device_name)
    ]


def get_alarm_count(project_name: str, 
                    device_name: str | None = None) -> int:
    """Count active unacknowledged alarms for one device."""
    return sum(
        1 for e in load_alarm_events(project_name)
        if e.is_active and not e.is_acknowledged and (device_name is None or e.device_name == device_name)
    )
