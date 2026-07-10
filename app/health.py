"""
Service health registry.

Backends call set_health() after each external write to record whether the
last attempt succeeded.  The project dashboard reads this to render the
System Health card without re-issuing any I/O.
"""
import datetime

from app.util import logger

# key → {"ok": bool, "message": str, "updated_at": datetime}
_health: dict[str, dict] = {}


def set_health(key: str, ok: bool, message: str = '') -> None:
    """Record the outcome of an external service call.

    *key* is a dotted identifier, e.g. ``telemetry:myproject`` or ``mqtt``.
    Failures are logged at ERROR level; callers should not log separately.
    """
    _health[key] = {
        'ok': ok,
        'message': message,
        'updated_at': datetime.datetime.now(datetime.timezone.utc),
    }
    if not ok:
        logger.error(f"[health/{key}] {message}")


def get_health(key: str) -> dict | None:
    """Return the last recorded health entry for *key*, or None if never set."""
    return _health.get(key)


def get_project_health(project_name: str) -> dict[str, dict]:
    """Return all health entries whose key starts with *project_name*."""
    prefix = f'{project_name}:'
    return {k: v for k, v in _health.items() if k.startswith(prefix)}
