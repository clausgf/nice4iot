"""
Device Files Tab — browse, upload, download, delete and edit device and project files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write; served
               to devices as a fallback when no device-specific copy exists)

JSON files additionally offer an inline editor with syntax validation.
"""
import json
from pathlib import Path

from nicegui import ui

from app.config import app_config
from app.core.device.backend import get_device_path
from app.paths import project_dir as get_project_dir
from app.ui.util import build_dialog
from app.util import is_valid_upload_filename

import logging
log = logging.getLogger("uvicorn")


def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the Files tab."""
    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with ui.card().classes('w-full'):
            _device_files_card(project_name, device_name)
        with ui.card().classes('w-full'):
            _project_files_card(project_name)


# ---------------------------------------------------------------------------
# JSON editor dialog
# ---------------------------------------------------------------------------

async def _json_editor_dialog(path: Path, refresh_fn=None) -> None:
    """Open a modal editor for a JSON file.  Creates the file on first save."""
    try:
        raw = path.read_text(encoding='utf-8') if path.is_file() else '{}'
        content = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        content = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '{}'

    with ui.dialog() as dialog, ui.card().classes('w-full').style('min-width:640px; max-width:960px'):
        ui.label(f'Edit {path.name}').classes('text-subtitle1 font-bold')
        ui.separator()
        textarea = (
            ui.textarea(value=content)
            .props('outlined')
            .classes('w-full font-mono')
            .style('min-height:320px; max-height:600px; overflow-y:auto; font-size:0.75rem')
        )
        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            async def _save() -> None:
                try:
                    parsed = json.loads(textarea.value)
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
                    ui.notify(f'Save failed: {exc}', type='negative')
                    tmp.unlink(missing_ok=True)
                    return
                ui.notify(f'Saved {path.name}', type='positive')
                dialog.close()
                if refresh_fn:
                    refresh_fn()

            ui.button('Save', on_click=_save).props('color=primary')

    dialog.open()
    await dialog


async def _new_json_dialog(directory: Path, refresh_fn=None) -> None:
    """Open a dialog to create a new JSON file in *directory*."""
    with ui.dialog() as dialog, ui.card().classes('w-full').style('min-width:640px; max-width:960px'):
        ui.label('New JSON File').classes('text-subtitle1 font-bold')
        ui.separator()
        filename_input = (
            ui.input(label='Filename', placeholder='config.json')
            .props('outlined dense')
            .classes('w-full q-mt-xs')
        )
        textarea = (
            ui.textarea(value='{}')
            .props('outlined')
            .classes('w-full font-mono q-mt-xs')
            .style('min-height:200px; max-height:400px; overflow-y:auto; font-size:0.75rem')
        )
        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            async def _create() -> None:
                fname = filename_input.value.strip()
                if not fname:
                    ui.notify('Please enter a filename', type='warning')
                    return
                if not fname.endswith('.json'):
                    fname += '.json'
                if not is_valid_upload_filename(fname):
                    ui.notify(f'Invalid filename: {fname!r}', type='negative')
                    return
                try:
                    parsed = json.loads(textarea.value)
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
                    ui.notify(f'Create failed: {exc}', type='negative')
                    tmp.unlink(missing_ok=True)
                    return
                ui.notify(f'Created {fname}', type='positive')
                dialog.close()
                if refresh_fn:
                    refresh_fn()

            ui.button('Create', on_click=_create).props('color=primary')

    dialog.open()
    await dialog


# ---------------------------------------------------------------------------
# Device files (read/write)
# ---------------------------------------------------------------------------

def _device_files_card(project_name: str, device_name: str) -> None:
    device_path = get_device_path(project_name, device_name)

    with ui.expansion('Device Files', value=True).classes('w-full').props(
            'dense header-class="text-subtitle1 font-bold"'):
        ui.markdown(
            'Files stored in the device directory. '
            'Devices can upload (PUT) and download (GET) these via the API.'
        ).classes('text-caption q-ma-none')

        @ui.refreshable
        def file_list() -> None:
            files = _list_files(device_path)
            if not files:
                ui.label('No files yet.').classes('text-caption text-grey-6 q-mt-sm')
                return
            with ui.column().classes('w-full gap-1 q-mt-sm'):
                for p in files:
                    _file_row(p, refresh_fn=file_list.refresh)

        file_list()

        ui.separator().classes('q-mt-sm')
        with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
            ui.label('Upload').classes('text-caption text-grey-7')

            async def _new_json() -> None:
                await _new_json_dialog(device_path, file_list.refresh)

            ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

        def _handle_upload(e) -> None:
            filename = e.name
            if not is_valid_upload_filename(filename):
                ui.notify(f'Invalid filename: {filename!r}', type='negative')
                e.sender.reset()
                return
            dest = device_path / filename
            try:
                dest.write_bytes(e.content.read())
                ui.notify(f'Uploaded {filename}', type='positive')
                file_list.refresh()
            except Exception as ex:
                log.exception(f'Upload failed: {ex}')
                ui.notify(f'Upload failed: {ex}', type='negative')
            finally:
                e.sender.reset()

        ui.upload(
            on_upload=_handle_upload,
            max_file_size=app_config.max_file_upload_size,
            auto_upload=True,
        ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Project files (read/write + JSON editor)
# ---------------------------------------------------------------------------

def _project_files_card(project_name: str) -> None:
    project_path = get_project_dir(project_name)

    with ui.expansion('Project Files', value=True).classes('w-full').props(
            'dense header-class="text-subtitle1 font-bold"'):
        ui.markdown(
            'Shared files in the project directory. '
            'Served to devices as a fallback when no device-specific copy exists.'
        ).classes('text-caption q-ma-none')

        @ui.refreshable
        def file_list() -> None:
            files = _list_files(project_path)
            if not files:
                ui.label('No project-level files.').classes('text-caption text-grey-6 q-mt-sm')
                return
            with ui.column().classes('w-full gap-1 q-mt-sm'):
                for p in files:
                    _file_row(p, refresh_fn=file_list.refresh)

        file_list()

        ui.separator().classes('q-mt-sm')
        with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
            ui.label('Upload').classes('text-caption text-grey-7')

            async def _new_json() -> None:
                await _new_json_dialog(project_path, file_list.refresh)

            ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

        def _handle_project_upload(e) -> None:
            filename = e.name
            if not is_valid_upload_filename(filename):
                ui.notify(f'Invalid filename: {filename!r}', type='negative')
                e.sender.reset()
                return
            dest = project_path / filename
            try:
                dest.write_bytes(e.content.read())
                ui.notify(f'Uploaded {filename}', type='positive')
                file_list.refresh()
            except Exception as ex:
                log.exception(f'Upload failed: {ex}')
                ui.notify(f'Upload failed: {ex}', type='negative')
            finally:
                e.sender.reset()

        ui.upload(
            on_upload=_handle_project_upload,
            max_file_size=app_config.max_file_upload_size,
            auto_upload=True,
        ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Shared file row
# ---------------------------------------------------------------------------

def _file_row(path: Path, refresh_fn=None) -> None:
    size_kb = path.stat().st_size / 1024
    size_str = f'{size_kb:.1f} KB' if size_kb < 1024 else f'{size_kb / 1024:.1f} MB'
    is_json = path.suffix.lower() == '.json'

    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        icon = 'data_object' if is_json else 'insert_drive_file'
        ui.icon(icon).classes('text-grey-6 text-sm')
        ui.label(path.name).classes('grow text-body2')
        ui.label(size_str).classes('text-caption text-grey-7')

        if is_json:
            async def _edit(p=path) -> None:
                await _json_editor_dialog(p, refresh_fn)
            ui.button(icon='edit').props('flat dense size=sm').tooltip('Edit JSON').on_click(_edit)

        ui.button(icon='download').props('flat dense size=sm').tooltip('Download').on_click(
            lambda _, p=path: _download_file(p)
        )

        async def _del(p=path) -> None:
            await _delete_file(p, refresh_fn)
        ui.button(icon='delete').props('flat dense size=sm color=negative').tooltip('Delete').on_click(_del)


def _download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


async def _delete_file(path: Path, refresh_fn=None) -> None:
    result = await build_dialog(
        'Delete File',
        f'Delete {path.name!r}? This is irreversible.',
        ['|1Cancel', '-Delete'],
    )
    if result != 'Delete':
        return
    try:
        path.unlink()
        ui.notify(f'Deleted {path.name}', type='positive')
        if refresh_fn:
            refresh_fn()
    except Exception as e:
        ui.notify(f'Delete failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_files(directory: Path) -> list[Path]:
    """Return non-hidden files with valid upload filenames, sorted by name."""
    if not directory.is_dir():
        return []
    return sorted(
        [p for p in directory.iterdir() if p.is_file() and is_valid_upload_filename(p.name)],
        key=lambda p: p.name,
    )
