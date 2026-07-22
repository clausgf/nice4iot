import datetime
from typing import Annotated

import niceview
from pydantic import BaseModel, Field

from app.util import NAME_REGEX

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


class Device(BaseModel):
    """
    A device represents a physical IoT node within a project.

    The device name doubles as the directory name beneath the project directory.
    Devices authenticate with short-lived bearer tokens obtained via the provisioning
    endpoint. Each device keeps its own token list so multiple firmware instances
    (e.g. after a reboot) can coexist until old tokens expire.
    """

    name: str = Field(
        min_length=1,
        pattern=NAME_REGEX,
        description='Unique device identifier within the project. Used as the directory name on disk. '
                    'Must be a valid identifier: letters, digits and underscore only, '
                    'and must not start with a digit.')

    description: Annotated[str,
            Field(description='Human-readable description of this device.'),
            niceview.Field(widget_type='ui.textarea')
        ] = ""

    is_active: Annotated[bool,
            Field(title='Active',
                  description='Inactive devices are rejected: provisioning returns 403; '
                              'device API calls return 401 (all auth failures are normalised to 401).')
        ] = True

    location: Annotated[str,
            Field(description='Physical location or installation site of the device (free text).')
        ] = ""

    project_name: Annotated[str,
            Field(min_length=1,
                  description='Name of the project this device belongs to. '
                               'Set at creation time. The project determindes the parent directory of the device directory.'),
            niceview.Field(editable=False)
        ]

    created_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the device record was created (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]

    updated_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp of the last change to this device record (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]

    last_seen_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp of the last successful authenticated API request (UTC).'),
            niceview.Field(editable=False)
        ] = None

    is_provisioning_approved: Annotated[bool,
            Field(title='Provisioning Approved',
                  description='Whether this device is allowed to obtain bearer tokens. '
                               'Set automatically if auto-approval is enabled on the project, '
                               'otherwise requires manual activation.')
        ] = False

    last_provisioning_request_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp of the last provisioning attempt, '
                               'regardless of whether it succeeded (UTC).'),
            niceview.Field(editable=False)
        ] = None

    last_provisioned_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp of the last successful provisioning (UTC).'),
            niceview.Field(editable=False)
        ] = None

    tags: Annotated[list[str],
            Field(description='Free-form labels for grouping and filtering devices.'),
            niceview.Field()
        ] = []

    class Meta:
        description = (
            "Device settings and provisioning state. "
            "The device name is the filesystem key and cannot be changed without renaming the directory."
        )
