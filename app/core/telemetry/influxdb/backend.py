import base64
import datetime
import time

import httpx
import asyncio

from app.core.telemetry.influxdb.models import InfluxLineConfig
from app.util import logger


class InfluxLineBackend:
    """
    InfluxDB Line Protocol telemetry backend.

    Writes device measurements to an InfluxDB-compatible endpoint.
    Measurement name: {project_name}_{kind}
    Tags: project, device
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
            if isinstance(v, bool):
                fields.append(f'{k}={str(v).lower()}')
            elif isinstance(v, int):
                fields.append(f'{k}={v}i')
            elif isinstance(v, float):
                fields.append(f'{k}={v}')
            else:
                logger.debug(f"Skipping non-numeric telemetry field '{k}' from {device_name}: {v!r}")
        if not fields:
            return None
        measurement = f'{self.project_name}_{kind}'
        tags = f'project={self.project_name},device={device_name}'
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
