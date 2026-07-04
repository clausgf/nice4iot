"""
Device Files Tab — browse, upload, download and delete device-specific files.

Files live at  <projects_dir>/<project>/<device>/<filename>
Project-level  <projects_dir>/<project>/<filename>  files are shown read-only
as fallback (devices download them when no device-specific copy exists).
"""
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
# Device files (writable)
# ---------------------------------------------------------------------------

def _device_files_card(project_name: str, device_name: str) -> None:
    device_path = get_device_path(project_name, device_name)

    with ui.expansion('Device Files', value=True).classes('w-full').props('dense header-class="text-subtitle1 font-bold"'):
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
                for path in files:
                    _file_row(path, project_name, device_name, file_list.refresh)

        file_list()

        # Upload widget
        ui.separator().classes('q-mt-sm')
        ui.label('Upload file').classes('text-caption text-grey-7 q-mt-xs')

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


def _file_row(path: Path, project_name: str, device_name: str, refresh_fn) -> None:
    size_kb = path.stat().st_size / 1024
    size_str = f'{size_kb:.1f} KB' if size_kb < 1024 else f'{size_kb / 1024:.1f} MB'

    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon('insert_drive_file').classes('text-grey-6 text-sm')
        ui.label(path.name).classes('grow text-body2')
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download').on_click(
            lambda _, p=path: _download_file(p)
        )
        ui.button(icon='delete').props('flat dense size=sm color=negative').tooltip('Delete').on_click(
            lambda _, p=path: _delete_file(p, project_name, device_name, refresh_fn)
        )


def _download_file(path: Path) -> None:
    try:
        data = path.read_bytes()
        ui.download(data, filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


async def _delete_file(path: Path, project_name: str, device_name: str, refresh_fn) -> None:
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
        refresh_fn()
    except Exception as e:
        ui.notify(f'Delete failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Project files (read-only fallback)
# ---------------------------------------------------------------------------

def _project_files_card(project_name: str) -> None:
    project_path = get_project_dir(project_name)

    with ui.expansion('Project Files (fallback)', value=True).classes('w-full').props('dense header-class="text-subtitle1 font-bold"'):
        ui.markdown(
            'Read-only files in the project directory. '
            'Served to devices as a fallback when no device-specific copy exists.'
        ).classes('text-caption q-ma-none')

        files = _list_files(project_path)
        if not files:
            ui.label('No project-level files.').classes('text-caption text-grey-6 q-mt-sm')
            return
        with ui.column().classes('w-full gap-1 q-mt-sm'):
            for path in files:
                _project_file_row(path)


def _project_file_row(path: Path) -> None:
    size_kb = path.stat().st_size / 1024
    size_str = f'{size_kb:.1f} KB' if size_kb < 1024 else f'{size_kb / 1024:.1f} MB'
    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon('folder_open').classes('text-grey-6 text-sm')
        ui.label(path.name).classes('grow text-body2 text-grey-7')
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download').on_click(
            lambda _, p=path: _download_file(p)
        )


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
