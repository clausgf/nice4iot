"""GitHub REST API backend for firmware release resolution. Dispatched to by
app/core/firmware/backend.py's host-agnostic orchestration — see gitlab.py
for the other backend and everything that differs.
"""
from urllib.parse import quote

import httpx

from app.core.firmware.models import FirmwareError, FirmwareSource, ResolvedAsset
from app.util import logger

API_BASE = 'https://api.github.com'
API_VERSION = '2022-11-28'
USER_AGENT = 'nice4iot'

# The asset download 302s from api.github.com to a GitHub-owned asset host. We
# never attach credentials, so this is a defence-in-depth check, not a secret guard.
_ALLOWED_DOWNLOAD_HOSTS = ('api.github.com', 'github.com', 'codeload.github.com')
_ALLOWED_DOWNLOAD_SUFFIX = '.githubusercontent.com'


def _api_headers(etag: str | None = None) -> dict[str, str]:
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': API_VERSION,
        'User-Agent': USER_AGENT,
    }
    if etag:
        headers['If-None-Match'] = etag
    return headers


def _log_rate_limit(resp: httpx.Response) -> None:
    remaining = resp.headers.get('x-ratelimit-remaining')
    if remaining is not None and remaining.isdigit() and int(remaining) <= 5:
        reset = resp.headers.get('x-ratelimit-reset', '?')
        logger.warning(f'GitHub rate limit low: {remaining} remaining (resets at {reset})')


async def resolve_release(client: httpx.AsyncClient, repo: str, src: FirmwareSource,
                          etag: str | None) -> tuple[dict | None, str]:
    """Return (release_json, etag). release_json is None on HTTP 304 (unchanged)."""
    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        if not tag:
            raise FirmwareError('pinned channel requires a tag')
        url = f'{API_BASE}/repos/{repo}/releases/tags/{quote(tag, safe="")}'
    elif src.channel == 'stable':
        url = f'{API_BASE}/repos/{repo}/releases/latest'
    else:  # prerelease → list, pick newest non-draft
        url = f'{API_BASE}/repos/{repo}/releases?per_page=20'

    resp = await client.get(url, headers=_api_headers(etag))
    _log_rate_limit(resp)
    if resp.status_code == 304:
        return None, etag or ''
    if resp.status_code == 404:
        raise FirmwareError(f'not found on GitHub: {repo} ({src.channel})')
    if resp.status_code != 200:
        raise FirmwareError(f'GitHub returned {resp.status_code} for {url}')
    new_etag = resp.headers.get('etag', '')
    data = resp.json()

    if src.channel == 'prerelease':
        releases = [r for r in data if not r.get('draft')]
        if not releases:
            raise FirmwareError(f'no releases found for {repo}')
        releases.sort(key=lambda r: r.get('published_at') or '', reverse=True)
        return releases[0], new_etag
    return data, new_etag


def resolved_asset(release_json: dict, src: FirmwareSource) -> ResolvedAsset:
    for asset in release_json.get('assets', []):
        if asset.get('name') == src.asset_name:
            return ResolvedAsset(
                tag=release_json.get('tag_name', ''),
                asset_name=src.asset_name,
                download_url=asset['url'],
                digest=(asset.get('digest') or ''),
            )
    raise FirmwareError(f'asset {src.asset_name!r} not found in release '
                        f'{release_json.get("tag_name")!r}')


def release_url(repo: str, src: FirmwareSource) -> str:
    """Human-facing GitHub Releases URL the current config resolves to."""
    base = f'https://github.com/{repo}/releases'
    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        return f'{base}/tag/{tag}' if tag else base
    if src.channel == 'stable':
        return f'{base}/latest'
    return base  # prerelease → the releases list


def download_headers() -> dict[str, str]:
    return {'Accept': 'application/octet-stream', 'User-Agent': USER_AGENT}


def is_allowed_download_host(host: str, src: FirmwareSource) -> bool:
    return host in _ALLOWED_DOWNLOAD_HOSTS or host.endswith(_ALLOWED_DOWNLOAD_SUFFIX)
