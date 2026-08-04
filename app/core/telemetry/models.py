import dataclasses
import datetime
from typing import Annotated, Literal, Protocol
from pydantic import BaseModel, Field
import niceview

from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.influxdb.models import InfluxLineConfig

# Name of the synthetic info series that carries a write's string labels, following
# the OpenMetrics `target_info` convention: Prometheus emits `<project>_target_info`,
# InfluxDB the measurement `<project>_target_info`. Reserved as a numeric metric key
# (a numeric field of this name is dropped) to avoid colliding with the info series.
INFO_METRIC_KEY = 'target_info'


@dataclasses.dataclass
class MetricSeries:
    """One time series of a single metric, normalized across telemetry sources.

    Produced by both the local JSONL store and remote backend reads so the
    Data tab renders identically regardless of source — see
    app.core.telemetry.backend.read_series().
    """
    kind: str
    metric: str
    points: list[tuple[datetime.datetime, float]]  # ascending by timestamp


class DataTrace(BaseModel):
    """One trace in the Data-tab explorer: a colour plus a kind/metric selection."""
    color: str = 'Blue'
    kind: str | None = None
    metric: str | None = None


class DataView(BaseModel):
    """Persisted Data-tab explorer configuration, per device (``.data_view.json``)."""
    window: str = 'Last 24 h'
    traces: list[DataTrace] = Field(default_factory=lambda: [DataTrace()])
    marker_labels: list[str] = Field(default_factory=list)  # label keys shown as chart markers


class TelemetryBackend(Protocol):
    async def write(self, device_name: str, values: dict, kind: str,
                    timestamp: datetime.datetime | None,
                    labels: dict | None = None) -> None: ...

    async def read_series(self, device_name: str,
                          start: datetime.datetime,
                          end: datetime.datetime) -> list[MetricSeries]: ...


class TelemetryConfig(BaseModel):
    """Per-project telemetry configuration. Exactly one backend is active at a time."""
    updated_at: Annotated[
            datetime.datetime | None,
            Field(description='Timestamp of the last configuration change (UTC, set automatically).'),
            niceview.Field(editable=False),
        ] = None
    backend: Annotated[
        Literal['none', 'prometheus', 'influxdb'],
        niceview.Field(options={
            'none': 'Disabled',
            'prometheus': 'Prometheus / Mimir / VictoriaMetrics',
            'influxdb': 'InfluxDB Line Protocol',
        })
    ] = 'none'
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)
    influxdb: InfluxLineConfig = Field(default_factory=InfluxLineConfig)

    class Meta:
        description = (
            "Configures where device telemetry is sent. "
            "Exactly one backend is active at a time; "
            "switching backends preserves each backend's last configuration."
        )
