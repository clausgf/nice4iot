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

    is_active: Annotated[bool,
            Field(description='Inactive devices are rejected: provisioning returns 403; '
                              'device API calls return 401 (all auth failures are normalised to 401).'),
            niceview.Field(label='', tooltip='Whether the device is active or not.')
        ] = True

    name: Annotated[str, 
            Field(description='Unique device identifier within the project. Used as the directory name on disk. '
                    'Letters, digits and underscore only. Must not start with a digit.',
                min_length=1,
                pattern=NAME_REGEX),
            niceview.Field(editable=False)
        ] = "device"

    description: Annotated[str,
            Field(description='Human-readable description of this device.'),
            niceview.Field(widget_type='ui.textarea')
        ] = ""

    location: Annotated[str,
            Field(description='Physical location or installation site of the device (free text).')
        ] = ""

    project_name: Annotated[str,
            Field(min_length=1,
                  description='Name of the project this device belongs to. Set at creation time.'),
            niceview.Field(editable=False)
        ]

    created_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Device record creation timestamp (UTC, set automatically).'),
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

    last_provisioning_token_fingerprint: Annotated[str,
            Field(default='',
                  description='Short SHA-256 fingerprint of the provisioning token this device '
                              'last used successfully. Identifies the token (matched against the '
                              'fingerprint shown in the project provisioning-token list) without '
                              'storing the shared secret.'),
            niceview.Field(editable=False)
        ] = ''

    last_provisioning_token_expires_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Expiry of the provisioning token this device last used (UTC). '
                              'Filter devices by this to find which are affected by a soon-expiring '
                              'provisioning token, even after the token itself has been removed.'),
            niceview.Field(editable=False)
        ] = None

    firmware_version: Annotated[str,
            Field(default='',
                  description='Firmware version the device last reported (via the X-Firmware-Version '
                              'header on authenticated API requests, or at provisioning). '),
            niceview.Field(editable=False)
        ] = ''

    firmware_reported_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp when the device last reported its firmware version (UTC).'),
            niceview.Field(editable=False)
        ] = None

    tags: Annotated[list[str],
            Field(description='Free-form labels for grouping and filtering devices.'),
            niceview.Field()
        ] = []

    # Plain property, not a pydantic field: a live query against the alarm
    # backend (project_name/name identify the device), not stored device
    # state -- so it can't live on DeviceRuntime, which carries neither.
    @property
    def active_alarms(self) -> int:
        """Count of this device's active, unacknowledged alarms."""
        from app.core.alarm.backend import get_alarm_count
        return get_alarm_count(self.project_name, self.name)


class DeviceRuntime(BaseModel):
    """Device-reported runtime state, persisted in ``.runtime.json`` next to the
    device directory.

    Kept separate from ``device.json`` on purpose: these fields change on every
    authenticated request (last_seen) or firmware report, and writing them into
    ``device.json`` — managed by the UI's optimistic-locked autosave adapter —
    would cause lock conflicts. ``get_device()`` loads this sidecar and copies the
    values onto the in-memory :class:`Device`.
    """

    last_seen_at: datetime.datetime | None = None
    firmware_version: str = ''
    firmware_reported_at: datetime.datetime | None = None

    # Snapshot of the device's most recent *system* telemetry push (kind ==
    # 'system'): the numeric measurements (battery_V, wifi_rssi, ...) and the
    # string labels (firmware_id, firmware_sha256, ...) of that single write,
    # cached here for O(1) access (e.g. a device table) instead of scanning the
    # per-device metrics JSONL. Replaced wholesale on each system push, so they
    # reflect exactly the last write — a field a push omits (e.g. battery_V on a
    # device without a battery pin) is absent, not stale.
    system_metrics: dict[str, float] = {}
    system_labels: dict[str, str] = {}
    system_reported_at: datetime.datetime | None = None

    # Convenience accessors over system_metrics/system_labels for the handful of
    # well-known keys arduino4iot's system push reports. Plain properties, not
    # pydantic fields/computed_fields, so they stay derived-only and never get
    # persisted into .runtime.json themselves. None/'' when the last push omitted
    # the key (see the system_metrics/system_labels comment above).
    @property
    def battery_voltage(self) -> float | None:
        return self.system_metrics.get('battery_V')

    @property
    def rssi(self) -> float | None:
        return self.system_metrics.get('wifi_rssi')

    @property
    def firmware_id(self) -> str:
        return self.system_labels.get('firmware_id', '')

    @property
    def board(self) -> str:
        return self.system_labels.get('board', '')
