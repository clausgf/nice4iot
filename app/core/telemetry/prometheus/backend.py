import base64
import datetime
import numbers
import time
import asyncio

import httpx
import pytz
import snappy
from app.config import app_config
from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.prometheus import prom_spec_pb2, types_pb2
from app.util import logger


class PrometheusBackend:
    """
    Prometheus Remote Write telemetry backend (Protobuf + Snappy).
    Compatible with Grafana Mimir, VictoriaMetrics, Thanos, and Prometheus 2.x.

    Metric names: {project_name}_{field_key}
    Labels: device, kind
    Fields ending in _total are written as COUNTER type; all others as GAUGE.
    """

    def __init__(self, project_name: str, config: PrometheusConfig = PrometheusConfig()):
        self.project_name = project_name
        self.config = config

    def _write_headers(self) -> dict[str, str]:
        headers = {
            'Content-Encoding': 'snappy',
            'Content-Type': 'application/x-protobuf',
            'User-Agent': 'nice4iot',
            'X-Prometheus-Remote-Write-Version': '0.1.0',
        }
        if self.config.username:
            credentials = base64.b64encode(
                f'{self.config.username}:{self.config.password}'.encode()
            ).decode()
            headers['Authorization'] = f'Basic {credentials}'
        return headers

    def _read_headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if self.config.username:
            credentials = base64.b64encode(
                f'{self.config.username}:{self.config.password}'.encode()
            ).decode()
            headers['Authorization'] = f'Basic {credentials}'
        return headers

    async def write(self, device_name: str, values: dict, kind: str = 'default',
                    timestamp: datetime.datetime | None = None) -> None:
        wr = prom_spec_pb2.WriteRequest()
        device_label = types_pb2.Label(name='device', value=device_name)
        kind_label = types_pb2.Label(name='kind', value=kind)
        ts_ms = round(timestamp.timestamp() * 1000) if timestamp else round(time.time() * 1000)

        for k, v in values.items():
            if not isinstance(v, numbers.Number):
                logger.debug(f"Skipping non-numeric telemetry field '{k}' from {device_name}: {v!r}")
                continue

            is_counter = k.endswith('_total')
            metric_type = (types_pb2.MetricMetadata.MetricType.COUNTER if is_counter
                           else types_pb2.MetricMetadata.MetricType.GAUGE)
            metric_name = f'{self.project_name}_{k}'

            metadata = types_pb2.MetricMetadata()
            metadata.type = metric_type
            metadata.metric_family_name = metric_name
            wr.metadata.append(metadata)

            ts = types_pb2.TimeSeries()
            ts.labels.append(types_pb2.Label(name='__name__', value=metric_name))
            ts.labels.append(device_label)
            ts.labels.append(kind_label)
            ts.samples.append(types_pb2.Sample(timestamp=ts_ms, value=v))
            wr.timeseries.append(ts)

        payload = snappy.compress(wr.SerializeToString())
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(self.config.write_timeout):
                await client.post(self.config.push_url, data=payload, headers=self._write_headers())

    async def read(self, device_name: str, kind: str = 'default',
                   start: datetime.datetime | None = None,
                   end: datetime.datetime | None = None,
                   metrics: str = '.*',
                   timeframe: datetime.timedelta | None = None,
                   step: str = '15s') -> list:
        tz = pytz.timezone(app_config.timezone)
        now = datetime.datetime.now(tz)
        query_type = 'query_range'
        if timeframe is None:
            timeframe = self.config.default_pull_timeframe

        if start is not None:
            if end is None:
                end = min(start + timeframe, now)
        else:
            if end is not None:
                start = end - timeframe
            else:
                query_type = 'query'

        if query_type == 'query_range':
            if start > end or end > now:
                raise ValueError('Invalid timeframe: start must be before end and end must not be in the future')
            start_str = start.isoformat()
            end_str = end.isoformat()
        else:
            start_str = end_str = None

        query = (f'{{__name__=~"{self.project_name}_{metrics}",'
                 f'device=~"{device_name}",kind=~"{kind}"}}&step={step}')
        if start_str and end_str:
            query += f'&start={start_str}&end={end_str}'
        query = query.replace('+', '%2B')
        query_url = f'{self.config.pull_url}{query_type}?query={query}'

        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(self.config.read_timeout):
                r = await client.get(query_url, headers=self._read_headers())
        if r.status_code == 200:
            return r.json()['data']['result']
        return []
