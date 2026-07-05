import datetime
from typing import cast

from nicegui import ui

from app.routes import device_url, project_url
from app.core.device.models import Device
from app.core.device.backend import (
    create_device, delete_device, device_adapter, get_device, get_devices,
    rename_device,
)
from app.core.project.backend import get_project
from app.core.token.backend import get_device_token_adapter
from app.core.token.ui import TokenListCard
from app.ui.util import build_dialog
from app.util import is_valid_filename, render_datetime
from niceview.form import ModelForm

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************
# Device Dashboard Panel
# ***************************************************************************

def device_dashboard_panel(project_name: str, device_name: str) -> None:
    """Overview cards shown on the device Dashboard tab (auto-refreshes every 30 s)."""
    @ui.refreshable
    def _content() -> None:
        device = get_device(project_name, device_name)
        now = datetime.datetime.now(datetime.timezone.utc)
        with ui.grid().classes('grid-cols-1 sm:grid-cols-2 gap-4 w-full'):
            _status_card(device, now)
            _provisioning_card(device)

    _content()
    ui.timer(30.0, _content.refresh)


def _ago(delta: datetime.timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return f'{s}s ago'
    if s < 3600:
        return f'{s // 60}min ago'
    if s < 86400:
        return f'{s // 3600}h ago'
    return f'{s // 86400}d ago'


def _status_card(device: Device, now: datetime.datetime) -> None:
    with ui.card().classes('w-full'):
        ui.label('Status').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('items-center gap-2 q-mt-xs'):
            color = 'green' if device.is_active else 'grey'
            ui.chip('Active' if device.is_active else 'Inactive').props(f'dense color={color} text-color=white')
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
    with ui.card().classes('w-full'):
        ui.label('Provisioning').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('items-center gap-2 q-mt-xs'):
            prov_color = 'green' if device.is_provisioning_approved else 'orange'
            prov_text = 'Approved' if device.is_provisioning_approved else 'Pending Approval'
            ui.chip(prov_text).props(f'dense color={prov_color} text-color=white')
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
                "Invalid name: use letters, digits, underscore, plus, hyphen only.": is_valid_filename
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
    if not is_valid_filename(new_name):
        ui.notify(f"Invalid device name: {new_name}", type='negative')
        return
    if old_name == new_name:
        ui.notify("Device name unchanged", type='warning')
        return
    result = await build_dialog(
        'Rename Device',
        f'Renaming {old_name!r} changes its URL path. Continue?',
        ['|1Cancel', '-OK'],
    )
    if result != 'OK':
        return
    try:
        rename_device(project_name, old_name, new_name)
        ui.notify(f"Renamed to {new_name}", type='positive')
        ui.navigate.to(device_url(project_name, new_name, tab='General'))
    except Exception as e:
        log.exception(f"Rename failed: {e}")
        ui.notify(f"Rename failed: {e}", type='negative')


async def _delete_device(project_name: str, device_name: str) -> None:
    result = await build_dialog(
        'Delete Device',
        f'Delete device {device_name!r}? This is irreversible.',
        ['|1Cancel', '-Delete'],
    )
    if result != 'Delete':
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
        self.project_name = project_name
        self.device_new_dialog = DeviceCreationDialog(project_name)
        self.devices = get_devices(project_name)

        columns = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'sortable': True},
            {'name': 'is_active', 'label': 'Active', 'field': 'is_active', 'sortable': True},
            {'name': 'location', 'label': 'Location', 'field': 'location', 'sortable': True},
            {'name': 'last_seen_at', 'label': 'Last Seen', 'field': 'last_seen_at', 'sortable': True},
            {'name': 'is_provisioning_approved', 'label': 'Provisioning OK', 'field': 'is_provisioning_approved', 'sortable': True},
        ]
        rows = [
            {
                'id': d.name,
                'name': d.name,
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
                ui.button(icon='add') \
                    .tooltip('Create Device') \
                    .props('color=primary dense') \
                    .on_click(self.device_new_dialog.show)
        self.table.on('row-dblclick', lambda msg: (
            ui.navigate.to(device_url(self.project_name, msg.args[1]['id'], tab='General')),
        ))


# ***************************************************************************
# Device Creation Dialog
# ***************************************************************************

class DeviceCreationDialog:
    """Dialog for creating a new device."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.device_name = ''
        with ui.dialog().style('width: 400px') as self.dialog:
            with ui.card().classes('w-full'):
                ui.label('Create Device').classes('text-h6 text-center')
                val_rules = {
                    "Invalid name: use letters, digits, underscore, plus, hyphen only.": is_valid_filename
                }
                ui.input(
                    label='Device Name',
                    placeholder='enter a device name here',
                    validation=val_rules,
                ).bind_value(self, 'device_name').classes('w-full')
                with ui.row().classes('w-full place-content-end'):
                    ui.space()
                    ui.button('Cancel').props('color=secondary').on_click(lambda: self.dialog.submit(False))
                    ui.button('Create').on_click(lambda: self.dialog.submit(True))

    async def show(self):
        result = await self.dialog
        if result and self.device_name and is_valid_filename(self.device_name):
            try:
                device = create_device(Device(name=self.device_name, project_name=self.project_name))
                ui.notify(f"Created device {device.name}", type='positive')
                ui.navigate.to(device_url(self.project_name, self.device_name, tab='General'))
            except Exception as e:
                ui.notify(f"Error creating device {self.device_name}: {e}", type='negative')
        else:
            ui.notify("Device creation cancelled", type='negative')
