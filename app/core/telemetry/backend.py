import datetime
import json
import numbers
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.paths import project_dir
from app.core.telemetry.models import TelemetryBackend, TelemetryConfig
from app.core.telemetry.prometheus.backend import PrometheusBackend
from app.core.telemetry.influxdb.backend import InfluxLineBackend

TEL_FILE = '.telemetry.json'
LOCAL_METRICS_FILE = '.device_metrics.jsonl'
LOCAL_METRICS_MAX_LINES = 2000


def get_telemetry_adapter(project_name: str) -> JsonAdapter:
    """Get a JsonAdapter for the telemetry configuration of a project."""
    return JsonAdapter(TelemetryConfig, project_dir(project_name) / TEL_FILE, create_if_not_exist=True)


def _get_active_backend(project_name: str) -> TelemetryBackend | None:
    config = get_telemetry_adapter(project_name).read()
    if config.backend == 'prometheus':
        return PrometheusBackend(project_name, config.prometheus)
    if config.backend == 'influxdb':
        return InfluxLineBackend(project_name, config.influxdb)
    return None


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
    # Keep at most LOCAL_METRICS_MAX_LINES lines (trim oldest when over limit).
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
    _append_local_metrics(project_name, device_name, kind, values, now)


async def read_telemetry(project_name: str, device_name: str,
                         kind: str = 'default',
                         start: datetime.datetime | None = None,
                         end: datetime.datetime | None = None) -> list:
    """Read telemetry from the active backend. Returns [] if no backend is configured."""
    backend = _get_active_backend(project_name)
    if backend:
        return await backend.read(device_name, kind, start, end)
    return []
