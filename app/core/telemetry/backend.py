import datetime
import json
import numbers
import re
import time

import anyio
from niceview.dataadapter import JsonAdapter

from app.paths import project_dir, device_dir
from app.util import logger, is_valid_name
from app.core.telemetry.models import MetricSeries, TelemetryBackend, TelemetryConfig
from app.core.telemetry.prometheus.backend import PrometheusBackend
from app.core.telemetry.influxdb.backend import InfluxLineBackend

TEL_FILE = '.telemetry.json'
LOCAL_METRICS_FILE = '.device_metrics.jsonl'
LOCAL_METRICS_MAX_LINES = 2000
_TRIM_EVERY_N = 10  # trim JSONL only every N writes to amortise O(n) read cost

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
    path = device_dir(project_name, device_name) / LOCAL_METRICS_FILE
    if not path.parent.is_dir():
        return  # device directory not yet created via create_device()
    record = json.dumps({'ts': timestamp.isoformat(), 'kind': kind, 'v': numeric}) + '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(record)
    # Trim to LOCAL_METRICS_MAX_LINES only every _TRIM_EVERY_N writes.
    # Reading the full file on every append is O(n) per telemetry push; this
    # amortises the cost to O(n / _TRIM_EVERY_N) on average.
    # Key uses the full path so tests using different temp dirs don't share state.
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
    path = device_dir(project_name, device_name) / LOCAL_METRICS_FILE
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
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts < since:
                continue
        records.append(rec)
    return records


def observed_metrics(project_name: str) -> dict[str, list[str]]:
    """Collect the metric names seen in the local store, grouped by kind.

    Returns {kind: sorted metric names} aggregated across every device of the
    project, so alarm-rule editors can offer the actual (normalized) metric
    names. Blocking file IO — callers in an async context must wrap this with
    ``anyio.to_thread.run_sync`` per the async-IO rule.
    """
    base = project_dir(project_name)
    if not base.is_dir():
        return {}
    grouped: dict[str, set[str]] = {}
    for device_path in base.iterdir():
        if not device_path.is_dir() or not is_valid_name(device_path.name):
            continue
        for rec in read_local_metrics(project_name, device_path.name):
            kind = rec.get('kind')
            if kind:
                grouped.setdefault(kind, set()).update(rec.get('v', {}).keys())
    return {k: sorted(v) for k, v in sorted(grouped.items())}


def _evaluate_alarms(project_name: str, device_name: str, kind: str, values: dict) -> None:
    """Evaluate metric alarm rules — called from write_telemetry via thread pool."""
    try:
        from app.core.alarm.backend import evaluate_metric_rules
        evaluate_metric_rules(project_name, device_name, kind, values)
    except Exception as e:
        logger.error(f"Alarm evaluation error for {project_name}/{device_name}: {e}")


def flatten_metrics(values: dict, parent_key: str = '', sep: str = '_') -> dict:
    """Flatten nested JSON objects into single-level keys joined by *sep*.

    ``{"a": {"b": 1}}`` becomes ``{"a_b": 1}``; nesting of any depth is
    supported. Leaf values are passed through unchanged — numeric filtering
    happens downstream in each backend and the local store — so non-dict
    leaves (numbers, strings, lists) keep their flattened key. Empty nested
    objects contribute no keys.
    """
    flat: dict = {}
    for key, value in values.items():
        new_key = f'{parent_key}{sep}{key}' if parent_key else str(key)
        if isinstance(value, dict):
            flat.update(flatten_metrics(value, new_key, sep))
        else:
            flat[new_key] = value
    return flat


_INVALID_METRIC_CHARS = re.compile(r'[^a-zA-Z0-9_]')


def sanitize_metric_name(name: str) -> str:
    """Make a metric name compatible with every supported telemetry backend.

    Prometheus metric names must match ``[a-zA-Z_][a-zA-Z0-9_]*``; InfluxDB
    line-protocol field keys must not contain unescaped spaces, commas or
    ``=``. The common safe set is ``[a-zA-Z0-9_]``, so every other character
    (dots, dashes, spaces, unicode, ...) is replaced with ``_``. A name that
    is empty (or all-invalid) collapses to a single ``_``. The Prometheus
    backend always prefixes the project name, so a leading digit here still
    yields a valid ``<project>_<name>`` series.
    """
    return _INVALID_METRIC_CHARS.sub('_', name) or '_'


def normalize_metrics(values: dict) -> dict:
    """Flatten nested objects and sanitize every resulting key.

    ``{"a.b": {"c d": 1}}`` becomes ``{"a_b_c_d": 1}``. This is the single
    choke point through which every telemetry payload passes so that all
    backends, the local store, and alarm rules see identical, backend-safe
    metric names. Distinct source keys that sanitize to the same name collide;
    the last one wins (an accepted, documented edge case).
    """
    return {sanitize_metric_name(k): v for k, v in flatten_metrics(values).items()}


async def write_telemetry(project_name: str, device_name: str, values: dict,
                          kind: str = 'default',
                          timestamp: datetime.datetime | None = None) -> None:
    """Write telemetry to the active backend and to the local JSONL store.

    Metric names in *values* are normalized before any backend, the local
    store, or alarm rules see them: nested JSON objects are flattened to
    underscore-joined keys (``a.b`` → ``a_b``) and every character is
    sanitized to the ``[a-zA-Z0-9_]`` set common to all backends, so metric
    names stay flat and backend-compatible everywhere.
    """
    values = normalize_metrics(values)
    now = timestamp or datetime.datetime.now(datetime.timezone.utc)
    backend = _get_active_backend(project_name)
    if backend:
        try:
            await backend.write(device_name, values, kind, now)
            from app.health import set_health
            set_health(f'{project_name}:telemetry', True)
        except Exception as e:
            from app.health import set_health
            set_health(f'{project_name}:telemetry', False, str(e))
    # _append_local_metrics and alarm evaluation do file IO — offload to thread pool.
    await anyio.to_thread.run_sync(
        lambda: _append_local_metrics(project_name, device_name, kind, values, now)
    )
    await anyio.to_thread.run_sync(
        lambda: _evaluate_alarms(project_name, device_name, kind, values)
    )


_REMOTE_ALL_WINDOW = datetime.timedelta(days=30)  # 'All' cap for remote reads


def _local_series(project_name: str, device_name: str,
                  since: datetime.datetime | None) -> list[MetricSeries]:
    """Group local JSONL records into MetricSeries (one per kind/metric pair)."""
    grouped: dict[tuple[str, str], list[tuple[datetime.datetime, float]]] = {}
    for rec in read_local_metrics(project_name, device_name, since=since):
        ts = datetime.datetime.fromisoformat(rec['ts'])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        for metric, value in rec['v'].items():
            try:
                grouped.setdefault((rec['kind'], metric), []).append((ts, float(value)))
            except (TypeError, ValueError):
                continue
    series = [MetricSeries(kind=k, metric=m, points=sorted(pts))
              for (k, m), pts in grouped.items()]
    series.sort(key=lambda s: (s.kind, s.metric))
    return series


async def read_series(project_name: str, device_name: str,
                      since: datetime.datetime | None) -> tuple[list[MetricSeries], str]:
    """Read all metric series for a device, preferring the configured backend.

    Returns (series, source): source is the backend name (e.g. 'prometheus')
    or 'local' when no backend is configured or the backend read failed —
    including backends without a read path (InfluxDB line protocol raises
    NotImplementedError). since=None means everything locally, but is capped
    to the last _REMOTE_ALL_WINDOW remotely (remote queries need a bounded
    window).
    """
    backend = _get_active_backend(project_name)
    if backend is not None:
        end = datetime.datetime.now(datetime.timezone.utc)
        start = since or (end - _REMOTE_ALL_WINDOW)
        try:
            series = await backend.read_series(device_name, start, end)
            return series, type(backend).__name__.removesuffix('Backend').lower()
        except Exception as e:
            logger.error(f"Telemetry read from backend failed for "
                         f"{project_name}/{device_name}, falling back to local store: {e}")
    series = await anyio.to_thread.run_sync(
        lambda: _local_series(project_name, device_name, since))
    return series, 'local'
