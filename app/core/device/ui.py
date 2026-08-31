import datetime
import html
from typing import Any, Callable, Optional, cast

import anyio
from nicegui import PageArguments, ui

from app.routes import device_url, project_url
from app.ui import config_expansion, refresh_breadcrumbs, show_sidebar, status_avatar
from app.core.device.models import Device, DeviceRuntime, ProjectDeviceRow
from app.core.device.backend import (
    create_device, delete_device, device_adapter, get_device,
    invalidate_device_list_cache, is_device_online, project_device_rows,
    read_runtime, rename_device,
)
from app.core.file.browser_ui import device_files_panel
from app.core.device.data_ui import dashboard_plot_card, device_data_panel
from app.core.device.logs_ui import device_logs_panel
from app.core.project.backend import get_project
from app.core.firmware.ui import firmware_source_card
from app.core.seed.ui import device_seed_override_card
from app.core.token.backend import get_device_token_adapter
from app.core.token.ui import TokenListCard
from app.paths import device_dir
from app.util import is_valid_name, render_datetime, render_datetime_age
from niceview import EditGridWrapper, ModelForm, ModelGrid
from niceview.dataadapter import ReloadableAdapter
from niceview.util import confirm_dialog, input_dialog
from app.extensions import (
    call_with_page_args, get_device_dashboard_cards, get_device_settings_cards, get_device_tabs,
    get_project_settings_cards, get_project_tabs, maybe_await,
)

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************
# Device sub-page (routing entry point — lives here, not in frontend.py)
# ***************************************************************************

async def device_subpage(
    args: PageArguments,
    nav: ui.element,
    sidebar: ui.element,
    drawer: ui.left_drawer,
    hamburger: ui.element,
    project_id: str,
    device_id: str,
    tab: Optional[str] = None,
) -> None:
    """Render the device page: header nav path + tabbed panels.

    Shows the parent project's sidebar (Devices highlighted) rather than
    growing a third sidebar level of its own — the device's own sections
    stay a horizontal tab strip in the content area, same as before.
    """
    refresh_breadcrumbs(nav, project_id=project_id, device_id=device_id)

    from app.core.project.ui import find_nav_item, project_nav_items  # local: project.ui imports this module
    project_tab_defs = await anyio.to_thread.run_sync(lambda: get_project_tabs(project_id))
    settings_card_defs = await anyio.to_thread.run_sync(lambda: get_project_settings_cards(project_id))
    items = project_nav_items(project_id, project_tab_defs, settings_card_defs)
    devices_item = find_nav_item(items, 'Devices')
    show_sidebar(drawer, hamburger, sidebar, project_id, items, active=devices_item)

    extension_tab_defs = await anyio.to_thread.run_sync(lambda: get_device_tabs(project_id))
    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        general_tab   = ui.tab('General')
        files_tab     = ui.tab('Files')
        data_tab      = ui.tab('Data')
        logs_tab      = ui.tab('Logs')
        extension_tabs = [(ui.tab(label, icon=icon), render_fn) for label, icon, render_fn in extension_tab_defs]
    tab = tab or dashboard_tab.label
    tabs.on_value_change(lambda e: ui.navigate.history.replace(device_url(project_id, device_id, tab=cast(str, e.value))))
    with ui.tab_panels(tabs, value=tab).classes('w-full'):
        with ui.tab_panel(dashboard_tab):
            await device_dashboard_panel(project_id, device_id, args)
        with ui.tab_panel(general_tab):
            await device_general_panel(project_id, device_id, args)
        with ui.tab_panel(files_tab):
            await device_files_panel(project_id, device_id)
        with ui.tab_panel(data_tab):
            await device_data_panel(project_id, device_id)
        with ui.tab_panel(logs_tab):
            await device_logs_panel(project_id, device_id)
        for extension_tab, render_fn in extension_tabs:
            with ui.tab_panel(extension_tab):
                await maybe_await(call_with_page_args(render_fn, args, project_id, device_id))


# ***************************************************************************
# Device Dashboard Panel
# ***************************************************************************

async def device_dashboard_panel(project_name: str, device_name: str, args: PageArguments) -> None:
    """Overview cards shown on the device Dashboard tab (auto-refreshes every 10 s)."""
    from app.core.alarm.ui import dashboard_alarms_card

    @ui.refreshable
    async def _content() -> None:
        from app.core.alarm.backend import get_device_offline_threshold
        from app.core.telemetry.backend import read_data_views
        device = get_device(project_name, device_name)
        threshold = await anyio.to_thread.run_sync(lambda: get_device_offline_threshold(project_name))
        runtime = await anyio.to_thread.run_sync(lambda: read_runtime(project_name, device_name))
        plot_views = await anyio.to_thread.run_sync(lambda: read_data_views(project_name, device_name))

        with ui.grid().classes('grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full'):
            await _status_card(device, project_name, threshold, runtime)
            await _timeline_card(device)
            for render_fn in await anyio.to_thread.run_sync(lambda: get_device_dashboard_cards(project_name)):
                await maybe_await(call_with_page_args(render_fn, args, project_name, device_name))
            for view in plot_views:
                if view.show_on_dashboard:
                    await dashboard_plot_card(project_name, device_name, view)

    await _content()
    ui.timer(10.0, _content.refresh)
    await dashboard_alarms_card(project_name, device_name)


def _format_metric(v: float) -> str:
    """Compact display for a cached numeric metric: no trailing '.0' for integral
    values (wifi_rssi -67, boot_count 42), trimmed decimals otherwise (battery 3.71)."""
    if v == int(v):
        return str(int(v))
    return f'{v:.3f}'.rstrip('0').rstrip('.')


async def _status_card(device: Device, project_name: str, offline_threshold: datetime.timedelta,
                       runtime: DeviceRuntime | None = None) -> None:
    from app.core.alarm.backend import get_alarm_count
    online = is_device_online(device, offline_threshold)
    alarm_count = get_alarm_count(project_name, device.name)

    with ui.card().tight().classes('w-full'):
        with ui.card_section().props('dense').classes('w-full'):
            # Row 0: card name - icons for alarms, active, online
            with ui.row().classes('w-full gap-1 items-center'):
                ui.label('Device status').classes('text-subtitle1 font-bold')
                ui.space()
                if alarm_count:
                    ui.chip(str(alarm_count)).props('dense color=negative text-color=white icon=notifications_active') \
                        .tooltip(f'{alarm_count} active alarm(s)')
                status_avatar(True if device.is_active else None, ['toggle_off', 'toggle_on'], 'Device')
                status_avatar(True if online else None, ['cloud_off', 'cloud'], ['Offline', 'Online'])
            ui.separator().classes('q-mt-xs q-mb-xs')

            # Row 1: device name, tags
            with ui.row().classes('w-full gap-0 q-mt-sm items-center'):
                ui.label(device.name).classes('text-subtitle1 font-bold')
                ui.space()
                if device.tags:
                    for tag in device.tags[:4]:
                        ui.chip(tag).props('dense color=primary text-color=white')
                    if len(device.tags) > 4:
                        ui.chip(f'+{len(device.tags) - 4}').props('dense color=grey text-color=white')

            # Row 2-: location, description, last seen, firmware, labels
            if device.location:
                with ui.row().classes('items-center gap-1 q-mt-xs'):
                    ui.icon('place').classes('text-grey-7 text-sm')
                    ui.label(device.location).classes('text-body2')
            if device.description:
                ui.label(device.description).classes('text-body2 q-mt-xs text-grey-7')
            if device.location or device.description:
                ui.separator().classes('q-mt-xs q-mb-xs')

            reported_at = max(
                (ts for ts in (device.firmware_reported_at, runtime.system_reported_at if runtime else None)
                 if ts is not None), default=None)
            if reported_at:
                with ui.row().classes('items-center w-full gap-1 q-mt-sm'):
                    ui.space()
                    ui.label(f'as of {render_datetime_age(reported_at)}').classes('text-caption text-grey-7')
            with ui.grid(columns='auto 1fr').classes('grid-cols-2 gap-y-1 q-mt-xs'):
                ui.label('Firmware').classes('text-caption text-grey-7')
                if device.firmware_version:
                    fw = device.firmware_version
                    ui.label(fw).tooltip(fw).classes('text-body2 overflow-hidden text-ellipsis')
                else:
                    ui.label('Unknown').classes('text-body2 text-grey-7')
                ui.label('Board').classes('text-caption text-grey-7')
                if runtime and runtime.board:
                    ui.label(runtime.board).tooltip(runtime.board).classes('text-body2 overflow-hidden text-ellipsis')
                else:
                    ui.label('Unknown').classes('text-body2 text-grey-7')

            # Latest system-telemetry snapshot (battery_V, wifi_rssi, ...), cached
            # in the runtime sidecar — the last 'system' push's numeric values.
            if runtime and runtime.system_metrics:
                ui.separator().classes('q-mt-xs q-mb-xs')
                with ui.row().classes('items-center w-full gap-1'):
                    ui.label('System').classes('text-caption text-grey-7')
                    ui.space()
                    ui.label(render_datetime_age(runtime.system_reported_at)) \
                        .classes('text-caption text-grey-7')
                with ui.grid(columns='auto 1fr').classes('grid-cols-2 gap-y-1 q-mt-xs'):
                    for k, metric_value in sorted(runtime.system_metrics.items()):
                        ui.label(k).classes('text-caption text-grey-7')
                        ui.label(_format_metric(metric_value)).classes('text-body2')


async def _timeline_card(device: Device) -> None:

    with ui.card().tight().classes('w-full'):
        with ui.card_section().props('dense').classes('w-full'):
            # Row 0: card name - icons for alarms, active, online
            with ui.row().classes('items-center w-full gap-0'):
                ui.label('Timeline').classes('text-subtitle1 font-bold')
                ui.space()
                prov_color = 'positive' if device.is_provisioning_approved else 'negative'
                prov_text = 'Provisioning approved' if device.is_provisioning_approved else 'Provisioning pending'
                ui.chip(prov_text).props(f'dense color={prov_color} text-color=white')
            ui.separator().classes('q-mt-xs q-mb-xs')
            with ui.grid(columns='auto 1fr').classes('grid-cols-2 gap-y-1 q-mt-sm'):
                ui.label('Last seen').classes('text-caption text-grey-7')
                ui.label(render_datetime_age(device.last_seen_at)).classes('text-body2')
                ui.label('Created').classes('text-caption text-grey-7')
                ui.label(render_datetime(device.created_at)).classes('text-body2')
                ui.label('Updated').classes('text-caption text-grey-7')
                ui.label(render_datetime(device.updated_at)).classes('text-body2')
                ui.label('Last provisioned').classes('text-caption text-grey-7')
                ui.label(render_datetime_age(device.last_provisioned_at)).classes('text-body2')
                ui.label('Last provisioning request').classes('text-caption text-grey-7')
                ui.label(render_datetime_age(device.last_provisioning_request_at)).classes('text-body2')
                if device.last_provisioning_token_expires_at:
                    ui.label('Provisioning token expires').classes('text-caption text-grey-7')
                    ui.label(render_datetime_age(device.last_provisioning_token_expires_at)) \
                        .tooltip(f'Token fingerprint: {device.last_provisioning_token_fingerprint}') \
                        .classes('text-body2')


# ***************************************************************************
# Device General Panel (Settings → General)
# ***************************************************************************

async def device_general_panel(project_name: str, device_name: str, args: PageArguments) -> None:
    """Content of the General tab — device settings, tokens, danger zone."""
    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with config_expansion('Device'):
            _device_general_card(project_name, device_name)
        with config_expansion('Authentication Tokens'):
            _device_tokens_card(project_name, device_name)
        with config_expansion('Firmware Seed'):
            await device_seed_override_card(device_dir(project_name, device_name),
                                            project_name=project_name, device_name=device_name)
        with config_expansion('Firmware Download'):
            # Device-level firmware source pulls into the device dir — an
            # unconfigured device serves the project's pulled firmware.bin via
            # the normal file-serving fallback (see app/api/file.py).
            await firmware_source_card(device_dir(project_name, device_name),
                                       project_name=project_name, device_name=device_name)
        for title, render_fn in await anyio.to_thread.run_sync(lambda: get_device_settings_cards(project_name)):
            # Match the device page's built-in expansions (subtitle1), not the
            # config_expansion default (h6, used on the project page).
            with config_expansion(title):
                await maybe_await(call_with_page_args(render_fn, args, project_name, device_name))
        # Danger Zone always last, after any extension cards (matches the project page).
        with config_expansion('Danger Zone'):
            await _device_danger_card(project_name, device_name)


def _device_general_card(project_name: str, device_name: str) -> None:
    form = ModelForm.from_adapter(
        Device,
        device_adapter(project_name, device_name),
        autosave=True,
        layout=[['is_active:shrink', 'name'], 
                'description', 'location', 'tags',
                ['is_provisioning_approved:w-auto']],
    )
    form.render()
    d = cast(Device, form.item)  # niceview types form.item as Any; cast enables attribute access for bind_text_from
    ui.label().classes('text-caption text-grey-7 q-mt-xs').bind_text_from(
        d, 'updated_at',
        backward=lambda v: f'Created {render_datetime(d.created_at)}, updated {render_datetime(v)}'
    )


def _device_tokens_card(project_name: str, device_name: str) -> None:
    project = get_project(project_name, check_active=False)
    TokenListCard(
        get_device_token_adapter(project_name, device_name),
        allow_add=True,
        token_length=project.device_token_length,
        expires_in=project.device_tokens_expire_in,
    )


async def _device_danger_card(project_name: str, device_name: str) -> None:
    with ui.row().classes('w-full gap-4 q-mt-xs'):
        val_rules: dict[str, Callable[[Any], bool]] = {
            "Invalid name: letters, digits, underscore only; must not start with a digit.": is_valid_name
        }
        name_widget = ui.input(
            label='New Device Name',
            value=device_name,
            validation=val_rules,
        ).classes('grow').props('dense outlined')
        async def _on_rename() -> None:
            await _rename_device(project_name, device_name, name_widget.value)
        # Negative on purpose, and not to be normalised away: a rename is destructive
        # for deployed devices. Their configured API paths carry the device name, so
        # renaming breaks every client in the field until it is reconfigured.
        ui.button('Rename Device').props('color=negative').on_click(_on_rename)

    async def _on_delete() -> None:
        await _delete_device(project_name, device_name)
    ui.button('Delete Device').props('color=negative').classes('w-full').on_click(_on_delete)


async def _rename_device(project_name: str, old_name: str, new_name: str) -> None:
    if not is_valid_name(new_name):
        ui.notify(f"Invalid device name: {new_name}", type='negative')
        return
    if old_name == new_name:
        ui.notify("Device name unchanged", type='warning')
        return
    if not await confirm_dialog(
        'Rename Device',
        f'Renaming **{old_name}** changes the API path it is reached at. '
        'The device stops reaching the server until it is reconfigured with the new name.',
        ok_label='Rename',
        ok_role='delete',
    ):
        return
    try:
        rename_device(project_name, old_name, new_name)
        ui.notify(f"Renamed to {new_name}", type='positive')
        ui.navigate.to(device_url(project_name, new_name, tab='General'))
    except Exception as e:
        log.exception(f"Rename failed: {e}")
        ui.notify(f"Rename failed: {e}", type='negative')


async def _delete_device(project_name: str, device_name: str) -> None:
    if not await confirm_dialog(
        'Delete Device',
        f'Delete device **{device_name}**? This is irreversible.',
        ok_label='Delete',
        ok_role='delete',
    ):
        return
    try:
        delete_device(project_name, device_name)
        ui.notify(f"Deleted device {device_name}", type='positive')
        ui.navigate.to(project_url(project_name, tab='devices'))
    except Exception as e:
        log.exception(f"Delete failed: {e}")
        ui.notify(f"Delete failed: {e}", type='negative')


async def prompt_create_device(project_name: str) -> str | None:
    """Prompt for a device name and create the device record. Returns the new
    device's name, or None if cancelled or creation failed. Shared by the
    plain "New Device" action and the Web-Serial-Flash / AP+QR shortcuts,
    which all start from the same device record (see docs/concepts.md)."""
    name = await input_dialog(
        'Create Device',
        label='Device Name',
        placeholder='enter a device name here',
        validator=is_valid_name,
        error_message='Invalid name: letters, digits, underscore only; must not start with a digit.',
    )
    if name is None:
        return None
    try:
        device = create_device(Device(name=name, project_name=project_name))
        ui.notify(f"Created device {device.name}", type='positive')
        return device.name
    except Exception as e:
        ui.notify(f"Error creating device {name}: {e}", type='negative')
        return None


# ***************************************************************************
# Project Devices Table (used in project Devices tab)
# ***************************************************************************
# The Status column is rendered as one raw-HTML cell holding three <span>
# icons (status dot, WiFi, battery) via ModelGrid's cell_renderers + html_fields
# (ag-grid's html_columns under the hood) — nicegui bundles the classic
# "Material Icons" webfont globally (class material-icons), so a plain
# <span class="material-icons"> works inside an ag-grid cell without any
# custom cellRenderer component. Tooltips are a plain HTML title= attribute
# (ag-grid's own tooltipField needs the text as a visible or hidden *column*,
# which we don't otherwise want) — no rich styling, but correct and simple.
#
# Icon name choice is deliberately narrow and verified, not guessed: earlier
# versions used more granular bar-count icons ('signal_wifi_four_bar',
# 'network_wifi_two_bar', 'battery_six_bar', ...) which made the icon visibly
# jump left/right within its cell from row to row. Rendering every candidate
# name against the actual bundled font (a temporary debug overlay injected
# into a live page, screenshotted) showed why: several of those names
# ('signal_wifi_zero_bar'/'four_bar', every 'battery_*_bar' word-form) don't
# exist as ligatures in the bundled font at all — the "icon" was empty/
# invisible — and the ones that do render come from visibly different glyph
# designs with different internal bearings, so swapping between them shifts
# the visible glyph within its fixed-size box. The names below are exactly
# the ones confirmed to render, and to share consistent bearings within their
# own group, in that same probe.

_ICON_STYLE = 'font-size:16px;vertical-align:middle;color:{color}'


def _icon_span(icon: str, color: str, tooltip: str) -> str:
    return f'<span class="material-icons" style="{_ICON_STYLE.format(color=color)}" title="{html.escape(tooltip)}">{icon}</span>'


# status_key -> (icon, color, tooltip). status_key is computed by
# app.core.device.backend.device_status_key() from is_active/
# is_provisioning_approved/online — inactive beats everything else, then
# pending provisioning approval, then plain online/offline.
_STATUS_ICONS: dict[str, tuple[str, str, str]] = {
    'online': ('circle', '#4caf50', 'Active, provisioned, online'),
    'offline': ('circle', '#fb8c00', 'Active, provisioned, offline'),
    'pending': ('pending', '#9c27b0', 'Active, pending provisioning approval'),
    'inactive': ('circle', '#9e9e9e', 'Inactive'),
}


def _status_icon_span(status_key: str) -> str:
    icon, color, tooltip = _STATUS_ICONS.get(status_key, _STATUS_ICONS['inactive'])
    return _icon_span(icon, color, tooltip)


# RSSI (dBm) -> no-data / weak / good. Only three states (down from a 0-4 bar
# scale) because the bundled font has no consistent, fully-populated bar-count
# family to scale through — see the module comment above.
def _wifi_icon_span(rssi: Optional[int]) -> str:
    if rssi is None:
        return _icon_span('signal_wifi_off', '#757575', 'No signal data yet')
    tooltip = f'{rssi} dBm'
    if rssi >= -70:
        return _icon_span('wifi', '#757575', tooltip)
    return _icon_span('signal_wifi_bad', '#757575', tooltip)


# Battery voltage (V) -> a 0-6 bar icon, assuming a single-cell Li-ion/LiPo
# pack. Uses the numeric 'battery_N_bar' names, not the word-form
# ('battery_six_bar', ...) nicepaper's Displays list used to use — the
# word-form doesn't exist in the bundled font at all (see module comment).
_BATTERY_BARS = tuple(f'battery_{i}_bar' for i in range(7))
_BATTERY_EMPTY_V = 3.2
_BATTERY_FULL_V = 4.15


def _battery_icon_name(voltage: Optional[float]) -> str:
    if voltage is None:
        return 'battery_unknown'
    if voltage < _BATTERY_EMPTY_V:
        return 'battery_alert'
    if voltage >= _BATTERY_FULL_V:
        return 'battery_full'
    step = (_BATTERY_FULL_V - _BATTERY_EMPTY_V) / len(_BATTERY_BARS)
    index = min(len(_BATTERY_BARS) - 1, int((voltage - _BATTERY_EMPTY_V) / step))
    return _BATTERY_BARS[index]


def _battery_icon_span(voltage: Optional[float]) -> str:
    tooltip = f'{voltage:.2f} V' if voltage is not None else 'No battery data yet'
    color = '#e53935' if voltage is not None and voltage < _BATTERY_EMPTY_V else '#757575'
    return _icon_span(_battery_icon_name(voltage), color, tooltip)


def _status_cell_html(value: tuple[str, Optional[int], Optional[float]]) -> str:
    """cell_renderer for ProjectDeviceRow.status — a (status_key, rssi,
    battery_voltage) tuple rendered as three icons in one cell, so the grid
    doesn't need three separate narrow columns for what's really one glance
    of device health."""
    status_key, rssi, battery_voltage = value
    icons = _status_icon_span(status_key) + _wifi_icon_span(rssi) + _battery_icon_span(battery_voltage)
    return f'<span style="display:inline-flex;align-items:center;gap:6px;">{icons}</span>'


class _ProjectDeviceRowAdapter(ReloadableAdapter):
    """Minimal read-only niceview CollectionAdapter[ProjectDeviceRow] over an
    already-fetched row list, keyed by device name. ModelGrid.from_list()'s
    ListAdapter keys rows by list position ("0", "1", ...) instead, which
    would make row navigation (see ProjectDevicesTable._on_row_selected)
    navigate to the wrong device (or none at all). Implements ReloadableAdapter
    so the EditGridWrapper Refresh button reloads the device list fresh from disk."""

    def __init__(self, project_name: str, rows: list[ProjectDeviceRow] | None = None) -> None:
        self.project_name = project_name
        if rows is None:
            self.reload()
        else:
            self._by_name = {row.name: row for row in rows}

    def reload(self) -> None:
        invalidate_device_list_cache(self.project_name)
        rows = project_device_rows(self.project_name)
        self._by_name = {row.name: row for row in rows}

    def __iter__(self):
        return iter(self._by_name.values())

    def key_from_item(self, item: ProjectDeviceRow) -> str:
        return item.name

    def read(self, key: str) -> ProjectDeviceRow:
        return self._by_name[key]

    def items(self):
        return iter(self._by_name.items())

    def create(self, item: ProjectDeviceRow) -> ProjectDeviceRow:
        raise NotImplementedError('ProjectDevicesTable is read-only')

    def update(self, item: ProjectDeviceRow) -> ProjectDeviceRow:
        raise NotImplementedError('ProjectDevicesTable is read-only')

    def delete(self, key: str) -> None:
        raise NotImplementedError('ProjectDevicesTable is read-only')


class ProjectDevicesTable:
    """Grid of all devices in a project. Read-only (device edits happen on the
    device's own page); clicking a row navigates there. rows are built by
    app.core.device.backend.project_device_rows() — pass them in already
    fetched (see project_devices_panel), since that does per-device file IO
    that must not block the event loop (see the Async IO rule in CLAUDE.md).

    Navigation goes through ModelGrid.on_select() (ag-grid's selectionChanged,
    resolved via a clean get_selected_row() RPC) rather than listening for a
    raw 'rowDoubleClicked' DOM event directly: ag-grid's native row events
    carry the whole grid api/context object graph, which is circular and
    fails NiceGUI's generic event-arg JSON serialization client-side — the
    handler then silently never fires. on_select doesn't have this problem
    since it never serializes the raw event, only the already-clean row data."""

    def __init__(self, project_name: str, rows: list[ProjectDeviceRow] | None = None):
        self.project_name = project_name

        async def _new_device() -> None:
            name = await prompt_create_device(project_name)
            if name is not None:
                ui.navigate.to(device_url(project_name, name, tab='General'))

        self.adapter = _ProjectDeviceRowAdapter(project_name, rows)
        grid = ModelGrid.from_adapter(
            ProjectDeviceRow, self.adapter,
            auto_size_columns=True,
            rowSelection='single',
            cell_renderers={'status': _status_cell_html},
            html_fields=['status'],
        )
        grid.on_select(self._on_row_selected)
        self.wrapper = EditGridWrapper(
            grid,
            title=f'Devices in {project_name}',
            search=True,
            add_button='',
            edit_button=None,
            delete_button=None,
            refresh_button='',
            on_add=_new_device,
        ).render()

    def _on_row_selected(self, event) -> None:
        if event.row_key is not None:
            ui.navigate.to(device_url(self.project_name, event.row_key))
