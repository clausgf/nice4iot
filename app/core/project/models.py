import datetime
from typing import Annotated, Any

import niceview
from pydantic import BaseModel, Field, field_validator

from app.util import FILENAME_REGEX

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


class Project(BaseModel):
    """
    A project groups devices and their configuration under a shared namespace.

    The project name doubles as the directory name on disk; device data and
    all per-project config files (forwarding, telemetry, logging) are stored
    beneath it. Devices authenticate with short-lived bearer tokens obtained
    by presenting a provisioning token.
    """

    name: Annotated[str,
            Field(min_length=1,
                  pattern=FILENAME_REGEX,
                  description='Unique project identifier. Used as the directory name on disk. '
                              'Only letters, digits, underscore, hyphen and plus are allowed.'),
            niceview.Field(editable=False)
        ] = "project"

    description: Annotated[str,
            Field(description='Human-readable description of the project.'),
            niceview.Field(widget_type='ui.textarea')
        ] = ""

    is_active: Annotated[bool,
            Field(title='Active',
                  description='Inactive projects reject all device API requests (403).')
        ] = True

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
                  description='Automatically approve newly created devices for provisioning. '
                               'Disable to require manual approval before a device can obtain a bearer token.'),
            niceview.Field()
        ] = True

    device_tokens_expire_in: Annotated[int,
            Field(default=7,
                  description='Lifetime of bearer tokens issued to devices (days). '
                              'Devices must re-provision before their token expires.'),
            niceview.Field(widget_type='ui.number')
        ]

    device_token_length: Annotated[int,
            Field(default=32,
                  description='Length of bearer tokens issued to devices during provisioning.'),
            niceview.Field(widget_type='ui.number')
        ]

    tags: Annotated[list[str],
            Field(description='Free-form labels for grouping and filtering projects.')
        ] = []

    @field_validator('device_tokens_expire_in', mode='before')
    @classmethod
    def _parse_expire_in_legacy(cls, v: Any) -> int:
        # Legacy: Pydantic v2 serialised timedelta as total seconds (float)
        if isinstance(v, float):
            return round(v) // 86400
        if isinstance(v, datetime.timedelta):
            return v.days
        return int(v)

    class Meta:
        description = (
            "General project settings."
        )
