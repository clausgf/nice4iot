"""Software Bill of Materials — the installed Python distributions and their
versions, read from package metadata (``importlib.metadata``).

Pure and synchronous so it stays trivial to test; UI callers wrap
``collect_sbom()`` in ``anyio.to_thread.run_sync`` per the async-IO rule, since
scanning installed-package metadata touches the filesystem.
"""
import importlib.metadata as _im
import os
import subprocess


def app_revision() -> str | None:
    """Short git commit this build came from, with a ``-dirty`` suffix when the
    working tree had uncommitted changes. ``None`` when it can't be determined.

    Prefers a commit baked in at build time via the ``NICE4IOT_GIT_COMMIT``
    environment variable (the GHCR image sets it from the release SHA, since the
    image has no ``.git``); otherwise falls back to querying git in the source
    tree, which covers development and source runs.
    """
    baked = os.environ.get('NICE4IOT_GIT_COMMIT')
    if baked:
        return baked.strip()[:12] or None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        rev = subprocess.run(['git', '-C', root, 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True, timeout=2)
        if rev.returncode != 0:
            return None
        commit = rev.stdout.strip()
        status = subprocess.run(['git', '-C', root, 'status', '--porcelain'],
                                capture_output=True, text=True, timeout=2)
        if status.returncode == 0 and status.stdout.strip():
            commit += '-dirty'
        return commit or None
    except (OSError, subprocess.SubprocessError):
        return None


def package_version(name: str) -> str | None:
    """Installed version of a single distribution, or ``None`` if not installed.

    Used to surface key components (e.g. ``niceview``, ``nicepaper``) even when
    an optional one like the epaper extension is absent from this build.
    """
    try:
        return _im.version(name)
    except _im.PackageNotFoundError:
        return None


def collect_sbom() -> list[tuple[str, str]]:
    """Every installed distribution as ``(name, version)``, case-insensitively
    sorted by name.

    Deduplicated by name — a given environment can expose the same distribution
    through more than one metadata directory; the first one seen wins.
    """
    seen: dict[str, str] = {}
    for dist in _im.distributions():
        name = dist.metadata['Name']
        if name and name not in seen:
            seen[name] = dist.version
    return sorted(seen.items(), key=lambda kv: kv[0].lower())
