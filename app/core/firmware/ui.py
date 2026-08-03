"""Firmware source card for the Files tabs (project and device)."""
import logging
from pathlib import Path
from typing import Callable

from nicegui import ui
from niceview import ConflictError, ModelForm, StorageError

from app.core.firmware.backend import (
    FirmwareError,
    get_firmware_adapter,
    load_firmware_state,
    peek_latest_tag,
    pull_firmware,
)
from app.core.firmware.models import FirmwareSource
from app.util import render_datetime

log = logging.getLogger('uvicorn')


def firmware_source_card(dir_path: Path, *, project_name: str, device_name: str | None,
                         refresh_files: Callable[[], None]) -> None:
    """Render the firmware-source config form + pull controls.

    The caller provides the surrounding ``ui.card``. ``refresh_files`` re-renders
    the enclosing Files panel so a freshly pulled file appears in the list.
    """
    adapter = get_firmware_adapter(dir_path)
    config = adapter.read()

    ui.label('Firmware source').classes('font-bold')
    ui.markdown(FirmwareSource.Meta.description).classes('text-caption q-ma-none')

    def _save() -> None:
        try:
            adapter.save(config)
        except (ConflictError, StorageError) as e:
            ui.notify(str(e), color='negative')

    form = ModelForm.from_item(config, on_change=lambda e: _save())
    form.render()
    for widget in form.widgets.values():
        widget.props('outlined dense').classes('w-full')

    @ui.refreshable
    def status() -> None:
        state = load_firmware_state(dir_path)
        with ui.row().classes('items-center gap-2 q-mt-sm'):
            if state and state.tag:
                ui.icon('check_circle').classes('text-green-6')
                ui.label(f'Pulled: {state.tag}').classes('text-body2')
                ui.label(render_datetime(state.pulled_at)).classes('text-caption text-grey-6')
            else:
                ui.label('Nothing pulled yet').classes('text-body2 text-grey-6')

    status()
    latest_label = ui.label('').classes('text-caption text-grey-7 q-mt-xs')

    async def _check_latest() -> None:
        cfg = adapter.read()
        if not cfg.repo.strip():
            ui.notify('No repository configured', type='warning')
            return
        latest_label.text = 'Checking…'
        try:
            tag = await peek_latest_tag(cfg)
            latest_label.text = f'Latest available: {tag or "—"}'
        except FirmwareError as e:
            latest_label.text = ''
            ui.notify(f'Check failed: {e}', type='negative')

    async def _pull_now() -> None:
        cfg = adapter.read()
        if not cfg.repo.strip():
            ui.notify('No repository configured', type='warning')
            return
        try:
            result = await pull_firmware(dir_path, cfg, project_name=project_name,
                                         device_name=device_name)
            ui.notify(result.message, type='positive' if result.changed else 'info')
            status.refresh()
            if result.changed:
                refresh_files()
        except FirmwareError as e:
            ui.notify(f'Pull failed: {e}', type='negative')
        except Exception as e:  # unexpected — surface, don't crash the panel
            log.exception(f'firmware pull failed: {e}')
            ui.notify(f'Pull failed: {e}', type='negative')

    with ui.row().classes('gap-2 q-mt-xs'):
        ui.button('Pull now', icon='download', on_click=_pull_now).props('dense')
        ui.button('Check latest', icon='refresh', on_click=_check_latest).props('dense flat')
