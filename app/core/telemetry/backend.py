import datetime
import json
import numbers
import time
from pathlib import Path

import anyio
from niceview.dataadapter import JsonAdapter

from app.paths import project_dir
from app.core.telemetry.models import TelemetryBackend, TelemetryConfig
from app.core.telemetry.prometheus.backend import PrometheusBackend
from app.core.telemetry.influxdb.backend import InfluxLineBackend

TEL_FILE = '.telemetry.json'
LOCAL_METRICS_FILE = '.device_metrics.jsonl'
LOCAL_METRICS_MAX_LINES = 2000

# ---------------------------------------------------------------------------
# Telemetry backend cache
# ---------------------------------------------------------------------------
# _get_active_backend() reads and parses the telemetry config JSON on every
# call. Cache the resolved backend for _BACKEND_CACHE_TTL seconds.
# Out-of-band config file changes (bypassing the UI) take effect after TTL
# expiry or on SIGUSR1 (see flush_telemetry_backend_cache / app/main.py).

_backend_cache: dict[str, tuple[TelemetryBackend | None, float]] = {}
_BACKEND_CACHE_TTL: float = 60.0

_write_count: dict[str, int] = {}  # keyed by str(path), amortises JSONL trim cost


def flush_telemetry_backend_cache() -> None:
    """Flush all cached telemetry backends (call on SIGUSR1 or config change)."""
    _backend_cache.clear()


def get_telemetry_adapter(project_name: str) -> JsonAdapter:
    """Get a JsonAdapter for the telemetry configuration of a project."""
    return JsonAdapter(TelemetryConfig, project_dir(project_name) / TEL_FILE,
                       create_if_not_exist=True, lock_field='updated_at')


def _get_active_backend(project_name: str) -> TelemetryBackend | None:
    cached = _backend_cache.get(project_name)
    if cached:
        backend, ts = cached
        if time.monotonic() - ts < _BACKEND_CACHE_TTL:
            return backend

    config = get_telemetry_adapter(project_name).read()
    if config.backend == 'prometheus':
        backend = PrometheusBackend(project_name, config.prometheus)
    elif config.backend == 'influxdb':
        backend = InfluxLineBackend(project_name, config.influxdb)
    else:
        backend = None
    _backend_cache[project_name] = (backend, time.monotonic())
    return backend


def _append_local_metrics(project_name: str, device_name: str, kind: str,
                           values: dict, timestamp: datetime.datetime) -> None:
    """Append one JSONL record to the per-device local metrics file."""
    numeric = {k: v for k, v in values.items() if isinstance(v, numbers.Number)}
    if not numeric:
        return
    path = Path(project_dir(project_name)) / device_name / LOCAL_METRICS_FILE
    if not path.parent.is_dir():
        return  # device directory not yet created via create_device()
    record = json.dumps({'ts': timestamp.isoformat(), 'kind': kind, 'v': numeric}) + '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(record)
    # Trim to LOCAL_METRICS_MAX_LINES only every _TRIM_EVERY_N writes.
    # Reading the full file on every append is O(n) per telemetry push; this
    # amortises the cost to O(n / _TRIM_EVERY_N) on average.
    # Key uses the full path so tests using different temp dirs don't share state.
    _TRIM_EVERY_N = 10
    _write_count[str(path)] = _write_count.get(str(path), 0) + 1
    if _write_count[str(path)] >= _TRIM_EVERY_N:
        _write_count[str(path)] = 0
        try:
            lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
            if len(lines) > LOCAL_METRICS_MAX_LINES:
                path.write_text(''.join(lines[-LOCAL_METRICS_MAX_LINES:]), encoding='utf-8')
        except OSError:
            pass


def read_local_metrics(project_name: str, device_name: str,
                       kind: str | None = None,
                       since: datetime.datetime | None = None) -> list[dict]:
    """Read local metric records, optionally filtered by kind and time."""
    path = Path(project_dir(project_name)) / device_name / LOCAL_METRICS_FILE
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind is not None and rec.get('kind') != kind:
            continue
        if since is not None:
            ts = datetime.datetime.fromisoformat(rec['ts'])
            if ts < since:
                continue
        records.append(rec)
    return records


async def write_telemetry(project_name: str, device_name: str, values: dict,
                          kind: str = 'default',
                          timestamp: datetime.datetime | None = None) -> None:
    """Write telemetry to the active backend and to the local JSONL store."""
    now = timestamp or datetime.datetime.now(datetime.timezone.utc)
    backend = _get_active_backend(project_name)
    if backend:
        await backend.write(device_name, values, kind, now)
    # _append_local_metrics does file IO — offload to thread pool to avoid blocking
    # the event loop on every telemetry push.
    await anyio.to_thread.run_sync(
        lambda: _append_local_metrics(project_name, device_name, kind, values, now)
    )


async def read_telemetry(project_name: str, device_name: str,
                         kind: str = 'default',
                         start: datetime.datetime | None = None,
                         end: datetime.datetime | None = None) -> list:
    """Read telemetry from the active backend. Returns [] if no backend is configured."""
    backend = _get_active_backend(project_name)
    if backend:
        return await backend.read(device_name, kind, start, end)
    return []
