"""Software Bill of Materials — the installed Python distributions and their
versions, read from package metadata (``importlib.metadata``).

Pure and synchronous so it stays trivial to test; UI callers wrap
``collect_sbom()`` in ``anyio.to_thread.run_sync`` per the async-IO rule, since
scanning installed-package metadata touches the filesystem.
"""
import importlib.metadata as _im


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
