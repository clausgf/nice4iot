import base64
import datetime
import time

import httpx
import asyncio

from app.core.telemetry.influxdb.models import InfluxLineConfig
from app.util import logger


def _escape_measurement(value: str) -> str:
    """Escape a line-protocol measurement name (commas and spaces)."""
    return value.replace(',', r'\,').replace(' ', r'\ ')


def _escape_tag(value: str) -> str:
    """Escape a line-protocol tag key/value or field key (comma, equals, space).

    Applies to project/device names and field keys so that names containing
    line-protocol delimiters cannot break out of their token. Current name
    validation forbids these characters, so this is defence in depth.
    """
    return value.replace(',', r'\,').replace('=', r'\=').replace(' ', r'\ ')


class InfluxLineBackend:
    """
    InfluxDB Line Protocol telemetry backend.

    Data model, kept parallel to the Prometheus backend so the same payload
    looks structurally the same across backends:

        measurement = <project>          # namespace, like the Prometheus name prefix
        tags        = device, kind       # dimensions, like Prometheus labels
        fields      = the numeric values # the measured quantities

    e.g. ``weatherstation,device=sensor_garden,kind=sensors temperature=22.4,humidity=60 <ns>``.
    project is the namespace (a deliberate trade-off — see docs/architecture.md);
    device and kind are dimensions. Unlike Prometheus, one point carries all of a
    kind's fields together.
    """

    def __init__(self, project_name: str, config: InfluxLineConfig = InfluxLineConfig()):
        self.project_name = project_name
        self.config = config

    def _build_url(self) -> str:
        params = ['precision=ns']
        if self.config.database:
            params.append(f'db={self.config.database}')
        if self.config.bucket:
            params.append(f'bucket={self.config.bucket}')
        if self.config.org:
            params.append(f'org={self.config.org}')
        return self.config.write_url + '?' + '&'.join(params)

    def _build_headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'text/plain; charset=utf-8'}
        if self.config.token:
            headers['Authorization'] = f'Token {self.config.token}'
        elif self.config.username:
            credentials = base64.b64encode(
                f'{self.config.username}:{self.config.password}'.encode()
            ).decode()
            headers['Authorization'] = f'Basic {credentials}'
        return headers

    def _build_line(self, device_name: str, values: dict, kind: str, timestamp_ns: int) -> str | None:
        fields = []
        for k, v in values.items():
            ek = _escape_tag(k)
            if isinstance(v, bool):
                fields.append(f'{ek}={str(v).lower()}')
            elif isinstance(v, int):
                fields.append(f'{ek}={v}i')
            elif isinstance(v, float):
                fields.append(f'{ek}={v}')
            else:
                logger.debug(f"Skipping non-numeric telemetry field '{k}' from {device_name}: {v!r}")
        if not fields:
            return None
        # measurement = project (namespace); device and kind are tags (dimensions),
        # parallel to the Prometheus name-prefix + labels. No separate project tag:
        # project is already the measurement.
        measurement = _escape_measurement(self.project_name)
        tags = f'device={_escape_tag(device_name)},kind={_escape_tag(kind)}'
        return f'{measurement},{tags} {",".join(fields)} {timestamp_ns}'

    async def write(self, device_name: str, values: dict, kind: str = 'default',
                    timestamp: datetime.datetime | None = None) -> None:
        timestamp_ns = int(timestamp.timestamp() * 1e9) if timestamp else time.time_ns()
        line = self._build_line(device_name, values, kind, timestamp_ns)
        if not line:
            return
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(self.config.timeout):
                    resp = await client.post(self._build_url(), content=line.encode(),
                                             headers=self._build_headers())
            if resp.status_code >= 400:
                raise RuntimeError(f"InfluxDB returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"InfluxDB backend error for {self.project_name}: {e}")
            raise

    async def read_series(self, device_name: str,
                          start: datetime.datetime,
                          end: datetime.datetime) -> list:
        # No read path: VictoriaMetrics & friends are read via the Prometheus
        # backend; a genuine InfluxDB read would need InfluxQL (1.x) or Flux
        # (2.x). Raising here makes read_series() fall back to the local store.
        raise NotImplementedError("Read not implemented for the InfluxDB Line Protocol backend.")
