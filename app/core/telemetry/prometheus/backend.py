import base64
import datetime
import math
import numbers
import re
import time
import asyncio

import httpx
import snappy
from app.core.telemetry.models import MetricSeries
from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.prometheus import prom_spec_pb2, types_pb2
from app.util import logger


_INVALID_METRIC_CHARS = re.compile(r'[^a-zA-Z0-9_]')


def metric_prefix(project_name: str) -> str:
    """Prometheus-safe metric-name prefix derived from the project name.

    Prometheus metric names must match ``[a-zA-Z_][a-zA-Z0-9_]*``. Project
    names are already restricted to that identifier form (see
    ``is_valid_name``), so this is defence in depth: any character outside
    ``[a-zA-Z0-9_]`` is replaced with ``_`` and a leading digit (or empty
    name) is prefixed with ``_``. Applied identically on write and read so
    the series line up.
    """
    safe = _INVALID_METRIC_CHARS.sub('_', project_name)
    if not safe or safe[0].isdigit():
        safe = '_' + safe
    return safe


def _parse_matrix(response_json: dict, project_name: str) -> list[MetricSeries]:
    """Convert a Prometheus/VictoriaMetrics query result into MetricSeries.

    Expects the instant-query-with-range-selector shape: data.result is a
    list of {"metric": {<labels>}, "values": [[<unix_ts>, "<value>"], ...]}.
    Metric names are stripped of the sanitized '<project>_' prefix added by
    write() (see metric_prefix()); the 'kind' label defaults to 'default';
    NaN samples (staleness markers) are dropped.
    """
    prefix = f'{metric_prefix(project_name)}_'
    series_list: list[MetricSeries] = []
    for item in response_json.get('data', {}).get('result', []):
        labels = item.get('metric', {})
        name = labels.get('__name__', '')
        metric = name.removeprefix(prefix)
        if not metric or metric == name:
            continue
        points: list[tuple[datetime.datetime, float]] = []
        for ts, val in item.get('values', []):
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if math.isnan(v):
                continue
            points.append((datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc), v))
        if not points:
            continue
        points.sort(key=lambda p: p[0])
        series_list.append(MetricSeries(kind=labels.get('kind', 'default'),
                                        metric=metric, points=points))
    series_list.sort(key=lambda s: (s.kind, s.metric))
    return series_list


class PrometheusBackend:
    """
    Prometheus Remote Write telemetry backend (Protobuf + Snappy).
    Compatible with Grafana Mimir, VictoriaMetrics, Thanos, and Prometheus 2.x.

    Metric names: {sanitized_project}_{field_key} (see metric_prefix())
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
        prefix = metric_prefix(self.project_name)

        for k, v in values.items():
            if not isinstance(v, numbers.Number):
                logger.debug(f"Skipping non-numeric telemetry field '{k}' from {device_name}: {v!r}")
                continue

            is_counter = k.endswith('_total')
            metric_type = (types_pb2.MetricMetadata.MetricType.COUNTER if is_counter
                           else types_pb2.MetricMetadata.MetricType.GAUGE)
            metric_name = f'{prefix}_{k}'

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
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(self.config.write_timeout):
                    resp = await client.post(self.config.push_url, data=payload,
                                             headers=self._write_headers())
            if resp.status_code >= 400:
                raise RuntimeError(f"Prometheus remote write returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Prometheus backend error for {self.project_name}: {e}")
            raise

    async def read_series(self, device_name: str,
                          start: datetime.datetime,
                          end: datetime.datetime) -> list[MetricSeries]:
        """Read raw samples for every metric of *device_name* between start and end.

        Uses an instant query with a range selector ({...}[<window>s]) rather
        than query_range: it returns the actual stored samples instead of
        step-interpolated values, matching what the local JSONL store holds.
        Works on Prometheus, VictoriaMetrics, and Mimir. The device label is
        matched exactly (device names may contain regex metacharacters like
        '+'); the project prefix in __name__ is regex-escaped for the same
        reason. Raises on HTTP errors so callers can fall back.
        """
        window_s = max(1, math.ceil((end - start).total_seconds()))
        selector = (f'{{__name__=~"{re.escape(metric_prefix(self.project_name))}_.+",'
                    f'device="{device_name}"}}[{window_s}s]')
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(self.config.read_timeout):
                r = await client.get(f'{self.config.pull_url}query',
                                     params={'query': selector, 'time': str(end.timestamp())},
                                     headers=self._read_headers())
        if r.status_code != 200:
            raise RuntimeError(f"Telemetry read returned HTTP {r.status_code}: {r.text[:200]}")
        return _parse_matrix(r.json(), self.project_name)
