import datetime
import re
from typing import Annotated, Literal

import niceview
from pydantic import BaseModel, Field, field_validator

from app.util import is_valid_upload_filename

# owner/name only — never a URL (SSRF guard). Letters, digits, dot, underscore, hyphen.
REPO_RE = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')

# Same charset as a plain filename, plus '*'/'?' glob wildcards for asset_name.
ASSET_NAME_RE = re.compile(r'^[A-Za-z0-9*?][A-Za-z0-9_\-.*?]*$')


def is_valid_asset_name(name: str) -> bool:
    """Filename or glob pattern ('*'/'?') safe to match against release asset names."""
    return bool(ASSET_NAME_RE.match(name)) and '..' not in name


def is_wildcard_asset_name(name: str) -> bool:
    return any(c in name for c in '*?')


class FirmwareSource(BaseModel):
    """Per-directory firmware source: a public GitHub repository whose release
    asset is pulled into this directory. Configured by an operator in the UI;
    devices can never set it. Stored as ``.firmware.json`` next to the pulled file.
    """

    repo: Annotated[str,
            Field(description='Public GitHub repository as owner/name (e.g. clausgf/nice4iot). '
                              'Not a URL. Leave empty to disable.'),
            niceview.Field()
        ] = ''

    channel: Annotated[
            Literal['stable', 'prerelease', 'pinned'],
            Field(description='Which release to track.'),
            niceview.Field(options={
                'stable': 'Stable (latest release)',
                'prerelease': 'Newest incl. prereleases',
                'pinned': 'Pinned tag',
            })
        ] = 'stable'

    pinned_tag: Annotated[str,
            Field(title='Pinned tag',
                  description='Release tag to pull when channel is "Pinned tag".'),
            niceview.Field()
        ] = ''

    asset_name: Annotated[str,
            Field(title='Asset name',
                  description='Name of the release asset to download. May contain "*"/"?" '
                              'wildcards, e.g. "firmware-*.bin" or "*.bin" to pull every matching '
                              'asset in the release (each written under its own name) — handy for a '
                              'release that ships several board-specific files side by side.'),
            niceview.Field()
        ] = 'firmware.bin'

    dest_filename: Annotated[str,
            Field(title='Destination filename',
                  description='Filename written into this directory (served to devices). '
                              'Ignored when Asset name is a wildcard pattern.'),
            niceview.Field()
        ] = 'firmware.bin'

    auto_pull_enabled: Annotated[bool,
            Field(title='Auto-pull',
                  description='Periodically check the release channel and pull a new asset automatically.'),
            niceview.Field()
        ] = False

    auto_pull_interval: Annotated[datetime.timedelta,
            Field(title='Auto-pull interval',
                  description='How often to check for a new release (floored at 5 minutes).'),
            niceview.Field()
        ] = datetime.timedelta(minutes=60)

    mqtt_publish_on_pull: Annotated[bool,
            Field(title='Publish over MQTT on pull',
                  description='After a successful pull, force-publish the file over MQTT '
                              '(device-level source only; project MQTT must be enabled).'),
            niceview.Field()
        ] = False

    updated_at: Annotated[datetime.datetime | None,
            Field(description='Timestamp of the last change (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = None

    @field_validator('repo')
    @classmethod
    def _validate_repo(cls, v: str) -> str:
        v = v.strip()
        if v and not REPO_RE.match(v):
            raise ValueError('repo must be "owner/name" (letters, digits, . _ - only) — not a URL')
        return v

    @field_validator('asset_name')
    @classmethod
    def _validate_asset_name(cls, v: str) -> str:
        v = v.strip()
        if v and not is_valid_asset_name(v):
            raise ValueError('invalid asset name')
        return v or 'firmware.bin'

    @field_validator('dest_filename')
    @classmethod
    def _validate_dest_filename(cls, v: str) -> str:
        v = v.strip()
        if v and not is_valid_upload_filename(v):
            raise ValueError('invalid filename')
        return v or 'firmware.bin'

    @property
    def asset_is_wildcard(self) -> bool:
        return is_wildcard_asset_name(self.asset_name)

    class Meta:
        description = ('Pull a firmware asset from a **public** GitHub release into the project or device directory. '
                       'The pulled file is served to devices via the normal file path (device copy '
                       'overrides the project copy).')
        profiles = {
            'settings': [
                ['repo', 'channel', 'pinned_tag'], 
                ['asset_name', 'dest_filename'],
                ['auto_pull_enabled', 'auto_pull_interval'],
                'mqtt_publish_on_pull',
            ],
        }


class FirmwareState(BaseModel):
    """Records the last successful pull for a directory, in ``.firmware.state.json``.
    Drives the "already up to date" check and the conditional (ETag) auto-pull request.
    """

    tag: str = ''
    asset: str = ''           # first/primary pulled asset name — kept for simple display
    assets: list[str] = []    # every asset name written by this pull (one entry unless
                              # asset_name is a wildcard matching more than one release asset)
    digest: str = ''          # 'sha256:...' of the pulled asset, or of all of them combined
                              # (name:digest pairs, '|'-joined, sorted by name) when there's more than one
    pulled_at: datetime.datetime | None = None
    etag: str = ''            # ETag of the release API response, for conditional polling
