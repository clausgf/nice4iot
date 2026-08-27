"""GitLab REST API (v4) backend for firmware release resolution. Dispatched
to by app/core/firmware/backend.py's host-agnostic orchestration alongside
github.py — differences from GitHub that shape this module:

- No "latest release" endpoint: list releases ordered by released_at and
  take the first. GitLab also has no draft/prerelease flag on a release, so
  'stable' and 'prerelease' both just mean "newest release" here — kept as a
  real config choice anyway so a source reads the same regardless of host.
- Release assets are `assets.links[]`, each an arbitrary named URL — not
  necessarily hosted on the GitLab instance itself (a release link can point
  anywhere). The download-host allowlist is therefore the *configured*
  GitLab host only, unlike GitHub's fixed asset-CDN list — a link pointing
  off-instance is refused.
- No asset digest in the API response, so ResolvedAsset.digest is always ''
  here; integrity verification silently stays local-hash-only for GitLab
  sources (see backend._pull_firmware() — digest check is skipped when the
  release provides none).
- Public projects only, matching GitHub's current scope: no PRIVATE-TOKEN
  header is sent.
"""
from urllib.parse import quote, urlsplit

import httpx

from app.core.firmware.models import FirmwareError, FirmwareSource, ResolvedAsset

USER_AGENT = 'nice4iot'
_DEFAULT_BASE = 'https://gitlab.com'


def _base_url(src: FirmwareSource) -> str:
    return src.host_url.strip().rstrip('/') or _DEFAULT_BASE


def _api_base(src: FirmwareSource) -> str:
    return f'{_base_url(src)}/api/v4'


def _api_headers(etag: str | None = None) -> dict[str, str]:
    headers = {'User-Agent': USER_AGENT}
    if etag:
        headers['If-None-Match'] = etag
    return headers


async def resolve_release(client: httpx.AsyncClient, repo: str, src: FirmwareSource,
                          etag: str | None) -> tuple[dict | None, str]:
    """Return (release_json, etag). release_json is None on HTTP 304 (unchanged)."""
    project = quote(repo, safe='')
    base = _api_base(src)

    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        if not tag:
            raise FirmwareError('pinned channel requires a tag')
        url = f'{base}/projects/{project}/releases/{quote(tag, safe="")}'
    else:
        # 'stable'/'prerelease' both mean "newest release" — GitLab has no
        # draft/prerelease flag on a release to filter by.
        url = f'{base}/projects/{project}/releases?order_by=released_at&sort=desc&per_page=1'

    resp = await client.get(url, headers=_api_headers(etag))
    if resp.status_code == 304:
        return None, etag or ''
    if resp.status_code == 404:
        raise FirmwareError(f'not found on GitLab: {repo} ({src.channel})')
    if resp.status_code != 200:
        raise FirmwareError(f'GitLab returned {resp.status_code} for {url}')
    new_etag = resp.headers.get('etag', '')
    data = resp.json()

    if src.channel == 'pinned':
        return data, new_etag
    if not data:
        raise FirmwareError(f'no releases found for {repo}')
    return data[0], new_etag


def resolved_asset(release_json: dict, src: FirmwareSource) -> ResolvedAsset:
    links = (release_json.get('assets') or {}).get('links', [])
    for link in links:
        if link.get('name') == src.asset_name:
            return ResolvedAsset(
                tag=release_json.get('tag_name', ''),
                asset_name=src.asset_name,
                download_url=link.get('direct_asset_url') or link['url'],
                digest='',  # GitLab's release API carries no asset digest
            )
    raise FirmwareError(f'asset {src.asset_name!r} not found in release '
                        f'{release_json.get("tag_name")!r}')


def release_url(repo: str, src: FirmwareSource) -> str:
    """Human-facing GitLab Releases URL the current config resolves to."""
    base = f'{_base_url(src)}/{repo}/-/releases'
    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        return f'{base}/{tag}' if tag else base
    return base  # 'stable'/'prerelease' both just list the releases page


def download_headers() -> dict[str, str]:
    return {'User-Agent': USER_AGENT}


def is_allowed_download_host(host: str, src: FirmwareSource) -> bool:
    return host == urlsplit(_base_url(src)).hostname
