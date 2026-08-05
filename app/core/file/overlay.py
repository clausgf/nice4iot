"""
Device files layered over project files — the merge behind the unified Files card.

For a device, a project file *is* one of its files unless a device-specific copy
of the same name shadows it. Two places in the backend already model exactly
that, and this module mirrors them for the UI so the three never drift:

* `get_device_path()`/`get_file_path()` in `app.core.device.backend` — the
  device-facing GET resolves the device path first, the project path second.
* `check_and_publish_project()` in this package's `backend.py` — device files first,
  then project files for the names not already covered.

Reads therefore follow the underlay; writes never do. Saving an inherited file
copies it into the device directory (copy-on-write), leaving the project file —
and every other device using it — untouched.

The adapter resolves this once per entry and hands the result to the UI as an
`OverlayFileEntry`, so no caller has to redo the precedence rule alongside it.

Free of NiceGUI, so the merge stays unit-testable; the rendering lives in
`browser_ui.py` and `detail_ui.py`.
"""
import os
from pathlib import Path
from typing import Any, NamedTuple

from niceview import DirectoryAdapter, FileEntry

from app.util import shadow_merge


class FileCtx(NamedTuple):
    """Per-card context: constant for the lifetime of one Files card.

    device_name is None for the project Files tab (no device to publish to), and
    underlay_dir is None wherever nothing is inherited — which is the same card.
    """
    project_name: str
    device_name: str | None
    mqtt_enabled: bool
    underlay_dir: Path | None = None

    @property
    def can_publish(self) -> bool:
        return bool(self.mqtt_enabled and self.project_name and self.device_name)


class OverlayFileEntry(FileEntry):
    """One entry of the merged listing: niceview's file metadata plus where the
    file is read, where a save goes, and how it relates to the underlay.

    ``inherited`` and ``overrides`` are mutually exclusive and describe the two
    interesting cases; both are False for a plain file and for every file of a
    card without an underlay (the project Files tab), where read_path == save_path.
    """
    read_path: Path     # the device copy, or the project file when inherited
    save_path: Path     # always in the card's own directory (copy-on-write)
    inherited: bool = False  # read from the underlay — the device has no own copy
    overrides: bool = False  # the device's own copy, shadowing a project file of that name


class OverlayDirectoryAdapter(DirectoryAdapter):
    """A DirectoryAdapter over *dir_path* with *underlay* as a read-only layer
    beneath it: files of the same name in dir_path shadow those in the underlay.

    Every entry it hands out is an `OverlayFileEntry` carrying the resolved
    paths, so the Files card reads the precedence rule off the item instead of
    re-deriving it. `read()` follows the same precedence and therefore also
    resolves inherited names.

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

    def _resolve(self, key: str) -> tuple[Path, Path, bool, bool]:
        """(read_path, save_path, inherited, overrides) for *key*.

        Precedence matches `get_file_path()`: the own copy wins, the underlay is
        the fallback. A name that exists in neither resolves to the own directory,
        so a caller can use save_path for a file it is about to create.
        """
        own = super()._path(key)  # validates the key before it is joined
        under_exists = self._underlay is not None and (self._underlay / key).is_file()
        if own.is_file():
            return own, own, False, under_exists
        if under_exists:
            assert self._underlay is not None  # implied by under_exists, spelled out for readers
            return self._underlay / key, own, True, False
        return own, own, False, False

    def _path(self, key: str) -> Path:
        return self._resolve(key)[0]

    def _entry_from(self, key: str, stat: os.stat_result) -> OverlayFileEntry:
        base = super()._entry_from(key, stat)
        read_path, save_path, inherited, overrides = self._resolve(key)
        return OverlayFileEntry(name=base.name, mtime=base.mtime, size=base.size,
                                read_path=read_path, save_path=save_path,
                                inherited=inherited, overrides=overrides)

    def _scan(self) -> list[tuple[str, os.stat_result]]:
        own = super()._scan()
        if self._under is None:
            return own
        merged = shadow_merge(own, self._under._scan(), key=lambda pair: pair[0])
        # Re-sort: the two layers arrive as separate sorted runs, but the card
        # shows one namespace.
        merged.sort(key=lambda pair: os.path.normcase(pair[0]))
        return merged
