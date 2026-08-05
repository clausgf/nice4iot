"""
Device files layered over project files — the merge behind the unified Files card.

For a device, a project file *is* one of its files unless a device-specific copy
of the same name shadows it. Two places in the backend already model exactly
that, and this module mirrors them for the UI so the three never drift:

* `get_device_path()`/`get_file_path()` in `app.core.device.backend` — the
  device-facing GET resolves the device path first, the project path second.
* `check_and_publish_project()` in `app.core.file.backend` — device files first,
  then project files for the names not already covered.

Reads therefore follow the underlay; writes never do. Saving an inherited file
copies it into the device directory (copy-on-write), leaving the project file —
and every other device using it — untouched.

Free of NiceGUI, so the merge stays unit-testable; the rendering lives in
`files_ui.py`.
"""
import os
from pathlib import Path
from typing import Any, NamedTuple

from niceview import DirectoryAdapter

from app.util import shadow_merge


class FileRef(NamedTuple):
    """One entry of the merged listing: where it is read, where a save goes.

    ``inherited`` and ``overrides`` are mutually exclusive and describe the two
    interesting cases; both are False for a plain file and for every file of a
    card without an underlay (the project Files tab), where read_path == save_path.
    """
    key: str            # full filename, the adapter's key
    read_path: Path     # the device copy, or the project file when inherited
    save_path: Path     # always in the card's own directory (copy-on-write)
    inherited: bool     # read from the underlay — the device has no own copy
    overrides: bool     # the device's own copy, shadowing a project file of that name


def resolve_ref(key: str, write_dir: Path, underlay: Path | None) -> FileRef:
    """Resolve *key* against the card's directory and its optional underlay.

    Precedence matches `get_file_path()`: the own copy wins, the underlay is the
    fallback. A name that exists in neither resolves to the own directory, so a
    caller can use save_path for a file it is about to create.
    """
    own = write_dir / key
    under_exists = underlay is not None and (underlay / key).is_file()
    if own.is_file():
        return FileRef(key, own, own, False, under_exists)
    if under_exists:
        assert underlay is not None  # implied by under_exists, spelled out for mypy
        return FileRef(key, underlay / key, own, True, False)
    return FileRef(key, own, own, False, False)


class OverlayDirectoryAdapter(DirectoryAdapter):
    """A DirectoryAdapter over *dir_path* with *underlay* as a read-only layer
    beneath it: files of the same name in dir_path shadow those in the underlay.

    Only reads are merged. create()/delete() stay on the base class and therefore
    only ever touch dir_path — the Files card disables the wrapper's add/delete
    buttons and drives its own row actions, so they are unused in practice.
    """

    def __init__(self, dir_path: Path, underlay: Path | None = None, **kwargs: Any) -> None:
        super().__init__(dir_path, **kwargs)
        self._underlay = underlay
        # A plain adapter over the underlay lists it by exactly the same rules
        # (suffix mode, dotfiles, name_filter) — no need to restate any of them here.
        self._under = (DirectoryAdapter(underlay, **kwargs)
                       if underlay is not None and underlay.is_dir() else None)

    def _path(self, key: str) -> Path:
        own = super()._path(key)  # validates the key before it is joined
        if own.is_file() or self._underlay is None:
            return own
        under = self._underlay / key
        return under if under.is_file() else own

    def _scan(self) -> list[tuple[str, os.stat_result]]:
        own = super()._scan()
        if self._under is None:
            return own
        merged = shadow_merge(own, self._under._scan(), key=lambda pair: pair[0])
        # Re-sort: the two layers arrive as separate sorted runs, but the card
        # shows one namespace.
        merged.sort(key=lambda pair: os.path.normcase(pair[0]))
        return merged
