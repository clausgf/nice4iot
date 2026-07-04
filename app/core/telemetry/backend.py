import datetime

from niceview.dataadapter import JsonAdapter

from app.paths import project_dir
from app.core.telemetry.models import TelemetryBackend, TelemetryConfig
from app.core.telemetry.prometheus.backend import PrometheusBackend
from app.core.telemetry.influxdb.backend import InfluxLineBackend

TEL_FILE = '.telemetry.json'


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


async def write_telemetry(project_name: str, device_name: str, values: dict,
                          kind: str = 'default',
                          timestamp: datetime.datetime | None = None) -> None:
    """Write telemetry to the active backend. No-op if no backend is configured."""
    backend = _get_active_backend(project_name)
    if backend:
        await backend.write(device_name, values, kind, timestamp)


async def read_telemetry(project_name: str, device_name: str,
                         kind: str = 'default',
                         start: datetime.datetime | None = None,
                         end: datetime.datetime | None = None) -> list:
    """Read telemetry from the active backend. Returns [] if no backend is configured."""
    backend = _get_active_backend(project_name)
    if backend:
        return await backend.read(device_name, kind, start, end)
    return []
