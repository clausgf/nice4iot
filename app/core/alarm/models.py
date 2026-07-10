"""
Alarm models.

AlarmConfig  — per-project configuration (rules + built-in thresholds).
AlarmEvent   — one stateful alarm occurrence per (project, device, rule).
"""
import datetime
import uuid
from typing import Annotated, Literal

import niceview
from pydantic import BaseModel, Field


class MetricAlarmRule(BaseModel):
    """A configurable rule that fires when a telemetry metric crosses a threshold."""

    name: Annotated[str,
            Field(description='Unique rule name within the project.'),
            niceview.Field()
        ] = 'rule'

    is_active: Annotated[bool,
            Field(title='Active'),
            niceview.Field()
        ] = True

    kind: Annotated[str,
            Field(description='Telemetry kind to watch, e.g. "sensors" or "system".'),
            niceview.Field()
        ] = 'sensors'

    metric: Annotated[str,
            Field(description='Metric name within the payload, e.g. "temperature".'),
            niceview.Field()
        ] = 'temperature'

    comparison: Annotated[Literal['<', '=', '>'],
            Field(description='Comparison operator applied to the metric value.'),
            niceview.Field()
        ] = '<'

    threshold: Annotated[float,
            Field(description='Threshold value. Alarm fires when metric comparison threshold is True.'),
            niceview.Field(widget_type='ui.number')
        ] = 0.0

    description: Annotated[str,
            Field(description='Human-readable description shown in alarm notifications.'),
            niceview.Field()
        ] = ''


class DeviceUnavailableConfig(BaseModel):
    """Built-in rule: fire when a device has not been seen for longer than threshold_s."""

    is_active: Annotated[bool,
            Field(title='Device unavailable alarm active'),
            niceview.Field()
        ] = True

    threshold_s: Annotated[int,
            Field(default=0,
                  title='Unavailability threshold (s)',
                  description='Seconds without contact before alarm fires. '
                              '0 = use the project-level online threshold.'),
            niceview.Field(widget_type='ui.number')
        ]


class AlarmConfig(BaseModel):
    """Per-project alarm configuration stored in .alarm_config.json."""

    updated_at: datetime.datetime | None = None

    device_unavailable: DeviceUnavailableConfig = Field(
        default_factory=DeviceUnavailableConfig
    )

    rules: list[MetricAlarmRule] = []


def _short_id() -> str:
    return str(uuid.uuid4()).replace('-', '')[:12]


class AlarmEvent(BaseModel):
    """
    One stateful alarm occurrence.

    Identified by (rule_name, device_name); at most one event per pair.
    Lifecycle: triggered → active=True → condition clears → active=False
               → user acknowledges → acknowledged=True.
    Events are removed from the event file only when inactive AND acknowledged.
    """

    id: str = Field(default_factory=_short_id)
    rule_name: str
    device_name: str
    triggered_at: datetime.datetime
    last_seen_at: datetime.datetime
    last_value: float | None = None
    message: str = ''
    is_active: bool = True
    is_acknowledged: bool = False
    acknowledged_at: datetime.datetime | None = None
