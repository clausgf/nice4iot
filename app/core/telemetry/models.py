import datetime
from typing import Annotated, Literal, Protocol
from pydantic import BaseModel, Field
import niceview

from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.influxdb.models import InfluxLineConfig


class TelemetryBackend(Protocol):
    async def write(self, device_name: str, values: dict, kind: str,
                    timestamp: datetime.datetime | None) -> None: ...

    async def read(self, device_name: str, kind: str,
                   start: datetime.datetime | None,
                   end: datetime.datetime | None) -> list: ...


class TelemetryConfig(BaseModel):
    """Per-project telemetry configuration. Exactly one backend is active at a time."""
    updated_at: Annotated[
            datetime.datetime,
            Field(description='Timestamp of the last configuration change (UTC, set automatically).'),
            niceview.Field(editable=False),
        ] = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
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
