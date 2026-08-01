"""
Device / Project Files — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

Built on niceview's DrillDownWrapper over a DirectoryAdapter in all-files mode
(mixed extensions, keyed by full filename): the list drills down into a per-file
detail view. JSON opens in a validating CodeMirror editor, recognised text files
in a plain editor, images (png/jpg/gif/webp ≤ 2 MB) as an inline preview; SVG and
other binaries stay download-only (untrusted SVG is never rendered inline — see
docs/file-forms.md).
"""
import asyncio
import base64
import json
from pathlib import Path
from typing import Callable, NamedTuple

from nicegui import ui
from niceview import DirectoryAdapter, DrillDownWrapper, FileEntry
from niceview.util import confirm_dialog

from app.core.device.backend import get_device_path
from app.paths import project_dir as get_project_dir
from app.util import is_valid_upload_filename, render_datetime

import logging
log = logging.getLogger("uvicorn")

# ---------------------------------------------------------------------------
# File-type constants
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    '.yaml': 'YAML',  '.yml':  'YAML',
    '.toml': 'TOML',  '.xml':  'XML',
    '.html': 'HTML',  '.md':   'Markdown',
    '.py':   'Python', '.sh':  'Shell',
    '.css':  'CSS',   '.js':   'JavaScript',
}
_TEXT_EXTENSIONS: set[str] = {'.txt', '.log', '.csv', '.ini', '.cfg', '.conf'} | set(_LANG_MAP)
_MAX_VIEWER_SIZE: int = 100 * 1024  # 100 KB — larger text stays download-only

# Images rendered inline as a data: URI. SVG is deliberately excluded — scripts in
# an inline-rendered SVG would execute; larger images stay download-only.
_IMAGE_MIME: dict[str, str] = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp',
}
_MAX_IMAGE_SIZE: int = 2 * 1024 * 1024  # 2 MB


class _Ctx(NamedTuple):
    """Per-card context: which project/device and whether to publish over MQTT.

    device_name is None for the project Files tab (no device to publish to).
    """
    project_name: str
    device_name: str | None
    mqtt_enabled: bool


def _codemirror_language(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == '.json':
        return 'JSON'
    return _LANG_MAP.get(ext)


# ---------------------------------------------------------------------------
# Shared write / publish / download helpers
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> bool:
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        tmp.rename(path)
        return True
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        ui.notify(f'Save failed: {exc}', type='negative')
        return False


def _maybe_publish(path: Path, ctx: _Ctx) -> None:
    if ctx.mqtt_enabled and ctx.project_name and ctx.device_name:
        from app.core.file.backend import publish_file_now
        asyncio.create_task(publish_file_now(ctx.project_name, ctx.device_name, path))


def _download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Detail view (render_detail) — one file, dispatched by type
# ---------------------------------------------------------------------------

def _render_json_editor(path: Path, ctx: _Ctx) -> None:
    try:
        raw = path.read_text(encoding='utf-8') if path.is_file() else '{}'
        content = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        content = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '{}'

    editor = (
        ui.codemirror(value=content, language='JSON', line_wrapping=True)
        .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
    )

    def _save() -> None:
        try:
            parsed = json.loads(editor.value)
        except json.JSONDecodeError as exc:
            ui.notify(f'Invalid JSON: {exc}', type='negative')
            return
        if _atomic_write_text(path, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'):
            ui.notify(f'Saved {path.name}', type='positive')
            _maybe_publish(path, ctx)

    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button('Save', on_click=_save).props('color=primary')


def _render_text_editor(path: Path, ctx: _Ctx) -> None:
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return

    editor = (
        ui.codemirror(value=content, language=_codemirror_language(path), line_wrapping=True)
        .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
    )

    def _save() -> None:
        # Text is saved verbatim (no reformatting, unlike JSON).
        if _atomic_write_text(path, editor.value):
            ui.notify(f'Saved {path.name}', type='positive')
            _maybe_publish(path, ctx)

    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button('Save', on_click=_save).props('color=primary')


def _render_image_preview(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return
    mime = _IMAGE_MIME.get(path.suffix.lower(), 'application/octet-stream')
    b64 = base64.b64encode(data).decode('ascii')
    ui.image(f'data:{mime};base64,{b64}').classes('w-full') \
        .style('max-height: 70vh; object-fit: contain')


def _render_download_only(path: Path, reason: str) -> None:
    with ui.column().classes('items-start gap-2 q-mt-sm'):
        ui.label(reason).classes('text-body2 text-grey-7')
        ui.button('Download', icon='download',
                  on_click=lambda: _download_file(path)).props('outline')


def _file_detail(dir_path: Path, key: str, ctx: _Ctx) -> None:
    """render_detail body for one file, dispatched on type and size."""
    path = dir_path / key
    if not path.is_file():
        ui.label(f'{key!r} not found.').classes('text-negative')
        return
    ext = path.suffix.lower()
    size = path.stat().st_size
    if ext == '.json':
        _render_json_editor(path, ctx)
    elif ext in _IMAGE_MIME:
        if size <= _MAX_IMAGE_SIZE:
            _render_image_preview(path)
        else:
            _render_download_only(path, f'Image too large to preview ({size / 1024 / 1024:.1f} MB).')
    elif ext in _TEXT_EXTENSIONS:
        if size <= _MAX_VIEWER_SIZE:
            _render_text_editor(path, ctx)
        else:
            _render_download_only(path, f'File too large to edit ({size / 1024:.0f} KB).')
    else:
        _render_download_only(path, 'Binary file — download to view.')


# ---------------------------------------------------------------------------
# List view (render_list_item) — one row
# ---------------------------------------------------------------------------

def _file_list_row(dir_path: Path, key: str, item: FileEntry, select: Callable[[], None],
                   ctx: _Ctx, refresh: Callable[[], None], state: dict) -> None:
    path = dir_path / key
    ext = path.suffix.lower()
    is_json = ext == '.json'
    is_image = ext in _IMAGE_MIME
    is_text = ext in _TEXT_EXTENSIONS
    icon = ('data_object' if is_json else 'image' if is_image
            else 'article' if is_text else 'insert_drive_file')
    size = item.size
    size_str = f'{size / 1024:.1f} KB' if size < 1024 * 1024 else f'{size / 1024 / 1024:.1f} MB'
    published_at = state.get(key, {}).get('published_at') if ctx.mqtt_enabled else None

    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon(icon).classes('text-grey-6 text-sm')
        with ui.column().classes('grow gap-0'):
            ui.label(key).classes('text-body2 cursor-pointer').on('click', select)
            if published_at:
                try:
                    from datetime import datetime
                    ui.label(f'Published: {render_datetime(datetime.fromisoformat(published_at))}') \
                        .classes('text-caption text-grey-6')
                except (ValueError, TypeError):
                    pass
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='chevron_right').props('flat dense size=sm').tooltip('Open').on_click(select)
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download') \
            .on_click(lambda _, p=path: _download_file(p))

        if ctx.mqtt_enabled and ctx.project_name and ctx.device_name:
            async def _publish(p=path) -> None:
                from app.core.file.backend import publish_file_now
                ok = await publish_file_now(ctx.project_name, ctx.device_name, p)
                if ok:
                    ui.notify(f'Published {p.name} to device via MQTT', type='positive')
                    refresh()
                else:
                    ui.notify('MQTT publish failed (not connected?)', type='warning')
            ui.button(icon='cloud_upload').props('flat dense size=sm') \
                .tooltip('Force publish to device via MQTT').on_click(_publish)

        async def _delete(p=path) -> None:
            if not await confirm_dialog('Delete File', f'Delete **{p.name}**? This is irreversible.',
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

async def _new_json_dialog(directory: Path, refresh: Callable[[], None], ctx: _Ctx) -> None:
    """Create a new JSON file using a CodeMirror editor."""
    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        ui.label('New JSON File').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
            filename_input = ui.input(label='Filename', placeholder='config') \
                .props('outlined dense').classes('grow')
            filename_preview = ui.label('').classes('text-caption text-grey-6 text-no-wrap')

        def _update_preview(e) -> None:
            raw = (e.value or '').strip()
            effective = raw if raw.endswith('.json') else (f'{raw}.json' if raw else '')
            filename_preview.text = f'→ {effective}' if effective else ''

        filename_input.on_value_change(_update_preview)
        editor = ui.codemirror(value='{}', language='JSON', line_wrapping=True) \
            .classes('w-full border rounded q-mt-xs').style('height: clamp(160px, 30vh, 400px)')

        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            def _create() -> None:
                raw = (filename_input.value or '').strip()
                fname = raw if raw.endswith('.json') else f'{raw}.json'
                if not fname or fname == '.json':
                    ui.notify('Please enter a filename', type='warning')
                    return
                if not is_valid_upload_filename(fname):
                    ui.notify(f'Invalid filename: {fname!r}', type='negative')
                    return
                try:
                    parsed = json.loads(editor.value)
                except json.JSONDecodeError as exc:
                    ui.notify(f'Invalid JSON: {exc}', type='negative')
                    return
                dest = directory / fname
                if dest.exists():
                    ui.notify(f'{fname} already exists — open it to edit', type='warning')
                    return
                if _atomic_write_text(dest, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'):
                    ui.notify(f'Created {fname}', type='positive')
                    dialog.close()
                    refresh()
                    _maybe_publish(dest, ctx)

            ui.button('Create', on_click=_create).props('color=primary')

    dialog.open()
    await dialog


def _make_upload_handler(directory: Path, refresh: Callable[[], None], ctx: _Ctx):
    """Return an upload handler that writes uploaded files to *directory* atomically."""
    def _handle(e) -> None:
        filename = e.name
        if not is_valid_upload_filename(filename):
            ui.notify(f'Invalid filename: {filename!r}', type='negative')
            e.sender.reset()
            return
        dest = directory / filename
        tmp = dest.with_name(dest.name + '.tmp')
        try:
            tmp.write_bytes(e.content.read())
            tmp.rename(dest)
            ui.notify(f'Uploaded {filename}', type='positive')
            refresh()
            _maybe_publish(dest, ctx)
        except Exception as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
            tmp.unlink(missing_ok=True)
        finally:
            e.sender.reset()
    return _handle


# ---------------------------------------------------------------------------
# Card = DrillDownWrapper(list <-> detail) + an always-visible upload footer
# ---------------------------------------------------------------------------

def _files_card(dir_path: Path, *, title: str, description: str, ctx: _Ctx) -> None:
    from app.core.file.backend import get_file_config
    dir_path.mkdir(parents=True, exist_ok=True)
    max_upload = get_file_config(ctx.project_name).max_upload_size

    @ui.refreshable
    def wrapper_body() -> None:
        state: dict = {}
        if ctx.mqtt_enabled and ctx.device_name:
            from app.core.file.backend import load_file_state
            state = load_file_state(ctx.project_name, ctx.device_name)
        adapter = DirectoryAdapter(dir_path, suffix=None, name_filter=is_valid_upload_filename)

        def _list_item(key: str, item: FileEntry, select: Callable[[], None]) -> None:
            _file_list_row(dir_path, key, item, select, ctx, wrapper_body.refresh, state)

        DrillDownWrapper.from_adapter(
            FileEntry, adapter,
            list_title=title,
            item_title_field='name',
            add_button=None, delete_button=None,  # our own row/footer actions instead
            render_list_item=_list_item,
            render_detail=lambda _a, key, _set: _file_detail(dir_path, key, ctx),
        ).render()

    ui.markdown(description).classes('text-caption q-ma-none')
    wrapper_body()

    # Upload footer lives outside the wrapper so it is reachable even when the
    # directory is empty (DrillDownWrapper skips render_list_container then).
    ui.separator().classes('q-mt-sm')
    with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
        ui.label('Upload').classes('text-caption text-grey-7')

        async def _new_json() -> None:
            await _new_json_dialog(dir_path, wrapper_body.refresh, ctx)
        ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

    ui.upload(
        on_upload=_make_upload_handler(dir_path, wrapper_body.refresh, ctx),
        max_file_size=max_upload,
        auto_upload=True,
    ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

_DEVICE_DESC = ('Files stored in the device directory. '
                'Devices can upload (PUT) and download (GET) these via the API.')
_PROJECT_DESC = ('Shared files in the project directory. '
                 'Served to devices as a fallback when no device-specific copy exists.')


def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the device Files tab (device files + project-file fallback)."""
    from app.core.project.backend import get_project
    try:
        mqtt_enabled = get_project(project_name, check_active=False).is_mqtt_enabled
    except Exception:
        mqtt_enabled = False
    # Both cards publish to this device when MQTT is on.
    ctx = _Ctx(project_name, device_name, mqtt_enabled)
    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with ui.card().classes('w-full'):
            _files_card(get_device_path(project_name, device_name),
                        title='Device Files', description=_DEVICE_DESC, ctx=ctx)
        with ui.card().classes('w-full'):
            _files_card(get_project_dir(project_name),
                        title='Project Files', description=_PROJECT_DESC, ctx=ctx)


def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab (single card, full width)."""
    with ui.card().classes('w-full'):
        _files_card(get_project_dir(project_name),
                    title='Project Files', description=_PROJECT_DESC,
                    ctx=_Ctx(project_name, None, False))
