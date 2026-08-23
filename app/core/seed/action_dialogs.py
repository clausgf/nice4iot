"""The two device-seeding action dialogs beyond plain "add a device record":

- ``ap_qr_dialog``: shows the AP+captive-portal deep link as a QR code, for a
  device that will be provisioned via its own SoftAP + on-device form.
- ``web_serial_flash_dialog``: flashes esp32paper's merged full-flash image
  (bootloader + partition table + boot_app0 + app) plus a freshly generated
  NVS seed image over Web Serial (ESP Web Tools), in one go. The NVS offset
  is read from that same build's own published partition table, not
  hardcoded — see app.core.seed.boards' module docstring.

Both resolve the device's *effective* seed (project Seed settings + WiFi
override, see app.core.seed.backend.get_effective_seed) against an
operator-picked provisioning token — nothing here is persisted beyond the
existing Seed/token files; the dialogs are pure UI plus one-shot generation.
"""
import datetime
import logging

import anyio
from nicegui import ui

from app.config import app_config
from app.core.device.backend import get_file_path
from app.core.seed.ap_setup import build_ap_setup_url, qr_png_data_uri
from app.core.seed.backend import get_effective_seed
from app.core.seed.boards import BOARDS
from app.core.seed.manifest import manifest_data_uri
from app.core.seed.nvs import NvsGenerationError, build_nvs_image
from app.core.seed.partition_table import PartitionTableError, find_partition
from app.core.token.backend import create_token, get_provisioning_token_adapter
from app.exceptions import NotFoundError
from app.util import render_datetime

log = logging.getLogger('uvicorn')

_ENSURE_ESP_WEB_TOOLS_JS = '''
if (!window.__espWebToolsLoaded) {
    window.__espWebToolsLoaded = true;
    const s = document.createElement('script');
    s.type = 'module';
    s.src = '/static/esp-web-tools/install-button.js';
    document.head.appendChild(s);
}
'''

# Simple print-isolation: only .seed-print-area is visible when printing.
# Injected via JS (not ui.add_head_html), which only affects a page's initial
# server-rendered <head> — these dialogs are opened later, on an already-
# connected page, so a script/style added then must be inserted client-side.
_ENSURE_PRINT_CSS_JS = '''
if (!window.__seedPrintCssLoaded) {
    window.__seedPrintCssLoaded = true;
    const style = document.createElement('style');
    style.textContent = `
        @media print {
          body * { visibility: hidden; }
          .seed-print-area, .seed-print-area * { visibility: visible; }
          .seed-print-area { position: absolute; top: 0; left: 0; width: 100%; }
        }
    `;
    document.head.appendChild(style);
}
'''


def _active_token_options(project_name: str) -> dict[str, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    adapter = get_provisioning_token_adapter(project_name)
    return {
        token.value: f'{token.fingerprint} · expires {render_datetime(token.expires_at)}'
        for _key, token in adapter.items()
        if token.is_active and token.expires_at > now
    }


class _TokenPicker:
    """A provisioning-token <select> plus a "create new" button, shared by
    both dialogs below. `.value` is the currently selected token, or ''."""

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        with ui.row().classes('items-center gap-2 w-full no-wrap'):
            self.select = ui.select(_active_token_options(project_name),
                                     label='Provisioning token').classes('grow')
            ui.button(icon='add', on_click=self._create) \
                .props('flat dense round').tooltip('Create a new provisioning token')
        self._pick_first()

    def _pick_first(self) -> None:
        options = self.select.options
        if options:
            self.select.value = next(iter(options))

    def _create(self) -> None:
        adapter = get_provisioning_token_adapter(self.project_name)
        token = create_token(expires_in=app_config.provisioning_token_expires_in,
                             length=app_config.provisioning_token_length)
        adapter.create(token)
        self.select.set_options(_active_token_options(self.project_name), value=token.value)
        ui.notify('Provisioning token created', type='positive')

    @property
    def value(self) -> str:
        return self.select.value or ''


# ---------------------------------------------------------------------------
# Variant 3: AP + captive-portal form (device-side; nice4iot only displays)
# ---------------------------------------------------------------------------

def ap_qr_dialog(project_name: str, device_name: str) -> ui.dialog:
    """Explanation + deep-link QR for the device's own SoftAP setup portal."""
    ui.run_javascript(_ENSURE_PRINT_CSS_JS)
    dialog = ui.dialog().props('persistent')
    with dialog, ui.card().classes('seed-print-area w-full max-w-lg'):
        ui.label(f'AP + Form Setup — {device_name}').classes('text-h6')
        ui.markdown(
            '1. Power on the device. With no WiFi seeded, it opens its own '
            '**open** (no password) WiFi network named '
            '`arduino4iot-setup-<last 4 hex of its MAC>` — check the device '
            'label or your WiFi list for the exact name.\n'
            '2. Join that network with your phone or laptop.\n'
            '3. Scan the code below (or open the link) to pre-fill the setup '
            'form, then tap **Save** on the device. Nothing is written until '
            'you do.'
        ).classes('text-body2')

        qr_image = ui.image().classes('w-48 h-48 self-center')
        url_label = ui.label().classes('text-caption text-grey-7 break-all')

        picker = _TokenPicker(project_name)

        def _refresh() -> None:
            seed = get_effective_seed(project_name, device_name, picker.value)
            url = build_ap_setup_url(seed)
            qr_image.set_source(qr_png_data_uri(url))
            url_label.text = url

        picker.select.on_value_change(lambda _e: _refresh())
        _refresh()

        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Print', icon='print', on_click=lambda: ui.run_javascript('window.print()')) \
                .props('flat')
            ui.button('Close', on_click=dialog.close).props('flat')
    return dialog


# ---------------------------------------------------------------------------
# Variant 2: Web-Serial-Flash (app image + a freshly generated NVS image)
# ---------------------------------------------------------------------------

def web_serial_flash_dialog(project_name: str, device_name: str) -> ui.dialog:
    """Flash esp32paper's merged full-flash image for the chosen board plus a
    generated NVS seed image over Web Serial, via a vendored ESP Web Tools
    install button. The NVS offset/size come from that build's own published
    partition table (app.core.seed.partition_table), not a hardcoded value.

    Requires the project/device Firmware source to have pulled the board's
    `merged-<board>.bin` and `partitions-<board>.csv` — e.g. asset_name
    `merged-*.bin` alongside `partitions-*.csv` (or one wildcard covering
    both, such as `*.bin` plus a separate source for the `.csv`), so a
    wildcard pull lands every board's files side by side. See
    app.core.firmware for the "download every matching asset" pull behaviour.
    """
    ui.run_javascript(_ENSURE_ESP_WEB_TOOLS_JS)
    dialog = ui.dialog().props('persistent')
    with dialog, ui.card().classes('w-full max-w-lg'):
        ui.label(f'Web-Serial-Flash — {device_name}').classes('text-h6')
        ui.markdown(
            'Flashes the full merged image (bootloader, partition table, and '
            'app) for the chosen board, plus a freshly generated NVS seed '
            'image, in one pass over a USB-serial connection from this '
            'browser — works on a blank board, no prior flash needed. '
            'Requires Chrome, Edge, or another Chromium-based browser, and '
            'HTTPS (or localhost).'
        ).classes('text-body2')

        board_select = ui.select({b.id: b.label for b in BOARDS.values()},
                                 label='Board', value=next(iter(BOARDS))).classes('w-full')
        picker = _TokenPicker(project_name)
        status_label = ui.label().classes('text-caption text-grey-7')
        prepared: dict[str, str | None] = {'manifest_uri': None}

        @ui.refreshable
        def install_area() -> None:
            if prepared['manifest_uri'] is None:
                ui.label('Click "Prepare" to build the flash image.').classes('text-caption text-grey-7')
            else:
                # No custom slot="activate" button: ESP Web Tools' own default
                # button carries its shadow-DOM styling (a slotted light-DOM
                # button would render as an unstyled native <button> instead —
                # page CSS resets it, and the component's CSS can't reach past
                # the shadow boundary into slotted content).
                ui.label('Ready — click Connect to open the flashing dialog:') \
                    .classes('text-caption text-grey-7')
                ui.html(f'<esp-web-install-button manifest="{prepared["manifest_uri"]}">'
                       f'</esp-web-install-button>', sanitize=False)

        install_area()

        async def _prepare() -> None:
            board = BOARDS[board_select.value]
            token = picker.value
            if not token:
                ui.notify('Create or select a provisioning token first', type='warning')
                return
            status_label.text = 'Resolving the merged image and partition table…'
            try:
                merged_path = await anyio.to_thread.run_sync(
                    lambda: get_file_path(project_name, device_name, board.merged_asset_name))
                merged_image = await anyio.to_thread.run_sync(merged_path.read_bytes)
                partitions_path = await anyio.to_thread.run_sync(
                    lambda: get_file_path(project_name, device_name, board.partitions_asset_name))
                partitions_csv = await anyio.to_thread.run_sync(partitions_path.read_text)
                nvs_offset, nvs_size = find_partition(partitions_csv, 'nvs')
            except NotFoundError as e:
                status_label.text = ''
                ui.notify(f'{board.merged_asset_name} / {board.partitions_asset_name} not found for '
                          f'this device or project — pull them via the Firmware source first: {e}',
                          type='negative')
                return
            except PartitionTableError as e:
                status_label.text = ''
                ui.notify(f'Could not read the nvs partition from {board.partitions_asset_name}: {e}',
                          type='negative')
                return

            status_label.text = 'Building the NVS seed image…'
            try:
                seed = get_effective_seed(project_name, device_name, token)
                nvs_image = await anyio.to_thread.run_sync(build_nvs_image, seed, nvs_size)
            except NvsGenerationError as e:
                status_label.text = ''
                ui.notify(f'NVS image generation failed: {e}', type='negative')
                return

            prepared['manifest_uri'] = manifest_data_uri(board, merged_image, nvs_image, nvs_offset)
            status_label.text = (f'Ready: merged image {len(merged_image) / 1024:.0f} KiB, '
                                 f'NVS {len(nvs_image) / 1024:.0f} KiB @ 0x{nvs_offset:x}.')
            install_area.refresh()

        with ui.row().classes('w-full justify-between items-center gap-2 q-mt-sm'):
            ui.button('Prepare', icon='build', on_click=_prepare).props('flat')
            ui.button('Close', on_click=dialog.close).props('flat')
    return dialog
