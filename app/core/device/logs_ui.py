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

_LEVEL_COLORS = {
    '(E)': 'text-red',
    '(W)': 'text-orange',
    '(I)': 'text-blue',
    '(D)': 'text-green',
    '(V)': 'text-grey',
}


async def device_logs_panel(project_name: str, device_name: str) -> None:
    """Content of the Logs tab."""
    device_path = get_device_path(project_name, device_name)
    log_file = device_path / '.device.log'

    ui.label('Log explorer').classes('text-h6')
    _LogViewer(log_file)

    # Archived log files (rotation)
    archives = sorted(device_path.glob('.device.log.????-??'), reverse=True)
    if archives:
        ui.label('Archived Logs').classes('text-h6')
        for archive in archives:
            _archive_row(archive)


class _LogViewer:
    """Stateful UI component for the log viewer."""

    def __init__(self, log_file: Path) -> None:
        self.log_file: Path = log_file
        self._auto_refresh: bool = True
        self._n_lines: int = _DEFAULT_LINES
        self._pos: int = 0
        self._search_str: str = ''

        # Controls
        with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
            self.n_select = ui.select(
                [50, 100, 200, 500, 1000],
                value=self._n_lines,
                label='Lines',
            ).props('dense outlined').classes('w-28')
            self.n_select.on_value_change(self.on_n_change)

            self.search_input = ui.input(placeholder='Filter…').props('dense outlined clearable').classes('grow')
            self.search_input.on_value_change(self.on_search_change)

            ui.button(icon='refresh').props('dense flat').tooltip('Refresh now').on_click(
                lambda: self._reload_log()
            )

            self.auto_refresh_toggle = ui.switch(value=self._auto_refresh).tooltip('Auto-refresh')
            self.auto_refresh_toggle.bind_value(self, '_auto_refresh')

            ui.button(icon='download').props('dense flat').tooltip('Download log').on_click(
                lambda: _download_log(self.log_file)
            )

        self.log_area = ui.log().classes('w-full').style(
            'font-size: 0.75rem; min-height: 220px; '
            'height: calc(100dvh - 290px); max-height: calc(100vh - 290px); '
            'overflow-y: auto; white-space: pre-wrap; word-break: break-all;'
        )
        self._reload_log()
        ui.timer(_REFRESH_INTERVAL, self._on_refresh)

    def on_n_change(self,e ) -> None:
        self._n_lines = e.value
        self._reload_log()

    def on_search_change(self, e) -> None:
        self._search_str = e.value or ''
        self._reload_log()

    async def _on_refresh(self) -> None:
        """Refresh the log area when auto-refresh is enabled."""
        if self._auto_refresh:
            self._refresh_log()

    def _push_lines(self, lines: list[str]) -> None:
        """Push lines to the log area, with colorization."""
        for line in lines:
            if not line.strip():
                continue
            if self._search_str and self._search_str.lower() not in line.lower():
                continue
            color_class = next((c for k, c in _LEVEL_COLORS.items() if k in line), '')
            self.log_area.push(line, classes=color_class)

    def _reload_log(self) -> None:
        """Reload the log file (e.g. after rotation)."""
        self.log_area.clear()
        self._pos = 0
        if not self.log_file.is_file():
            self.log_area.push('(No log file yet — enable File logging in project settings)')
        else:
            try:
                p = self.log_file.stat().st_size
                lines = self.log_file.read_text(encoding='utf-8', errors='replace').splitlines()
                lines = lines[-self._n_lines:] if len(lines) > self._n_lines else lines
                self._push_lines(lines)
                self._pos = p
            except OSError as e:
                self.log_area.push(f'(Cannot read log: {e})')

    def _refresh_log(self) -> None:
        """Refresh the log area with new lines."""
        if not self.log_file.is_file():
            return
        try:
            p = self.log_file.stat().st_size
            if p < self._pos:
                # Log file was rotated or truncated; reload everything
                self._reload_log()
            elif p > self._pos:
                # Read new lines from the log file
                with self.log_file.open('r', encoding='utf-8', errors='replace') as f:
                    f.seek(self._pos)
                    new_lines = f.read().splitlines()
                    self._push_lines(new_lines)
                self._pos = p
        except OSError as e:
            self.log_area.push(f'(Cannot read log: {e})')


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
        ui.icon('archive').classes('text-grey-7 text-sm')
        ui.label(label).classes('grow text-body2')
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='download').props('dense flat size=sm').tooltip('Download').on_click(
            lambda _, p=archive: _download_log(p)
        )
