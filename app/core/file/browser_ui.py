"""
Device / Project Files — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

The device tab shows both in **one** list: the device's own files layered over the
project's, with inherited entries marked by a chip. Writes never reach the
underlay — saving an inherited file copies it to the device. The merge and the
per-entry resolution live in `overlay.py`.

Built on niceview's DrillDownWrapper over an OverlayDirectoryAdapter in all-files
mode (mixed extensions, keyed by full filename): this module is the list half —
rows, upload, new file — and `detail_ui.py` is the detail half.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anyio
from nicegui import ui
from niceview import DrillDownWrapper
from niceview.util import confirm_dialog, input_dialog

from app.core.device.backend import get_device_path
from app.core.file.backend import get_file_config, load_file_state, publish_file_now
from app.core.file.detail_ui import (
    FILE_ICONS,
    download_file,
    file_detail,
    maybe_publish,
    save_text,
)
from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter, OverlayFileEntry
from app.paths import project_dir as get_project_dir
from app.util import atomic_write, human_size, is_valid_upload_filename, render_datetime

log = logging.getLogger('uvicorn')


# ---------------------------------------------------------------------------
# List view (render_list_item) — one row
# ---------------------------------------------------------------------------

def _file_list_row(entry: OverlayFileEntry, select: Callable[[], None], ctx: FileCtx,
                   refresh: Callable[[], Any], state: dict) -> None:
    path = entry.read_path
    # State is keyed by basename per device, so inherited files are covered too.
    published_at = state.get(entry.name, {}).get('published_at') if ctx.mqtt_enabled else None

    with ui.row().classes('w-full items-center gap-0 q-py-xs'):
        ui.icon(FILE_ICONS.get(path.suffix.lower(), 'insert_drive_file')) \
            .classes('text-grey-7 text-sm q-mr-sm')
        with ui.column().classes('grow gap-0 cursor-pointer').on('click', select):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.label(entry.name).classes('text-body2')
                if entry.inherited:
                    ui.chip('project', icon='folder_shared') \
                        .props('dense outline size=sm color=grey-7') \
                        .tooltip('Served from the project directory — this device has no own copy')
            ui.label(f'{render_datetime(entry.mtime)}, {human_size(entry.size)}') \
                .classes('text-caption text-grey-7')
            if published_at:
                try:
                    ui.label(f'published {render_datetime(datetime.fromisoformat(published_at))}') \
                        .classes('text-caption text-grey-7')
                except (ValueError, TypeError):
                    pass
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download') \
            .on_click(lambda _, p=path: download_file(p))

        if ctx.can_publish:
            # Inherited files are publishable too — the watcher sends them to the
            # device anyway, so this only forces what would happen on its own.
            async def _publish(p=path) -> None:
                ok = await publish_file_now(ctx.project_name, ctx.device_name, p)
                if ok:
                    ui.notify(f'Published {p.name} to device via MQTT', type='positive')
                    refresh()
                else:
                    ui.notify('MQTT publish failed (not connected?)', type='warning')
            ui.button(icon='cloud_upload').props('flat dense size=sm') \
                .tooltip('Force publish to device via MQTT').on_click(_publish)

        # No delete for inherited files: there is no device copy to remove, and the
        # project file belongs to every other device as well.
        if not entry.inherited:
            question = (f'Delete this device\'s copy of **{entry.name}**? '
                        'The project file will be used again.'
                        if entry.overrides
                        else f'Delete **{entry.name}**? This is irreversible.')

            async def _delete(p=path, q=question) -> None:
                if not await confirm_dialog('Delete File', q,
                                            ok_label='Delete', ok_color='negative'):
                    return
                try:
                    p.unlink()
                    ui.notify(f'Deleted {p.name}', type='positive')
                    refresh()
                except OSError as e:
                    ui.notify(f'Delete failed: {e}', type='negative')
            ui.button(icon='delete').props('flat dense size=sm color=negative') \
                .tooltip('Delete').on_click(_delete)


# ---------------------------------------------------------------------------
# New file / upload
# ---------------------------------------------------------------------------

def _as_json_name(raw: str) -> str:
    """'config' and 'config.json' both mean config.json."""
    name = (raw or '').strip()
    return name if name.endswith('.json') else f'{name}.json'


def _make_upload_handler(directory: Path, refresh: Callable[[], Any], ctx: FileCtx):
    """Return an upload handler that writes uploaded files to *directory* atomically.

    An upload can be several MB, so the blocking write/rename is pushed to a
    worker thread — the same treatment as the device-facing PUT /api/file path."""
    async def _handle(e) -> None:
        # NiceGUI 3.x: the upload event carries a FileUpload (e.file) whose read()
        # is async; the earlier e.name / e.content.read() no longer exist.
        filename = e.file.name
        if not is_valid_upload_filename(filename):
            ui.notify(f'Invalid filename: {filename!r}', type='negative')
            e.sender.reset()
            return
        dest = directory / filename
        content = await e.file.read()
        try:
            await anyio.to_thread.run_sync(lambda: atomic_write(dest, content))
            ui.notify(f'Uploaded {filename}', type='positive')
            refresh()
            maybe_publish(dest, ctx)
        except OSError as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
        finally:
            e.sender.reset()
    return _handle


# ---------------------------------------------------------------------------
# Card = DrillDownWrapper(list <-> detail) + an always-visible upload footer
# ---------------------------------------------------------------------------

def _build_wrapper(adapter: OverlayDirectoryAdapter, *, title: str, ctx: FileCtx,
                   refresh: Callable[[], Any], state: dict) -> DrillDownWrapper:
    """The list <-> detail wrapper for one card.

    Extracted from `_files_card` so a test can drive the navigation niceview owns:
    rendering a panel only ever reaches the list view, and a mismatch in what we
    hand the wrapper used to surface in the browser rather than in CI.
    """
    return DrillDownWrapper.from_adapter(
        OverlayFileEntry, adapter,
        list_title=title,
        item_title_field='name',
        add_button=None, delete_button=None,  # our own row/footer actions instead
        render_list_item=lambda _key, item, select: _file_list_row(
            item, select, ctx, refresh, state),
        render_detail=lambda a, key, _set: file_detail(a, key, ctx),
    )


def _files_card(write_dir: Path, *, title: str, description: str, ctx: FileCtx) -> None:
    """One Files card. Everything is written to *write_dir*; ctx.underlay_dir adds
    a read-only layer beneath it (the project dir, for a device card), which also
    serves as the fallback directory for schema sidecars."""
    write_dir.mkdir(parents=True, exist_ok=True)
    max_upload = get_file_config(ctx.project_name).max_upload_size
    wrapper: DrillDownWrapper | None = None

    @ui.refreshable
    def wrapper_body() -> None:
        nonlocal wrapper
        state: dict = {}
        if ctx.mqtt_enabled and ctx.device_name:
            state = load_file_state(ctx.project_name, ctx.device_name)
        adapter = OverlayDirectoryAdapter(write_dir, ctx.underlay_dir, suffix=None,
                                          name_filter=is_valid_upload_filename)
        wrapper = _build_wrapper(adapter, title=title, ctx=ctx,
                                 refresh=wrapper_body.refresh, state=state)
        wrapper.render()

    ui.markdown(description).classes('text-caption q-ma-none')
    wrapper_body()

    # Upload footer lives outside the wrapper so it is reachable even when the
    # directory is empty (DrillDownWrapper skips render_list_container then).
    # Uploads and new files always land in write_dir, never in the underlay.
    ui.separator().classes('q-mt-sm')
    with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
        ui.label('Upload').classes('text-caption text-grey-7')

        async def _new_json() -> None:
            """Ask for a name, create an empty object, drill straight into its editor."""
            raw = await input_dialog(
                'New JSON File', label='Filename', placeholder='config',
                validator=lambda s: is_valid_upload_filename(_as_json_name(s)),
                error_message='Letters, digits, _ - . only, starting with a letter or digit')
            if raw is None:
                return  # cancelled
            fname = _as_json_name(raw)
            dest = write_dir / fname
            if dest.exists():
                ui.notify(f'{fname} already exists — open it to edit', type='warning')
                return
            if not save_text(dest, '{}\n'):
                return
            # Creating a device file of a project file's name is allowed, but say so.
            hides = ctx.underlay_dir is not None and (ctx.underlay_dir / fname).is_file()
            ui.notify(f'Created {fname}' + (' — overrides the project file' if hides else ''),
                      type='positive')
            maybe_publish(dest, ctx)
            wrapper_body.refresh()
            if wrapper is not None:
                wrapper.open(fname)

        ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

    ui.upload(
        on_upload=_make_upload_handler(write_dir, wrapper_body.refresh, ctx),
        max_file_size=max_upload,
        auto_upload=True,
    ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

_DEVICE_DESC = ('Every file this device is served — its own plus the project files '
                'it inherits, marked with a `project` chip. Editing an inherited file '
                'saves a copy for this device; the project file stays unchanged.')
_PROJECT_DESC = ('Shared files in the project directory. '
                 'Served to devices as a fallback when no device-specific copy exists.')


async def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the device Files tab: the device's effective file set — its own
    files layered over the project's, exactly as the API and the MQTT publisher
    resolve them."""
    from app.core.project.backend import get_project
    try:
        mqtt_enabled = get_project(project_name, check_active=False).is_mqtt_enabled
    except Exception:
        mqtt_enabled = False
    _files_card(get_device_path(project_name, device_name),
                title='Files', description=_DEVICE_DESC,
                ctx=FileCtx(project_name, device_name, mqtt_enabled,
                            underlay_dir=get_project_dir(project_name)))


async def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab — the project directory on its own, with
    no underlay, so no file is ever inherited here."""
    _files_card(get_project_dir(project_name),
                title='Project Files', description=_PROJECT_DESC,
                ctx=FileCtx(project_name, None, False))
