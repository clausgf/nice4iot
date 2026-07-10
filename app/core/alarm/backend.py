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
from pydantic import TypeAdapter
from niceview.dataadapter import JsonAdapter, lenient_list_load

from app.paths import project_dir
from app.core.alarm.models import AlarmConfig, AlarmEvent
from app.util import logger

# ---------------------------------------------------------------------------
# File names and adapters
# ---------------------------------------------------------------------------

ALARM_CONFIG_FILE = '.alarm_config.json'
ALARM_EVENTS_FILE = '.alarm_events.json'

_events_ta = TypeAdapter(list[AlarmEvent])

BUILTIN_DEVICE_UNAVAILABLE = 'device_unavailable'


def get_alarm_config_adapter(project_name: str) -> JsonAdapter:
    """Return a JsonAdapter for the project alarm configuration."""
    return JsonAdapter(
        AlarmConfig,
        project_dir(project_name) / ALARM_CONFIG_FILE,
        create_if_not_exist=True,
        lock_field='updated_at',
    )


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
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_bytes(_events_ta.dump_json(pruned, indent=2))
        tmp.rename(path)
    except OSError as e:
        logger.error(f"Failed to save alarm events for {project_name!r}: {e}")
        tmp.unlink(missing_ok=True)


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


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------

def evaluate_metric_rules(project_name: str, device_name: str,
                           kind: str, values: dict) -> None:
    """Evaluate all active metric alarm rules against incoming telemetry.

    Called synchronously from write_telemetry (via anyio thread).
    """
    try:
        config = get_alarm_config_adapter(project_name).read()
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
        triggered = _matches(value, rule.comparison, rule.threshold)
        existing = _find(events, rule.name, device_name)

        if triggered:
            if existing is None:
                msg = (rule.description or
                       f"{rule.metric} {rule.comparison} {rule.threshold} (got {value})")
                events.append(AlarmEvent(
                    rule_name=rule.name,
                    device_name=device_name,
                    triggered_at=now,
                    last_seen_at=now,
                    last_value=value,
                    message=msg,
                    is_active=True,
                ))
                logger.warning(f"Alarm triggered [{project_name}/{device_name}] "
                               f"rule={rule.name!r}: {msg}")
                changed = True
            else:
                existing.last_seen_at = now
                existing.last_value = value
                changed = True  # always persist updated last_value / last_seen_at
                if not existing.is_active:
                    # Condition re-triggered after a clear: re-open.
                    existing.is_active = True
                    existing.triggered_at = now
                    existing.is_acknowledged = False
                    existing.acknowledged_at = None
        else:
            if existing and existing.is_active:
                existing.is_active = False
                existing.last_seen_at = now
                changed = True

    if changed:
        save_alarm_events(project_name, events)


def evaluate_device_unavailable(project_name: str) -> None:
    """Evaluate the built-in device-unavailable rule for all active devices.

    Called synchronously from the background alarm check loop.
    """
    from app.core.project.backend import get_project
    from app.core.device.backend import get_devices, is_device_online

    try:
        config = get_alarm_config_adapter(project_name).read()
    except Exception:
        return

    if not config.device_unavailable.is_active:
        return

    try:
        project = get_project(project_name, check_active=False)
        devices = get_devices(project_name)
    except Exception:
        return

    threshold_s = config.device_unavailable.threshold_s or project.device_online_threshold_s
    events = load_alarm_events(project_name)
    now = datetime.datetime.now(datetime.timezone.utc)
    changed = False

    for device in devices:
        if not device.is_active:
            continue
        unavailable = not is_device_online(device, threshold_s)
        existing = _find(events, BUILTIN_DEVICE_UNAVAILABLE, device.name)

        if unavailable:
            if existing is None:
                events.append(AlarmEvent(
                    rule_name=BUILTIN_DEVICE_UNAVAILABLE,
                    device_name=device.name,
                    triggered_at=now,
                    last_seen_at=now,
                    message=f"Device not seen for >{threshold_s}s",
                    is_active=True,
                ))
                logger.warning(f"Alarm triggered [{project_name}/{device.name}] "
                               f"rule=device_unavailable: not seen for >{threshold_s}s")
                changed = True
            elif not existing.is_active:
                existing.is_active = True
                existing.triggered_at = now
                existing.last_seen_at = now
                existing.is_acknowledged = False
                existing.acknowledged_at = None
                changed = True
            else:
                existing.last_seen_at = now
        else:
            if existing and existing.is_active:
                existing.is_active = False
                existing.last_seen_at = now
                changed = True

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


def get_device_alarm_count(project_name: str, device_name: str) -> int:
    """Count active unacknowledged alarms for one device."""
    return sum(
        1 for e in load_alarm_events(project_name)
        if e.device_name == device_name and e.is_active and not e.is_acknowledged
    )


def get_project_alarm_count(project_name: str) -> int:
    """Count active unacknowledged alarms for all devices in a project."""
    return sum(
        1 for e in load_alarm_events(project_name)
        if e.is_active and not e.is_acknowledged
    )
