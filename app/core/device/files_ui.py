"""
Device Files Tab — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

JSON files open in a CodeMirror editor with syntax highlighting and validation.
Other text files open in a read-only CodeMirror viewer.
"""
import asyncio
import json
from pathlib import Path

from nicegui import ui

from app.core.device.backend import get_device_path
from app.paths import project_dir as get_project_dir
from app.util import is_valid_upload_filename, render_datetime
from niceview.util import confirm_dialog

import logging
log = logging.getLogger("uvicorn")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    '.yaml': 'YAML',  '.yml':  'YAML',
    '.toml': 'TOML',  '.xml':  'XML',
    '.html': 'HTML',  '.md':   'Markdown',
    '.py':   'Python', '.sh':  'Shell',
    '.css':  'CSS',   '.js':   'JavaScript',
}
_TEXT_EXTENSIONS: set[str] = {'.txt', '.log', '.csv', '.ini', '.cfg', '.conf'} | set(_LANG_MAP)
_MAX_VIEWER_SIZE: int = 100 * 1024  # 100 KB


def _codemirror_language(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == '.json':
        return 'JSON'
    return _LANG_MAP.get(ext)


def _is_viewable(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS and path.stat().st_size <= _MAX_VIEWER_SIZE


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the device Files tab (two-column grid)."""
    from app.core.project.backend import get_project
    try:
        project = get_project(project_name, check_active=False)
        mqtt_enabled = project.is_mqtt_enabled
    except Exception:
        mqtt_enabled = False

    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with ui.card().classes('w-full'):
            _device_files_card(project_name, device_name, mqtt_enabled=mqtt_enabled)
        with ui.card().classes('w-full'):
            _project_files_card(project_name, device_name=device_name, mqtt_enabled=mqtt_enabled)


def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab (single card, full width)."""
    with ui.card().classes('w-full'):
        _project_files_card(project_name)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

async def _json_editor_dialog(path: Path, refresh_fn=None,
                              project_name: str | None = None,
                              device_name: str | None = None,
                              mqtt_enabled: bool = False) -> None:
    """CodeMirror JSON editor with validation and atomic save."""
    try:
        raw = path.read_text(encoding='utf-8') if path.is_file() else '{}'
        content = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        content = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '{}'

    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        ui.label(f'Edit  {path.name}').classes('text-subtitle1 font-bold')
        ui.separator()
        editor = (
            ui.codemirror(value=content, language='JSON', line_wrapping=True)
            .classes('w-full border rounded')
            .style('height: clamp(200px, 40vh, 500px)')
        )
        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            async def _save() -> None:
                try:
                    parsed = json.loads(editor.value)
                except json.JSONDecodeError as exc:
                    ui.notify(f'Invalid JSON: {exc}', type='negative')
                    return
                tmp = path.with_suffix(path.suffix + '.tmp')
                try:
                    tmp.write_text(
                        json.dumps(parsed, indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8',
                    )
                    tmp.rename(path)
                except OSError as exc:
                    tmp.unlink(missing_ok=True)
                    ui.notify(f'Save failed: {exc}', type='negative')
                    return
                ui.notify(f'Saved {path.name}', type='positive')
                dialog.close()
                if refresh_fn:
                    refresh_fn()
                # Trigger MQTT publish if enabled
                if mqtt_enabled and project_name and device_name:
                    from app.core.file.backend import publish_file_now
                    asyncio.create_task(publish_file_now(project_name, device_name, path))

            ui.button('Save', on_click=_save).props('color=primary')

    dialog.open()
    await dialog


async def _text_viewer_dialog(path: Path) -> None:
    """Read-only CodeMirror viewer for plain-text files."""
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return

    lang = _codemirror_language(path)
    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        with ui.row().classes('w-full items-center gap-2'):
            ui.label(f'View  {path.name}').classes('text-subtitle1 font-bold grow')
            ui.label('read-only').classes('text-caption text-grey-6')
        ui.separator()
        (
            ui.codemirror(value=content, language=lang, line_wrapping=True)
            .classes('w-full border rounded')
            .style('height: clamp(200px, 40vh, 500px)')
        )
        with ui.row().classes('w-full justify-end q-mt-sm'):
            ui.button('Close', on_click=dialog.close).props('flat')

    dialog.open()
    await dialog


async def _new_json_dialog(directory: Path, refresh_fn=None,
                           project_name: str | None = None,
                           device_name: str | None = None,
                           mqtt_enabled: bool = False) -> None:
    """Create a new JSON file using a CodeMirror editor."""
    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        ui.label('New JSON File').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
            filename_input = (
                ui.input(label='Filename', placeholder='config')
                .props('outlined dense')
                .classes('grow')
            )
            filename_preview = ui.label('').classes('text-caption text-grey-6 text-no-wrap')

        def _update_preview(e) -> None:
            raw = (e.value or '').strip()
            effective = raw if raw.endswith('.json') else (f'{raw}.json' if raw else '')
            filename_preview.text = f'→ {effective}' if effective else ''

        filename_input.on_value_change(_update_preview)

        editor = (
            ui.codemirror(value='{}', language='JSON', line_wrapping=True)
            .classes('w-full border rounded q-mt-xs')
            .style('height: clamp(160px, 30vh, 400px)')
        )
        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            async def _create() -> None:
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
                    ui.notify(f'{fname} already exists — use the edit button', type='warning')
                    return
                tmp = dest.with_suffix('.json.tmp')
                try:
                    tmp.write_text(
                        json.dumps(parsed, indent=2, ensure_ascii=False) + '\n',
                        encoding='utf-8',
                    )
                    tmp.rename(dest)
                except OSError as exc:
                    tmp.unlink(missing_ok=True)
                    ui.notify(f'Create failed: {exc}', type='negative')
                    return
                ui.notify(f'Created {fname}', type='positive')
                dialog.close()
                if refresh_fn:
                    refresh_fn()
                # Trigger MQTT publish if enabled
                if mqtt_enabled and project_name and device_name:
                    from app.core.file.backend import publish_file_now
                    asyncio.create_task(publish_file_now(project_name, device_name, dest))

            ui.button('Create', on_click=_create).props('color=primary')

    dialog.open()
    await dialog


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def _device_files_card(project_name: str, device_name: str,
                       mqtt_enabled: bool = False) -> None:
    from app.core.file.backend import get_file_config
    max_upload = get_file_config(project_name).max_upload_size
    device_path = get_device_path(project_name, device_name)

    with ui.expansion('Device Files', value=True).classes('w-full').props(
            'dense header-class="text-subtitle1 font-bold"'):
        ui.markdown(
            'Files stored in the device directory. '
            'Devices can upload (PUT) and download (GET) these via the API.'
        ).classes('text-caption q-ma-none')

        @ui.refreshable
        def file_list() -> None:
            from app.core.file.backend import load_file_state
            state = load_file_state(project_name, device_name) if mqtt_enabled else {}
            files = _list_files(device_path)
            if not files:
                ui.label('No files yet.').classes('text-caption text-grey-6 q-mt-sm')
                return
            with ui.column().classes('w-full gap-1 q-mt-sm'):
                for p in files:
                    _file_row(p, refresh_fn=file_list.refresh,
                              project_name=project_name, device_name=device_name,
                              mqtt_enabled=mqtt_enabled, state=state)

        file_list()

        ui.separator().classes('q-mt-sm')
        with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
            ui.label('Upload').classes('text-caption text-grey-7')

            async def _new_json() -> None:
                await _new_json_dialog(device_path, file_list.refresh,
                                       project_name=project_name,
                                       device_name=device_name,
                                       mqtt_enabled=mqtt_enabled)
            ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

        ui.upload(
            on_upload=_make_upload_handler(device_path, lambda: file_list.refresh(),
                                           project_name=project_name,
                                           device_name=device_name,
                                           mqtt_enabled=mqtt_enabled),
            max_file_size=max_upload,
            auto_upload=True,
        ).props('flat dense').classes('w-full q-mt-xs')


def _project_files_card(project_name: str, device_name: str | None = None,
                        mqtt_enabled: bool = False) -> None:
    from app.core.file.backend import get_file_config
    max_upload = get_file_config(project_name).max_upload_size
    project_path = get_project_dir(project_name)

    with ui.expansion('Project Files', value=True).classes('w-full').props(
            'dense header-class="text-subtitle1 font-bold"'):
        ui.markdown(
            'Shared files in the project directory. '
            'Served to devices as a fallback when no device-specific copy exists.'
        ).classes('text-caption q-ma-none')

        @ui.refreshable
        def file_list() -> None:
            from app.core.file.backend import load_file_state
            # Only show MQTT state if we have a device context and MQTT is enabled
            state = (load_file_state(project_name, device_name)
                     if (mqtt_enabled and device_name) else {})
            files = _list_files(project_path)
            if not files:
                ui.label('No project-level files.').classes('text-caption text-grey-6 q-mt-sm')
                return
            with ui.column().classes('w-full gap-1 q-mt-sm'):
                for p in files:
                    _file_row(p, refresh_fn=file_list.refresh,
                              project_name=project_name, device_name=device_name,
                              mqtt_enabled=(mqtt_enabled and device_name is not None),
                              state=state)

        file_list()

        ui.separator().classes('q-mt-sm')
        with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
            ui.label('Upload').classes('text-caption text-grey-7')

            async def _new_json() -> None:
                await _new_json_dialog(project_path, file_list.refresh,
                                       project_name=project_name,
                                       device_name=device_name,
                                       mqtt_enabled=(mqtt_enabled and device_name is not None))
            ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

        ui.upload(
            on_upload=_make_upload_handler(project_path, lambda: file_list.refresh(),
                                           project_name=project_name,
                                           device_name=device_name,
                                           mqtt_enabled=(mqtt_enabled and device_name is not None)),
            max_file_size=max_upload,
            auto_upload=True,
        ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_upload_handler(directory: Path, refresh_fn,
                         project_name: str | None = None,
                         device_name: str | None = None,
                         mqtt_enabled: bool = False):
    """Return an upload event handler that writes uploaded files to *directory* atomically."""
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
            refresh_fn()
            # Trigger MQTT publish if enabled
            if mqtt_enabled and project_name and device_name:
                from app.core.file.backend import publish_file_now
                asyncio.create_task(publish_file_now(project_name, device_name, dest))
        except Exception as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
            tmp.unlink(missing_ok=True)
        finally:
            e.sender.reset()
    return _handle


def _file_row(path: Path, refresh_fn=None,
              project_name: str | None = None,
              device_name: str | None = None,
              mqtt_enabled: bool = False,
              state: dict | None = None) -> None:
    size_kb = path.stat().st_size / 1024
    size_str = f'{size_kb:.1f} KB' if size_kb < 1024 else f'{size_kb / 1024:.1f} MB'
    is_json = path.suffix.lower() == '.json'
    is_text = not is_json and _is_viewable(path)

    if state is None:
        state = {}

    filename = path.name
    file_state = state.get(filename, {})
    published_at_str = file_state.get('published_at')

    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        icon = 'data_object' if is_json else ('article' if is_text else 'insert_drive_file')
        ui.icon(icon).classes('text-grey-6 text-sm')

        with ui.column().classes('grow gap-0'):
            ui.label(path.name).classes('text-body2')
            if mqtt_enabled and published_at_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(published_at_str)
                    ui.label(f'Published: {render_datetime(dt)}').classes('text-caption text-grey-6')
                except (ValueError, TypeError):
                    pass

        ui.label(size_str).classes('text-caption text-grey-7')

        if is_json:
            async def _edit(p=path) -> None:
                await _json_editor_dialog(p, refresh_fn,
                                          project_name=project_name,
                                          device_name=device_name,
                                          mqtt_enabled=mqtt_enabled)
            ui.button(icon='edit').props('flat dense size=sm').tooltip('Edit JSON').on_click(_edit)
        elif is_text:
            async def _view(p=path) -> None:
                await _text_viewer_dialog(p)
            ui.button(icon='visibility').props('flat dense size=sm').tooltip('View').on_click(_view)

        ui.button(icon='download').props('flat dense size=sm').tooltip('Download').on_click(
            lambda _, p=path: _download_file(p)
        )

        if mqtt_enabled and project_name and device_name:
            async def _force_publish(p=path) -> None:
                from app.core.file.backend import publish_file_now
                published = await publish_file_now(project_name, device_name, p)
                if published:
                    ui.notify(f'Published {p.name} to device via MQTT', type='positive')
                    if refresh_fn:
                        refresh_fn()
                else:
                    ui.notify('MQTT publish failed (not connected?)', type='warning')
            ui.button(icon='cloud_upload').props('flat dense size=sm').tooltip(
                'Force publish to device via MQTT'
            ).on_click(_force_publish)

        async def _del(p=path) -> None:
            await _delete_file(p, refresh_fn)
        ui.button(icon='delete').props('flat dense size=sm color=negative').tooltip('Delete').on_click(_del)


def _download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


async def _delete_file(path: Path, refresh_fn=None) -> None:
    if not await confirm_dialog(
        'Delete File',
        f'Delete **{path.name}**? This is irreversible.',
        ok_label='Delete',
        ok_color='negative',
    ):
        return
    try:
        path.unlink()
        ui.notify(f'Deleted {path.name}', type='positive')
        if refresh_fn:
            refresh_fn()
    except Exception as e:
        ui.notify(f'Delete failed: {e}', type='negative')


def _list_files(directory: Path) -> list[Path]:
    """Return non-hidden files with valid upload filenames, sorted by name."""
    if not directory.is_dir():
        return []
    return sorted(
        [p for p in directory.iterdir() if p.is_file() and is_valid_upload_filename(p.name)],
        key=lambda p: p.name,
    )
