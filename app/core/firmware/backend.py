"""
Firmware pull from public GitHub Releases.

Each directory (a project dir or a device dir) may carry a ``.firmware.json``
(:class:`FirmwareSource`) pointing at a public GitHub repo. A pull resolves a
release and downloads every asset ``asset_name`` matches — a plain name matches
at most one; a "*"/"?" wildcard may match any number, e.g. a release that ships
several board-specific files under one pattern. Each is verified against its
digest and written atomically into that directory — as ``dest_filename`` for a
single non-wildcard match, or under its own GitHub name when ``asset_name`` is
a wildcard (there is no single rename target for more than one file) — from
where the normal file-serving path (device copy overriding project copy)
delivers it to devices. State is recorded in ``.firmware.state.json``.

No credentials are ever sent to GitHub (public repos only), so nothing can leak
across the redirect to the asset host. All network I/O is async (httpx); the
disk write is off-loaded to a worker thread (anyio.to_thread).
"""
import datetime
import fnmatch
import functools
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import anyio
import httpx
from niceview.dataadapter import JsonAdapter, lenient_model_load

from app.core.firmware.models import REPO_RE, FirmwareSource, FirmwareState, is_wildcard_asset_name
from app.paths import device_dir, project_dir
from app.util import atomic_write, is_valid_upload_filename, logger

FIRMWARE_CONFIG_FILE = '.firmware.json'
FIRMWARE_STATE_FILE = '.firmware.state.json'

_GITHUB_API = 'https://api.github.com'
_API_VERSION = '2022-11-28'
_USER_AGENT = 'nice4iot'
_HTTP_TIMEOUT = 30.0
_MAX_REDIRECTS = 5
_MAX_FIRMWARE_SIZE = 64 * 1024 * 1024  # 64 MiB hard cap on a downloaded asset
_MIN_INTERVAL = datetime.timedelta(minutes=5)
# The asset download 302s from api.github.com to a GitHub-owned asset host. We
# never attach credentials, so this is a defence-in-depth check, not a secret guard.
_ALLOWED_DOWNLOAD_HOSTS = ('api.github.com', 'github.com', 'codeload.github.com')
_ALLOWED_DOWNLOAD_SUFFIX = '.githubusercontent.com'


class FirmwareError(Exception):
    """A firmware pull could not be completed (config, network, or integrity)."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Config / state persistence (synchronous backend)
# ---------------------------------------------------------------------------

def get_firmware_adapter(dir_path: Path) -> JsonAdapter:
    """JsonAdapter for a directory's firmware source (for UI ModelForm binding)."""
    return JsonAdapter(FirmwareSource, dir_path / FIRMWARE_CONFIG_FILE,
                       create_if_not_exist=True, lock_field='updated_at')


def load_firmware_source(dir_path: Path) -> FirmwareSource:
    """Load a directory's firmware source without creating the file (loop-safe)."""
    path = dir_path / FIRMWARE_CONFIG_FILE
    try:
        text = path.read_text()
    except OSError:
        return FirmwareSource()
    return lenient_model_load(FirmwareSource, text, str(path))


def project_has_firmware_source(project_name: str) -> bool:
    """True if the project or any of its devices has a firmware repo configured."""
    if load_firmware_source(project_dir(project_name)).repo.strip():
        return True
    from app.core.device.backend import get_devices
    return any(
        load_firmware_source(device_dir(project_name, device.name)).repo.strip()
        for device in get_devices(project_name)
    )


def load_firmware_state(dir_path: Path) -> FirmwareState | None:
    path = dir_path / FIRMWARE_STATE_FILE
    try:
        text = path.read_text()
    except OSError:
        return None
    return lenient_model_load(FirmwareState, text, str(path))


def save_firmware_state(dir_path: Path, state: FirmwareState) -> None:
    atomic_write(dir_path / FIRMWARE_STATE_FILE, state.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# GitHub REST resolution + download (async)
# ---------------------------------------------------------------------------

@dataclass
class ResolvedAsset:
    tag: str
    asset_name: str
    download_url: str  # GitHub API asset URL (application/octet-stream → 302)
    digest: str        # 'sha256:...' from the asset JSON, or '' if absent


@dataclass
class PullResult:
    changed: bool
    tag: str
    message: str


def github_release_url(src: FirmwareSource) -> str:
    """Human-facing GitHub Releases URL the current config resolves to, for display
    in the UI. Empty when no repo is configured."""
    repo = src.repo.strip()
    if not repo:
        return ''
    base = f'https://github.com/{repo}/releases'
    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        return f'{base}/tag/{tag}' if tag else base
    if src.channel == 'stable':
        return f'{base}/latest'
    return base  # prerelease → the releases list


def _validate_repo(repo: str) -> str:
    repo = repo.strip()
    if not REPO_RE.match(repo):
        raise FirmwareError(f'invalid repository {repo!r} (expected owner/name, not a URL)')
    return repo


def _api_headers(etag: str | None = None) -> dict[str, str]:
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': _API_VERSION,
        'User-Agent': _USER_AGENT,
    }
    if etag:
        headers['If-None-Match'] = etag
    return headers


def _log_rate_limit(resp: httpx.Response) -> None:
    remaining = resp.headers.get('x-ratelimit-remaining')
    if remaining is not None and remaining.isdigit() and int(remaining) <= 5:
        reset = resp.headers.get('x-ratelimit-reset', '?')
        logger.warning(f'GitHub rate limit low: {remaining} remaining (resets at {reset})')


async def _resolve_release_json(client: httpx.AsyncClient, src: FirmwareSource,
                                etag: str | None) -> tuple[dict | None, str]:
    """Return (release_json, etag). release_json is None on HTTP 304 (unchanged)."""
    repo = _validate_repo(src.repo)
    if src.channel == 'pinned':
        tag = src.pinned_tag.strip()
        if not tag:
            raise FirmwareError('pinned channel requires a tag')
        url = f'{_GITHUB_API}/repos/{repo}/releases/tags/{quote(tag, safe="")}'
    elif src.channel == 'stable':
        url = f'{_GITHUB_API}/repos/{repo}/releases/latest'
    else:  # prerelease → list, pick newest non-draft
        url = f'{_GITHUB_API}/repos/{repo}/releases?per_page=20'

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


def _pick_assets(release_json: dict, asset_name: str) -> list[dict]:
    """Every release asset matching `asset_name`. A wildcard may match any
    number (>= 1) — e.g. a release shipping several board-specific files
    under one pattern like "firmware-*.bin" — an exact name matches at most
    one."""
    assets = release_json.get('assets', [])
    if is_wildcard_asset_name(asset_name):
        matches = [a for a in assets if fnmatch.fnmatchcase(a.get('name', ''), asset_name)]
    else:
        matches = [a for a in assets if a.get('name') == asset_name]
    if not matches:
        raise FirmwareError(f'no asset matches {asset_name!r} in release '
                            f'{release_json.get("tag_name")!r}')
    return matches


def _resolved_from(release_json: dict, src: FirmwareSource) -> list[ResolvedAsset]:
    """Resolve every asset `src.asset_name` matches, in this release. Each
    keeps its own GitHub asset name — `_pull_firmware` only renames to
    `dest_filename` for the single, non-wildcard case."""
    tag = release_json.get('tag_name', '')
    resolved = []
    for asset in _pick_assets(release_json, src.asset_name):
        name = asset.get('name') or src.asset_name
        if not is_valid_upload_filename(name):
            raise FirmwareError(f'asset name {name!r} is not a safe filename')
        resolved.append(ResolvedAsset(
            tag=tag, asset_name=name,
            download_url=asset['url'], digest=(asset.get('digest') or ''),
        ))
    return resolved


async def _download_asset(client: httpx.AsyncClient, download_url: str,
                          max_size: int) -> tuple[bytes, str]:
    """Stream an asset with a hard size cap. Returns (bytes, 'sha256:hexdigest')."""
    headers = {'Accept': 'application/octet-stream', 'User-Agent': _USER_AGENT}
    async with client.stream('GET', download_url, headers=headers) as resp:
        if resp.status_code != 200:
            raise FirmwareError(f'asset download failed: HTTP {resp.status_code}')
        host = resp.url.host
        if not (host in _ALLOWED_DOWNLOAD_HOSTS or host.endswith(_ALLOWED_DOWNLOAD_SUFFIX)):
            raise FirmwareError(f'refusing unexpected download host {host!r}')
        digest = hashlib.sha256()
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > max_size:
                raise FirmwareError(f'asset exceeds size cap ({max_size} bytes)')
            digest.update(chunk)
    return bytes(buf), 'sha256:' + digest.hexdigest()


def _combined_digest(resolved: list[ResolvedAsset]) -> str:
    """A single comparable digest for one or more resolved assets — sorted
    'name:digest' pairs, so reordering the same set never looks like a change."""
    return '|'.join(f'{r.asset_name}:{r.digest}' for r in sorted(resolved, key=lambda r: r.asset_name))


def _should_pull(src: FirmwareSource, state: FirmwareState | None,
                 resolved: list[ResolvedAsset]) -> bool:
    if state is None or not state.tag:
        return True
    if src.channel == 'pinned':
        # A pinned tag is stable; re-pull only if the asset bytes changed.
        return _combined_digest(resolved) != state.digest or resolved[0].tag != state.tag
    return resolved[0].tag != state.tag


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def peek_latest_tag(src: FirmwareSource) -> str:
    """Cheap 'latest available' lookup for the UI (no download)."""
    if not src.repo.strip():
        return ''
    async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTP_TIMEOUT,
                                 max_redirects=_MAX_REDIRECTS) as client:
        release_json, _ = await _resolve_release_json(client, src, None)
    return release_json.get('tag_name', '') if release_json else ''


async def pull_firmware(dir_path: Path, src: FirmwareSource, *, project_name: str,
                        device_name: str | None = None, force: bool = False,
                        use_conditional: bool = False) -> PullResult:
    """Resolve, download (if changed/forced), verify, write, record state, publish.

    Raises FirmwareError on any failure; nothing is written on failure.
    """
    from app.health import set_health
    key = f'{project_name}:firmware'
    try:
        result = await _pull_firmware(dir_path, src, project_name=project_name,
                                      device_name=device_name, force=force,
                                      use_conditional=use_conditional)
    except Exception as e:
        set_health(key, False, f'{device_name or "(project)"}: {e}')
        raise
    set_health(key, True)
    return result


async def _pull_firmware(dir_path: Path, src: FirmwareSource, *, project_name: str,
                         device_name: str | None = None, force: bool = False,
                         use_conditional: bool = False) -> PullResult:
    if not src.repo.strip():
        raise FirmwareError('no repository configured')

    state = await anyio.to_thread.run_sync(lambda: load_firmware_state(dir_path))
    etag = state.etag if (use_conditional and state) else None

    async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTP_TIMEOUT,
                                 max_redirects=_MAX_REDIRECTS) as client:
        release_json, new_etag = await _resolve_release_json(client, src, etag)
        if release_json is None:  # HTTP 304 — nothing changed upstream
            return PullResult(False, state.tag if state else '', 'up to date (not modified)')

        resolved = _resolved_from(release_json, src)
        tag = resolved[0].tag
        if not force and not _should_pull(src, state, resolved):
            # Refresh the stored ETag so the next conditional poll stays cheap.
            if state and new_etag and new_etag != state.etag:
                state.etag = new_etag
                await anyio.to_thread.run_sync(lambda: save_firmware_state(dir_path, state))
            return PullResult(False, tag, f'already at {tag}')

        downloaded = []  # (ResolvedAsset, data, actual_digest)
        for asset in resolved:
            data, actual_digest = await _download_asset(client, asset.download_url, _MAX_FIRMWARE_SIZE)
            if asset.digest and asset.digest.lower() != actual_digest.lower():
                raise FirmwareError(f'asset digest mismatch for {asset.asset_name!r} — nothing written')
            downloaded.append((asset, data, actual_digest))

    # Single, non-wildcard match renames to dest_filename, same as before; a
    # wildcard (whether it matched one asset or several) keeps each asset's
    # own GitHub name — there is no single dest_filename to rename them to.
    written_names = []
    for asset, data, _digest in downloaded:
        dest_name = asset.asset_name if src.asset_is_wildcard else src.dest_filename
        dest = dir_path / dest_name
        await anyio.to_thread.run_sync(functools.partial(atomic_write, dest, data))
        written_names.append(dest_name)

    new_state = FirmwareState(
        tag=tag, asset=written_names[0], assets=written_names,
        digest=_combined_digest(resolved), pulled_at=_now(), etag=new_etag,
    )
    await anyio.to_thread.run_sync(lambda: save_firmware_state(dir_path, new_state))

    if src.mqtt_publish_on_pull and device_name:
        from app.core.file.backend import publish_file_now
        for dest_name in written_names:
            try:
                await publish_file_now(project_name, device_name, dir_path / dest_name)
            except Exception as e:
                logger.error(f'firmware: MQTT publish after pull failed for '
                             f'{project_name}/{device_name}/{dest_name}: {e}')

    return PullResult(True, tag, f'pulled {tag} ({", ".join(written_names)})')


# ---------------------------------------------------------------------------
# Auto-pull background tick
# ---------------------------------------------------------------------------

_last_check: dict[str, float] = {}  # dir path → monotonic time of last auto-pull attempt


def _auto_pull_targets() -> list[tuple[Path, str, str | None]]:
    """Enumerate (dir, project_name, device_name|None) for all firmware sources."""
    from app.core.device.backend import get_devices
    from app.core.project.backend import get_projects
    targets: list[tuple[Path, str, str | None]] = []
    for project in get_projects():
        targets.append((project_dir(project.name), project.name, None))
        try:
            for device in get_devices(project.name):
                targets.append((device_dir(project.name, device.name), project.name, device.name))
        except Exception as e:
            logger.error(f'firmware auto-pull: cannot list devices for {project.name}: {e}')
    return targets


async def auto_pull_tick() -> None:
    """One pass of the auto-pull loop: pull-if-changed for every enabled source
    whose interval has elapsed. Uses conditional (ETag) requests to stay cheap."""
    targets = await anyio.to_thread.run_sync(_auto_pull_targets)
    for dir_path, project_name, device_name in targets:
        src = await anyio.to_thread.run_sync(functools.partial(load_firmware_source, dir_path))
        if not src.auto_pull_enabled or not src.repo.strip():
            continue
        interval_s = max(_MIN_INTERVAL, src.auto_pull_interval).total_seconds()
        key = str(dir_path)
        if time.monotonic() - _last_check.get(key, 0.0) < interval_s:
            continue
        _last_check[key] = time.monotonic()
        try:
            result = await pull_firmware(dir_path, src, project_name=project_name,
                                         device_name=device_name, use_conditional=True)
            if result.changed:
                logger.info(f'firmware auto-pull {project_name}/{device_name or "(project)"}: '
                            f'{result.message}')
        except Exception as e:
            logger.error(f'firmware auto-pull failed for {dir_path}: {e}')
