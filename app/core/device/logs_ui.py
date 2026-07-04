"""
Device Logs Tab — live tail of the per-device log file.

Log file: <projects_dir>/<project>/<device>/.device.log
Written by FileLogBackend when file logging is active in the project.
Rotation archives are also listed so older logs can be browsed.
"""
from pathlib import Path

from nicegui import ui

from app.core.device.backend import get_device_path

import logging
log = logging.getLogger("uvicorn")

_DEFAULT_LINES = 200
_REFRESH_INTERVAL = 5.0   # seconds


def device_logs_panel(project_name: str, device_name: str) -> None:
    """Content of the Logs tab."""
    device_path = get_device_path(project_name, device_name)
    log_file = device_path / '.device.log'

    with ui.card().classes('w-full'):
        with ui.expansion('Live Log', value=True).classes('w-full').props(
                'dense header-class="text-subtitle1 font-bold"'):
            _log_viewer(log_file)

    # Archived log files (rotation)
    archives = sorted(device_path.glob('.device.log.????-??'), reverse=True)
    if archives:
        with ui.card().classes('w-full q-mt-sm'):
            with ui.expansion('Archived Logs', value=False).classes('w-full').props(
                    'dense header-class="text-subtitle1 font-bold"'):
                for archive in archives:
                    _archive_row(archive)


def _log_viewer(log_file: Path) -> None:
    state = {'follow': True, 'n_lines': _DEFAULT_LINES}

    # Controls
    with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
        n_select = ui.select(
            [50, 100, 200, 500, 1000],
            value=state['n_lines'],
            label='Lines',
        ).props('dense outlined').classes('w-28')

        search_input = ui.input(placeholder='Filter…').props('dense outlined clearable').classes('grow')

        follow_toggle = ui.checkbox('Auto-refresh', value=state['follow'])
        follow_toggle.bind_value(state, 'follow')

        ui.button(icon='refresh').props('dense flat').tooltip('Refresh now').on_click(
            lambda: log_area.set_content(_read_tail(log_file, state['n_lines'], search_input.value))
        )

        ui.button(icon='download').props('dense flat').tooltip('Download log').on_click(
            lambda: _download_log(log_file)
        )

    def on_n_change(e) -> None:
        state['n_lines'] = e.value
        log_area.set_content(_read_tail(log_file, state['n_lines'], search_input.value))

    def on_search_change(e) -> None:
        log_area.set_content(_read_tail(log_file, state['n_lines'], e.value or ''))

    n_select.on_value_change(on_n_change)
    search_input.on_value_change(on_search_change)

    # Log area — monospace pre block inside a scrollable div
    initial = _read_tail(log_file, state['n_lines'])
    log_area = ui.code(initial, language='').classes('w-full').style(
        'font-size: 0.75rem; max-height: 500px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;'
    )

    # Auto-refresh timer — only active while the tab panel is mounted
    async def _auto_refresh() -> None:
        if state['follow']:
            content = _read_tail(log_file, state['n_lines'], search_input.value)
            if content != log_area.content:
                log_area.set_content(content)

    ui.timer(_REFRESH_INTERVAL, _auto_refresh)


def _read_tail(log_file: Path, n: int, search: str = '') -> str:
    if not log_file.is_file():
        return '(No log file yet — enable File logging in project settings)'
    try:
        lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
        tail = lines[-n:] if len(lines) > n else lines
        if search:
            tail = [l for l in tail if search.lower() in l.lower()]
        if not tail:
            return '(No matching lines)' if search else '(Log file is empty)'
        return '\n'.join(tail)
    except OSError as e:
        return f'(Cannot read log: {e})'


def _download_log(log_file: Path) -> None:
    try:
        data = log_file.read_bytes()
        ui.download(data, filename=log_file.name)
    except (OSError, FileNotFoundError) as e:
        ui.notify(f'Download failed: {e}', type='negative')


def _archive_row(archive: Path) -> None:
    label = archive.name.replace('.device.log.', '')
    size_kb = archive.stat().st_size / 1024
    size_str = f'{size_kb:.0f} KB' if size_kb < 1024 else f'{size_kb / 1024:.1f} MB'
    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon('archive').classes('text-grey-6 text-sm')
        ui.label(label).classes('grow text-body2')
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download').on_click(
            lambda _, p=archive: _download_log(p)
        )
