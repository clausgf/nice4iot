"""
Firmware pull from public GitHub or GitLab Releases.

Each directory (a project dir or a device dir) may carry a ``.firmware.json``
(:class:`FirmwareSource`) pointing at a public GitHub or GitLab repo (self-
hosted or gitlab.com). A pull resolves a release, downloads a named asset,
verifies its digest when the host's API provides one, and writes it atomically
into that directory as ``dest_filename`` — from where the normal file-serving
path (device copy overriding project copy) delivers it to devices. State is
recorded in ``.firmware.state.json``.

Host-specific request shapes live in github.py/gitlab.py (dispatched on
``src.host``); this module only knows the common per-directory orchestration.
No credentials are ever sent to either host (public repos only), so nothing
can leak across a redirect to an asset host. All network I/O is async
(httpx); the disk write is off-loaded to a worker thread (anyio.to_thread).
"""
import datetime
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import anyio
import httpx
from niceview.dataadapter import JsonAdapter, lenient_model_load

from app.core.firmware import github, gitlab
from app.core.firmware.models import (
    REPO_RE, FirmwareError, FirmwareSource, FirmwareState, ResolvedAsset,
)
from app.paths import device_dir, project_dir
from app.util import atomic_write, logger

FIRMWARE_CONFIG_FILE = '.firmware.json'
FIRMWARE_STATE_FILE = '.firmware.state.json'

_HTTP_TIMEOUT = 30.0
_MAX_REDIRECTS = 5
_MAX_FIRMWARE_SIZE = 64 * 1024 * 1024  # 64 MiB hard cap on a downloaded asset
_MIN_INTERVAL = datetime.timedelta(minutes=5)


def _host_module(src: FirmwareSource):
    return gitlab if src.host == 'gitlab' else github


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


def project_has_auto_pull_enabled(project_name: str) -> bool:
    """True if the project or any of its devices has auto-pull enabled for a configured repo."""
    src = load_firmware_source(project_dir(project_name))
    if src.auto_pull_enabled and src.repo.strip():
        return True
    from app.core.device.backend import get_devices
    return any(
        (s := load_firmware_source(device_dir(project_name, device.name))).auto_pull_enabled and bool(s.repo.strip())
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
# Host-agnostic resolution + download (async) — dispatches to github.py/gitlab.py
# ---------------------------------------------------------------------------

@dataclass
class PullResult:
    changed: bool
    tag: str
    message: str


def release_url(src: FirmwareSource) -> str:
    """Human-facing Releases URL the current config resolves to, for display
    in the UI. Empty when no repo is configured."""
    repo = src.repo.strip()
    if not repo:
        return ''
    return _host_module(src).release_url(repo, src)


def _validate_repo(repo: str) -> str:
    repo = repo.strip()
    if not REPO_RE.match(repo):
        raise FirmwareError(f'invalid repository {repo!r} (expected owner/name, or '
                            f'group/subgroup/.../name for GitLab — not a URL)')
    return repo


async def _resolve_release_json(client: httpx.AsyncClient, src: FirmwareSource,
                                etag: str | None) -> tuple[dict | None, str]:
    """Return (release_json, etag). release_json is None on HTTP 304 (unchanged)."""
    repo = _validate_repo(src.repo)
    return await _host_module(src).resolve_release(client, repo, src, etag)


def _resolved_from(release_json: dict, src: FirmwareSource) -> ResolvedAsset:
    return _host_module(src).resolved_asset(release_json, src)


async def _download_asset(client: httpx.AsyncClient, download_url: str,
                          max_size: int, src: FirmwareSource) -> tuple[bytes, str]:
    """Stream an asset with a hard size cap. Returns (bytes, 'sha256:hexdigest')."""
    module = _host_module(src)
    async with client.stream('GET', download_url, headers=module.download_headers()) as resp:
        if resp.status_code != 200:
            raise FirmwareError(f'asset download failed: HTTP {resp.status_code}')
        host = resp.url.host
        if not module.is_allowed_download_host(host, src):
            raise FirmwareError(f'refusing unexpected download host {host!r}')
        digest = hashlib.sha256()
        buf = bytearray()
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > max_size:
                raise FirmwareError(f'asset exceeds size cap ({max_size} bytes)')
            digest.update(chunk)
    return bytes(buf), 'sha256:' + digest.hexdigest()


def _should_pull(src: FirmwareSource, state: FirmwareState | None,
                 resolved: ResolvedAsset) -> bool:
    if state is None or not state.tag:
        return True
    if src.channel == 'pinned':
        # A pinned tag is stable; re-pull only if the asset bytes changed.
        return resolved.digest != state.digest or resolved.tag != state.tag
    return resolved.tag != state.tag


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
        if not force and not _should_pull(src, state, resolved):
            # Refresh the stored ETag so the next conditional poll stays cheap.
            if state and new_etag and new_etag != state.etag:
                state.etag = new_etag
                await anyio.to_thread.run_sync(lambda: save_firmware_state(dir_path, state))
            return PullResult(False, resolved.tag, f'already at {resolved.tag}')

        data, actual_digest = await _download_asset(client, resolved.download_url, _MAX_FIRMWARE_SIZE, src)

    if resolved.digest and resolved.digest.lower() != actual_digest.lower():
        raise FirmwareError('asset digest mismatch — nothing written')

    dest = dir_path / src.dest_filename
    await anyio.to_thread.run_sync(lambda: atomic_write(dest, data))

    new_state = FirmwareState(
        tag=resolved.tag, asset=resolved.asset_name,
        digest=(resolved.digest or actual_digest), pulled_at=_now(), etag=new_etag,
    )
    await anyio.to_thread.run_sync(lambda: save_firmware_state(dir_path, new_state))

    if src.mqtt_publish_on_pull and device_name:
        from app.core.file.backend import publish_file_now
        try:
            await publish_file_now(project_name, device_name, dest)
        except Exception as e:
            logger.error(f'firmware: MQTT publish after pull failed for '
                         f'{project_name}/{device_name}/{dest.name}: {e}')

    return PullResult(True, resolved.tag, f'pulled {resolved.tag}')


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
        src = await anyio.to_thread.run_sync(load_firmware_source, dir_path)
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
