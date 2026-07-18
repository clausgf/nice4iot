import dataclasses
import datetime
from typing import Annotated, Literal, Protocol
from pydantic import BaseModel, Field
import niceview

from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.influxdb.models import InfluxLineConfig


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


class TelemetryBackend(Protocol):
    async def write(self, device_name: str, values: dict, kind: str,
                    timestamp: datetime.datetime | None) -> None: ...

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
        niceview.Field(select_options={
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
