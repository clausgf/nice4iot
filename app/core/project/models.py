import datetime
from typing import Annotated, Any

import niceview
from pydantic import BaseModel, Field, field_validator

from app.util import NAME_REGEX

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


class Project(BaseModel):
    """
    A project groups devices and their configuration under a shared namespace.

    The project name doubles as the directory name on disk; device data and
    all per-project config files (forwarding, telemetry, logging) are stored
    beneath it. Devices authenticate with short-lived bearer tokens obtained
    by presenting a provisioning token.
    """

    is_active: Annotated[bool,
            Field(description='Inactive projects are rejected: provisioning returns 403; '
                              'device API requests return 401 (all auth failures are normalised to 401).'),
            niceview.Field(label='', tooltip='Whether the project is active or not.')
        ] = True

    name: Annotated[str,
            Field(min_length=1,
                  pattern=NAME_REGEX,
                  description='Unique project identifier. Used as the directory name on disk and '
                              'as the telemetry metric-name prefix. Letters, digits and underscore only. '
                              'Must not start with a digit.'),
            niceview.Field(editable=False)
        ] = "project"

    description: Annotated[str,
            Field(description='Human-readable description of the project.'),
            niceview.Field(widget_type='ui.textarea')
        ] = ""

    owner: Annotated[str,
            Field(description='Owner or responsible person for this project.')
        ] = ""  # not shown in the project form

    created_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the project was created (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]

    updated_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp of the last configuration change (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]

    is_autocreate_devices: Annotated[bool,
            Field(title='Auto-create devices',
                  description='Automatically create a device record on the first provisioning request '
                               'if no record exists yet. Disable to require manual device registration.'),
            niceview.Field()
        ] = True

    is_provisioning_autoapproval: Annotated[bool,
            Field(title='Auto-approve provisioning',
                  description='Automatically approve newly created devices for provisioning '
                               '(HTTP only — MQTT autocreate uses is_autocreate_devices). '
                               'Disable to require manual approval before a device can obtain a bearer token.'),
            niceview.Field()
        ] = True

    is_http_enabled: Annotated[bool,
            Field(title='HTTP API enabled',
                  description='Enable REST API access for devices in this project. '
                              'Disable to prevent all HTTP device requests (telemetry, log, file, forward).')
        ] = True

    is_mqtt_enabled: Annotated[bool,
            Field(title='MQTT enabled',
                  description='Enable MQTT for devices in this project.')
        ] = False

    mqtt_topic_base: Annotated[str,
            Field(title='MQTT topic base',
                  description='Topic prefix for this project. Use {project} and {device} as placeholders. '
                              'Example: /nice4iot/{project}/{device}  →  nice4iot/myproject/sensor1/telemetry/sensors. '
                              'Leading slashes and double slashes are normalized automatically.')
        ] = '/nice4iot/{project}/{device}'

    device_tokens_expire_in: Annotated[datetime.timedelta,
            Field(default=datetime.timedelta(days=7),
                  description='Lifetime of bearer tokens issued to devices (days). '
                              'Devices must re-provision before their token expires.'),
        ]

    device_token_length: Annotated[int,
            Field(default=32,
                  description='Length of bearer tokens issued to devices during provisioning.'),
            niceview.Field(widget_type='ui.number')
        ]

    tags: Annotated[list[str],
            Field(description='Free-form labels for grouping and filtering projects.')
        ] = []

    enabled_extensions: Annotated[list[str],
            Field(description='Names of installed extensions active for this project. '
                               'Disabled (absent) by default; edited via the Extensions card.')
        ] = []  # not shown in the general form; niceview.Field() intentionally omitted

    @field_validator('device_tokens_expire_in', mode='before')
    @classmethod
    def _parse_expire_in_legacy(cls, v: Any) -> Any:
        # Normalise legacy numeric encodings to a timedelta. A bare number returned
        # here would be read as seconds, so build the timedelta explicitly:
        #   * the original int field held whole days (7 -> 7 days);
        #   * pydantic v2 later serialised the timedelta as float total-seconds.
        # timedelta instances and ISO 8601 strings pass through to pydantic unchanged.
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return datetime.timedelta(days=v)
        if isinstance(v, float):
            return datetime.timedelta(seconds=v)
        return v

