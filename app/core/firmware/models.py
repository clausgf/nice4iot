import datetime
import re
from dataclasses import dataclass
from typing import Annotated, Literal

import niceview
from pydantic import BaseModel, Field, field_validator

from app.util import is_valid_upload_filename

# owner/name, or owner/group/.../name for a GitLab subgroup — never a URL
# (SSRF guard). Letters, digits, dot, underscore, hyphen per segment, at
# least one '/'.
REPO_RE = re.compile(r'^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$')

_HOST_URL_RE = re.compile(r'^https?://[A-Za-z0-9._-]+(?::\d+)?$')


class FirmwareError(Exception):
    """A firmware pull could not be completed (config, network, or integrity)."""


@dataclass
class ResolvedAsset:
    tag: str
    asset_name: str
    download_url: str  # host API's own asset URL (GitHub: 302s to an asset host; GitLab: usually direct)
    digest: str        # 'sha256:...' if the host's API provides one, else ''


class FirmwareSource(BaseModel):
    """Per-directory firmware source: a public GitHub or GitLab repository
    whose release asset is pulled into this directory. Configured by an
    operator in the UI; devices can never set it. Stored as ``.firmware.json``
    next to the pulled file.
    """

    host: Annotated[
            Literal['github', 'gitlab'],
            Field(description='Which git hosting API to resolve releases against.'),
            niceview.Field(options={'github': 'GitHub', 'gitlab': 'GitLab'})
        ] = 'github'

    host_url: Annotated[str,
            Field(title='GitLab server URL',
                  description='Base URL of a self-hosted GitLab instance, e.g. '
                              'https://gitlab.example.com. Leave empty for gitlab.com. '
                              'Ignored when host is GitHub.'),
            niceview.Field()
        ] = ''

    repo: Annotated[str,
            Field(description='Public repository as owner/name (GitHub) or '
                              'group/subgroup/.../name (GitLab). Not a URL. Leave empty to disable.'),
            niceview.Field()
        ] = ''

    channel: Annotated[
            Literal['stable', 'prerelease', 'pinned'],
            Field(description='Which release to track. GitLab has no draft/prerelease flag on a '
                              'release, so "Stable" and "Newest incl. prereleases" both resolve to '
                              'the newest release there.'),
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
                  description='Name of the release asset to download.'),
            niceview.Field()
        ] = 'firmware.bin'

    dest_filename: Annotated[str,
            Field(title='Destination filename',
                  description='Filename written into this directory (served to devices).'),
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
            raise ValueError('repo must be "owner/name" (letters, digits, . _ - only per segment) — not a URL')
        return v

    @field_validator('host_url')
    @classmethod
    def _validate_host_url(cls, v: str) -> str:
        v = v.strip().rstrip('/')
        if v and not _HOST_URL_RE.match(v):
            raise ValueError('host_url must be a bare http(s) origin, e.g. https://gitlab.example.com — no path')
        return v

    @field_validator('asset_name', 'dest_filename')
    @classmethod
    def _validate_filename(cls, v: str) -> str:
        v = v.strip()
        if v and not is_valid_upload_filename(v):
            raise ValueError('invalid filename')
        return v or 'firmware.bin'

    class Meta:
        description = ('Pull a firmware asset from a **public** GitHub or GitLab release into the '
                       'project or device directory. The pulled file is served to devices via the '
                       'normal file path (device copy overrides the project copy).')
        profiles = {
            'settings': [
                ['host', 'host_url'],
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
    asset: str = ''
    digest: str = ''          # 'sha256:...' of the pulled asset
    pulled_at: datetime.datetime | None = None
    etag: str = ''            # ETag of the release API response, for conditional polling
