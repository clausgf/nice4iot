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

    is_active: Annotated[bool,
            Field(description='Whether the rule is active.'),
            niceview.Field(label='', tooltip='Whether the *metric alarm* rule is active or not.')
        ] = True

    name: Annotated[str,
            Field(description='Unique rule name within the project.'),
            niceview.Field()
        ] = 'rule'

    kind: Annotated[str,
            Field(description='Telemetry kind to watch.'),
            niceview.Field(widget_type='ui.select', with_input=True, new_value_mode='add-unique')
        ] = 'sensors'

    metric: Annotated[str,
            Field(description='Metric name within the payload.'),
            niceview.Field(widget_type='ui.select', with_input=True, new_value_mode='add-unique')
        ] = 'temperature'

    comparison: Annotated[Literal['<', '=', '>'],
            Field(description='Comparison operator compares metric value to threshold.'),
            niceview.Field()
        ] = '<'

    threshold: Annotated[float,
            Field(description='Alarm fires when the comparison evaluates to True.'),
            niceview.Field(widget_type='ui.number')
        ] = 0.0


class DeviceOfflineAlarm(BaseModel):
    """Built-in rule: fire when a device has not been seen within the online threshold."""

    is_active: Annotated[bool,
            Field(description='Whether the rule is active.'),
            niceview.Field(label='', tooltip='Whether the *device offline* alarm is active or not.')
        ] = True

    name: Annotated[str,
            Field(description='Fixed rule name.'),
            niceview.Field(editable=False)
        ] = 'device_offline'

    device_offline_threshold: Annotated[datetime.timedelta,
            Field(title='Offline threshold',
                  description='Time since last contact after which the device offline alarm fires. '
                              'Set to match the expected telemetry or keep-alive interval.'),
            niceview.Field()
        ] = datetime.timedelta(days=1)


class ProvisioningTokenExpiryAlarm(BaseModel):
    """Built-in rule: fire when a provisioning token is about to expire (for tokens that have been used to provision a device)."""

    is_active: Annotated[bool,
            Field(description='Whether the rule is active.'),
            niceview.Field(label='', tooltip='Whether the *provisioning token expiring* alarm is active or not.')
        ] = True

    name: Annotated[str,
            Field(description='Fixed rule name.'),
            niceview.Field(editable=False)
        ] = 'provisioning_expiry'

    token_expiration_threshold: Annotated[datetime.timedelta,
            Field(title='Alarm time before provisioning token expiry',
                  description='Time delta before the expiration of the provisioning '
                              'token to fire the alarm.'),
            niceview.Field()
        ] = datetime.timedelta(days=7)

    only_tokens_in_active_use: Annotated[bool,
            Field(title='Only tokens in active use',
                  description='Only fire the alarm for provisioning tokens that have been used '
                              'to provision a device.'),
            niceview.Field()
        ] = True

    class Meta:
        profiles = {
            'default': ['is_active:shrink', 'name', 'token_expiration_threshold', 'only_tokens_in_active_use']
        }


class AlarmConfig(BaseModel):
    """Per-project alarm configuration stored in .alarm_config.json."""

    updated_at: datetime.datetime | None = None

    device_offline: DeviceOfflineAlarm = Field(default_factory=DeviceOfflineAlarm)
    provisioning_expiry: ProvisioningTokenExpiryAlarm = Field(default_factory=ProvisioningTokenExpiryAlarm)

    rules: list[MetricAlarmRule] = []


def _short_id() -> str:
    return str(uuid.uuid4()).replace('-', '')[:12]


class AlarmEvent(BaseModel):
    """
    Stateful alarms.

    Identified by (rule_name, device_name); at most one event per pair.
    Lifecycle: triggered → is_active=True → condition clears → is_active=False
               → user acknowledges → is_acknowledged=True.
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
