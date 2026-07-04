import datetime
import os
from typing import Optional

from nicegui import app, ui

from app.routes import device_url, project_url
from app.core.device.models import Device
from app.core.device.backend import create_device, get_device, get_devices, update_device
from app.core.project.backend import get_project
from app.core.token.backend import get_device_token_adapter
from app.core.token.ui import TokenListCard
from app.ui.util import build_dialog
from app.util import is_valid_filename, render_datetime

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************

class ProjectDevicesTable:
    """Table containing a project's devices."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.device_new_dialog = DeviceCreationDialog(project_name)
        self.devices = get_devices(project_name)

        devices_cols = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'sortable': True},
            {'name': 'is_active', 'label': 'Active', 'field': 'is_active', 'sortable': True},
            {'name': 'location', 'label': 'Location', 'field': 'location', 'sortable': True},
            {'name': 'last_seen_at', 'label': 'Last Seen', 'field': 'last_seen_at', 'sortable': True},
            {'name': 'is_provisioning_approved', 'label': 'Provisioning OK', 'field': 'is_provisioning_approved', 'sortable': True},
        ]
        devices_rows = [
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

        self.devices_table = ui.table(
            title=f'Devices in project {project_name.capitalize()}',
            columns=devices_cols,
            rows=devices_rows,
        ).classes('w-full')
        with self.devices_table.add_slot('top-right'):
            with ui.row():
                with ui.input(placeholder='Search').props('type=search outlined dense').classes('grow').bind_value(self.devices_table, 'filter').add_slot('append'):
                    ui.icon('search')
                ui.button(icon='add') \
                    .tooltip('Create Device') \
                    .props('color=primary dense') \
                    .on_click(self.device_new_dialog.show)
        self.devices_table.on('row-dblclick', lambda msg: (
            ui.navigate.to(device_url(self.project_name, msg.args[1]['id'], tab='Settings')),
        ))


# ***************************************************************************

class DeviceSettingsCard:
    """Card for device settings and bearer token management."""

    def __init__(self, project_name: str, device_name: str):
        self.project_name = project_name
        self.device_name = device_name
        self.device = get_device(project_name, device_name)
        project = get_project(project_name)

        with ui.card().classes('w-full') as self.card:
            ui.label(f'{project_name}/{device_name} Settings').classes('text-h6 font-bold')
            ui.separator()
            ui.input(label='Name').bind_value(self.device, 'name').classes('w-full')
            ui.input(label='Location').bind_value(self.device, 'location').classes('w-full')
            ui.textarea(label='Description').bind_value(self.device, 'description').classes('w-full')
            ui.checkbox(text='Device is active').bind_value(self.device, 'is_active')
            ui.checkbox(text='Provisioning approved').bind_value(self.device, 'is_provisioning_approved')
            ui.label(f'Last seen at {render_datetime(self.device.last_seen_at)}')
            ui.label(f'Last provisioning request at {render_datetime(self.device.last_provisioning_request_at)}')
            ui.label(f'Last successful provisioning at {render_datetime(self.device.last_provisioned_at)}')

            with ui.expansion('Authentication Tokens', value=True).classes('w-full q-mt-sm').props('dense header-class="text-subtitle1 font-bold"'):
                TokenListCard(
                    get_device_token_adapter(project_name, device_name),
                    show_name=False,
                    allow_add=True,
                    token_length=project.device_token_length,
                    expires_in=datetime.timedelta(days=project.device_tokens_expire_in),
                )

            ui.label(f'Device created at {render_datetime(self.device.created_at)}, last update at {render_datetime(self.device.updated_at)}')

            with ui.row().classes('w-full place-content-end'):
                ui.button('Delete').props('color=negative').on_click(self._on_delete)
                ui.space()
                ui.button('Reload').props('color=secondary').on_click(self._reload)
                ui.button('Save').on_click(self._save)

    def _reload(self) -> None:
        self.device = get_device(self.project_name, self.device_name)
        ui.notify(f"Reloaded device {self.device.name}", type='positive')

    def _save(self) -> None:
        if self.device.name != self.device_name:
            if not is_valid_filename(self.device.name):
                ui.notify(f"Invalid device name {self.device.name}", type='negative')
                return
            new_path = os.path.join(app_config.projects_dir, self.device.project_name, self.device.name)
            if os.path.exists(new_path):
                ui.notify(f"Device {self.device.name} already exists", type='negative')
                return
            os.rename(
                os.path.join(app_config.projects_dir, self.device.project_name, self.device_name),
                new_path,
            )
            self.device = update_device(self.device)
            ui.notify(f"Renamed & saved device {self.device.name}", type='positive')
            ui.navigate.to(device_url(self.device.project_name, self.device.name, tab='Settings'))
            return
        self.device = update_device(self.device)
        ui.notify(f"Saved device {self.device.name}", type='positive')

    async def _on_delete(self) -> None:
        result = await build_dialog(
            'Delete Device',
            f'Are you sure you want to delete device {self.device_name}?',
            ['|2Cancel', '-Delete'],
        )
        if result == 'Delete':
            ui.notify(f"TODO Delete {self.project_name}/{self.device_name}", type='positive')
            ui.navigate.to(project_url(self.project_name, tab='Devices'))

# ***************************************************************************

class DeviceCreationDialog:
    """Dialog for creating a new device."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.device_name = ''
        with ui.dialog().style('width: 400px') as self.dialog:
            with ui.card().classes('w-full'):
                ui.label('Create Device').classes('text-h6 center')
                val_rules = {
                    "Device name contains invalid characters. Please use letters, numbers, underscore, plus and minus only.": lambda x: is_valid_filename(x)
                }
                ui.input(
                    label='Device Name', 
                    placeholder='enter a device name here', 
                    validation=val_rules
                ).bind_value(self, 'device_name').classes('w-full')
                with ui.row().classes('w-full place-content-end'):
                    ui.space()
                    ui.button('Cancel').props('color=secondary').on_click(lambda: self.dialog.submit(False))
                    ui.button('Create').on_click(lambda: self.dialog.submit(True))

    async def show(self):
        """Show the dialog and process the result."""
        result = await self.dialog
        if result and self.device_name and is_valid_filename(self.device_name):
            try:
                device = create_device(Device(name=self.device_name, project_name=self.project_name))
                ui.notify(f"Created device {device.name}", type='positive')
                ui.navigate.to(device_url(self.project_name, self.device_name, tab='Settings'))
            except Exception as e:
                ui.notify(f"Error creating device {self.device_name}: {e}", type='negative')
        else:
            ui.notify("Device creation cancelled", type='negative')


