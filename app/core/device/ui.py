import datetime
from typing import Optional, cast

import anyio
from nicegui import PageArguments, ui

from app.routes import device_url, project_url
from app.ui import config_expansion
from app.core.device.models import Device
from app.core.device.backend import (
    create_device, delete_device, device_adapter, get_device, get_devices,
    is_device_online, rename_device,
)
from app.core.device.files_ui import device_files_panel
from app.core.device.data_ui import device_data_panel
from app.core.device.logs_ui import device_logs_panel
from app.core.project.backend import get_project
from app.core.token.backend import get_device_token_adapter
from app.core.token.ui import TokenListCard
from app.util import is_valid_name, render_datetime
from niceview.form import ModelForm
from niceview.util import confirm_dialog, input_dialog
from app.extensions import get_device_dashboard_cards, get_device_general_cards, get_device_tabs, maybe_await

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************
# Device sub-page (routing entry point — lives here, not in frontend.py)
# ***************************************************************************

async def device_subpage(
    args: PageArguments,
    nav: ui.element,
    project_id: str,
    device_id: str,
    tab: Optional[str] = None,
) -> None:
    """Render the device page: header nav path + tabbed panels."""
    nav.clear()
    with nav:
        ui.label('/').classes('text-h6 text-white opacity-50')
        ui.label(project_id).classes('text-h6 cursor-pointer text-white opacity-80') \
            .on('click', lambda: ui.navigate.to(project_url(project_id)))
        ui.label('/').classes('text-h6 text-white opacity-50')
        ui.label(device_id).classes('text-h6 font-bold cursor-pointer text-white') \
            .on('click', lambda: ui.navigate.to(device_url(project_id, device_id)))

    extension_tab_defs = await anyio.to_thread.run_sync(lambda: get_device_tabs(project_id))
    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        general_tab   = ui.tab('General')
        files_tab     = ui.tab('Files')
        data_tab      = ui.tab('Data')
        logs_tab      = ui.tab('Logs')
        alarms_tab    = ui.tab('Alarms')
        extension_tabs = [(ui.tab(label), render_fn) for label, render_fn in extension_tab_defs]
    tab = tab or 'Dashboard'
    with ui.tab_panels(tabs, value=tab).classes('w-full'):
        with ui.tab_panel(dashboard_tab):
            await device_dashboard_panel(project_id, device_id)
        with ui.tab_panel(general_tab):
            await device_general_panel(project_id, device_id)
        with ui.tab_panel(files_tab):
            device_files_panel(project_id, device_id)
        with ui.tab_panel(data_tab):
            await device_data_panel(project_id, device_id)
        with ui.tab_panel(logs_tab):
            device_logs_panel(project_id, device_id)
        with ui.tab_panel(alarms_tab):
            from app.core.alarm.ui import DeviceAlarmsTab
            DeviceAlarmsTab(project_id, device_id)
        for extension_tab, render_fn in extension_tabs:
            with ui.tab_panel(extension_tab):
                await maybe_await(render_fn(project_id, device_id))


# ***************************************************************************
# Device Dashboard Panel
# ***************************************************************************

async def device_dashboard_panel(project_name: str, device_name: str) -> None:
    """Overview cards shown on the device Dashboard tab (auto-refreshes every 10 s)."""
    from app.core.alarm.ui import DeviceAlarmPanel

    @ui.refreshable
    async def _content() -> None:
        device = get_device(project_name, device_name)
        project = get_project(project_name, check_active=False)
        now = datetime.datetime.now(datetime.timezone.utc)
        with ui.grid().classes('grid-cols-1 sm:grid-cols-2 gap-4 w-full'):
            _status_card(device, project_name, project.device_online_threshold_s, now)
            _provisioning_card(device)
            for render_fn in await anyio.to_thread.run_sync(lambda: get_device_dashboard_cards(project_name)):
                await maybe_await(render_fn(project_name, device_name))

    await _content()
    ui.timer(10.0, _content.refresh)
    DeviceAlarmPanel(project_name, device_name)


def _ago(delta: datetime.timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return f'{s}s ago'
    if s < 3600:
        return f'{s // 60}min ago'
    if s < 86400:
        return f'{s // 3600}h ago'
    return f'{s // 86400}d ago'


def _status_card(device: Device, project_name: str, online_threshold_s: int, now: datetime.datetime) -> None:
    from app.core.alarm.backend import get_device_alarm_count
    online = is_device_online(device, online_threshold_s)
    alarm_count = get_device_alarm_count(project_name, device.name)
    with ui.card().classes('w-full'):
        with ui.row().classes('items-center w-full'):
            ui.label('Status').classes('text-subtitle1 font-bold')
            ui.space()
            if alarm_count:
                ui.chip(str(alarm_count)).props('dense color=red text-color=white icon=notifications_active') \
                    .tooltip(f'{alarm_count} active alarm(s)')
            color = 'green' if device.is_active else 'grey'
            ui.chip('Active' if device.is_active else 'Inactive').props(f'dense color={color} text-color=white')
            ui.chip('Online' if online else 'Offline').props(
                f'dense color={"green" if online else "grey"} text-color=white'
            )
        ui.separator()
        if device.location:
            with ui.row().classes('items-center gap-1 q-mt-xs'):
                ui.icon('place').classes('text-grey-6 text-sm')
                ui.label(device.location).classes('text-body2')
        if device.description:
            ui.label(device.description).classes('text-body2 q-mt-xs text-grey-8')
        ui.separator().classes('q-mt-sm')
        ui.label('Last seen').classes('text-caption text-grey-6')
        if device.last_seen_at:
            delta = now - device.last_seen_at
            ui.label(f'{render_datetime(device.last_seen_at)}  ({_ago(delta)})').classes('text-body2')
        else:
            ui.label('Never').classes('text-body2 text-grey-6')


def _provisioning_card(device: Device) -> None:
    prov_color = 'green' if device.is_provisioning_approved else 'orange'
    prov_text = 'Approved' if device.is_provisioning_approved else 'Pending'
    with ui.card().classes('w-full'):
        with ui.row().classes('items-center w-full'):
            ui.label('Provisioning').classes('text-subtitle1 font-bold')
            ui.space()
            ui.chip(prov_text).props(f'dense color={prov_color} text-color=white')
        ui.separator()
        with ui.grid().classes('grid-cols-2 gap-y-1 q-mt-sm'):
            ui.label('Last provisioned').classes('text-caption text-grey-6')
            ui.label(render_datetime(device.last_provisioned_at)).classes('text-caption')
            ui.label('Last request').classes('text-caption text-grey-6')
            ui.label(render_datetime(device.last_provisioning_request_at)).classes('text-caption')
            ui.label('Created').classes('text-caption text-grey-6')
            ui.label(render_datetime(device.created_at)).classes('text-caption')
            ui.label('Updated').classes('text-caption text-grey-6')
            ui.label(render_datetime(device.updated_at)).classes('text-caption')


# ***************************************************************************
# Device General Panel (Settings → General)
# ***************************************************************************

async def device_general_panel(project_name: str, device_name: str) -> None:
    """Content of the General tab — device settings, tokens, danger zone."""
    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with ui.card().classes('w-full'):
            _device_general_card(project_name, device_name)
        with ui.card().classes('w-full'):
            _device_tokens_card(project_name, device_name)
        with ui.card().classes('w-full'):
            await _device_danger_card(project_name, device_name)
        for title, render_fn in await anyio.to_thread.run_sync(lambda: get_device_general_cards(project_name)):
            with ui.card().classes('w-full'):
                with config_expansion(title):
                    await maybe_await(render_fn(project_name, device_name))


def _device_general_card(project_name: str, device_name: str) -> None:
    with ui.expansion('Device', value=True).classes('w-full').props('dense header-class="text-subtitle1 font-bold"'):
        form = ModelForm.from_adapter(
            Device,
            device_adapter(project_name, device_name),
            include=['name', 'description', 'location', 'tags', 'is_active', 'is_provisioning_approved'],
            autosave=True,
        )
        form.render_field('name', editable=False).props('outlined dense').classes('w-full')
        form.render_field('description').props('outlined dense hide-bottom-space').classes('w-full')
        form.render_field('location').props('outlined dense hide-bottom-space').classes('w-full')
        form.render_field('tags').props('outlined dense hide-bottom-space').classes('w-full')
        with ui.row().classes('w-full gap-4 q-mt-xs'):
            form.render_field('is_active')
            form.render_field('is_provisioning_approved')
        d = cast(Device, form.item)  # niceview types form.item as Any; cast enables attribute access for bind_text_from
        ui.label().classes('text-caption text-grey-7 q-mt-xs').bind_text_from(
            d, 'updated_at',
            backward=lambda v: f'Created {render_datetime(d.created_at)}, updated {render_datetime(v)}'
        )


def _device_tokens_card(project_name: str, device_name: str) -> None:
    project = get_project(project_name, check_active=False)
    with ui.expansion('Authentication Tokens', value=True).classes('w-full').props('dense header-class="text-subtitle1 font-bold"'):
        TokenListCard(
            get_device_token_adapter(project_name, device_name),
            show_name=False,
            allow_add=True,
            token_length=project.device_token_length,
            expires_in=datetime.timedelta(days=project.device_tokens_expire_in),
        )


async def _device_danger_card(project_name: str, device_name: str) -> None:
    with ui.expansion('Danger Zone', value=False).classes('w-full').props('dense header-class="text-subtitle1 font-bold"'):
        with ui.row().classes('w-full gap-4 q-mt-xs'):
            val_rules = {
                "Invalid name: letters, digits, underscore only; must not start with a digit.": is_valid_name
            }
            name_widget = ui.input(
                label='New Device Name',
                value=device_name,
                validation=val_rules,
            ).classes('grow').props('dense outlined')
            async def _on_rename() -> None:
                await _rename_device(project_name, device_name, name_widget.value)
            ui.button('Rename').props('color=negative').on_click(_on_rename)

        async def _on_delete() -> None:
            await _delete_device(project_name, device_name)
        ui.button('Delete Device').props('color=negative w-full').on_click(_on_delete)


async def _rename_device(project_name: str, old_name: str, new_name: str) -> None:
    if not is_valid_name(new_name):
        ui.notify(f"Invalid device name: {new_name}", type='negative')
        return
    if old_name == new_name:
        ui.notify("Device name unchanged", type='warning')
        return
    if not await confirm_dialog(
        'Rename Device',
        f'Renaming **{old_name}** changes its URL path. Continue?',
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
        ok_color='negative',
    ):
        return
    try:
        delete_device(project_name, device_name)
        ui.notify(f"Deleted device {device_name}", type='positive')
        ui.navigate.to(project_url(project_name, tab='Devices'))
    except Exception as e:
        log.exception(f"Delete failed: {e}")
        ui.notify(f"Delete failed: {e}", type='negative')


# ***************************************************************************
# Project Devices Table (used in project Devices tab)
# ***************************************************************************

class ProjectDevicesTable:
    """Table of all devices in a project."""

    def __init__(self, project_name: str):
        from app.core.alarm.backend import get_device_alarm_count
        self.project_name = project_name
        self.devices = get_devices(project_name)

        columns = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'sortable': True},
            {'name': 'alarms', 'label': 'Alarms', 'field': 'alarms', 'sortable': True},
            {'name': 'is_active', 'label': 'Active', 'field': 'is_active', 'sortable': True},
            {'name': 'location', 'label': 'Location', 'field': 'location', 'sortable': True},
            {'name': 'last_seen_at', 'label': 'Last Seen', 'field': 'last_seen_at', 'sortable': True},
            {'name': 'is_provisioning_approved', 'label': 'Provisioning OK', 'field': 'is_provisioning_approved', 'sortable': True},
        ]
        rows = [
            {
                'id': d.name,
                'name': d.name,
                'alarms': get_device_alarm_count(project_name, d.name),
                'is_active': d.is_active,
                'location': d.location or '',
                'last_seen_at': render_datetime(d.last_seen_at),
                'is_provisioning_approved': d.is_provisioning_approved,
            }
            for d in self.devices
        ]

        self.table = ui.table(
            title=f'Devices in {project_name}',
            columns=columns,
            rows=rows,
        ).classes('w-full')
        with self.table.add_slot('top-right'):
            with ui.row():
                with ui.input(placeholder='Search').props('type=search outlined dense').classes('grow').bind_value(self.table, 'filter').add_slot('append'):
                    ui.icon('search')

                async def _new_device():
                    name = await input_dialog(
                        'Create Device',
                        label='Device Name',
                        placeholder='enter a device name here',
                        validator=is_valid_name,
                        error_message='Invalid name: letters, digits, underscore only; must not start with a digit.',
                    )
                    if name is None:
                        return
                    try:
                        device = create_device(Device(name=name, project_name=project_name))
                        ui.notify(f"Created device {device.name}", type='positive')
                        ui.navigate.to(device_url(project_name, name, tab='General'))
                    except Exception as e:
                        ui.notify(f"Error creating device {name}: {e}", type='negative')

                ui.button(icon='add') \
                    .tooltip('Create Device') \
                    .props('color=primary dense') \
                    .on_click(_new_device)
        self.table.on('row-dblclick', lambda msg: (
            ui.navigate.to(device_url(self.project_name, msg.args[1]['id'], tab='General')),
        ))
