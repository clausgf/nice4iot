import copy
import datetime
import os
from typing import Optional
from nicegui import PageArguments, app, ui

from app.core.auth import create_token
from app.ui.theme import frame
from app.util import is_valid_filename, render_datetime
from app.config import app_config
from app.core.device import get_device, get_devices, update_device
from app.core.models import AuthToken
from app.core.project import get_project
from app.core.telemetry.telemetry import get_tel
from app.ui.util import build_dialog

from niceview.modelgrid import ModelGrid

import logging
log = logging.getLogger("uvicorn")


device_selection_cols = [
    {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'sortable': True},
]
device_rows = [
    {'id': 0, 'name': 'esp32-123456', 'tags': '', 'provisioning_ok': True, 'last_seen': '2021-09-01 12:34:56', 'status': 'Online', 'actions': 'Edit'},
    {'id': 1, 'name': 'esp32-123457', 'tags': '', 'provisioning_ok': True, 'last_seen': '2021-09-01 12:34:56', 'status': 'Online', 'actions': 'Edit'},
]


# ***************************************************************************

@ui.page('/projects/{project_name:str}/devices/{device_name:str}')
async def devices_page(project_name: str, device_name: str, tab: Optional[str] = None):
    """Device page."""
    # check if device exists, if not, redirect to project/devices page
    device = get_device(project_name, device_name)
    if not device:
        ui.notify(f"Device {project_name}/{device_name} does not exist", type='negative')
        ui.navigate.to(f'/projects/{project_name}?tab=Devices')
        return

    with frame(f'Device {project_name.capitalize()}/{device_name}'):
        with ui.tabs().classes('w-full') as tabs:
            dashboard_tab = ui.tab('Dashboard')
            settings_tab = ui.tab('Settings')

        with ui.tab_panels(tabs).classes('w-full'):
            with ui.tab_panel(dashboard_tab):
                ui.textarea('This note is kept between visits') \
                    .classes('w-96').bind_value(app.storage.user, 'note')
                ui.button('Click me')
            with ui.tab_panel(settings_tab):
                settings_card = DeviceSettingsCard(project_name, device_name)
        if tab:
            tabs.set_value(tab)
        else:
            tabs.set_value(dashboard_tab)


# ***************************************************************************

class DeviceCreationDialog:
    """Dialog for creating a new device."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.device_name = ''
        with ui.dialog().style('width: 400px') as self.dialog:
            with ui.card().classes('w-full'):
                ui.label('Create Device').classes('text-h6 center')
                val_rules = { "Device name contains invalid characters. Please use letters, number, underscore, plus and minus only.": lambda x: is_valid_filename(x) }
                ui.input(label='Device Name', placeholder='enter a device name here', validation=val_rules).bind_value(self, 'device_name').classes('w-full')
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
                ui.notify(f"Created device {device.name}", type='positive'),
                ui.navigate.to(f'/projects/{self.project_name}/devices/{self.device_name}?tab=Settings')
            except Exception as e:
                ui.notify(f"Error creating device {self.device_name}: {e}", type='negative')
        else:
            ui.notify("Device creation cancelled", type='negative')


# ***************************************************************************

class ProjectDevicesTable:
    """Table containing a project's devices."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.device_new_dialog = DeviceCreationDialog(project_name)
        self.devices = get_devices(project_name)

        self.table = ModelGrid(Device, 
                               title=f'{project_name.capitalize()}\'s Devices',
                               fields=['is_active', 'name', 'location', 'last_seen_at', 'is_provisioning_approved'], 
                               defaultColDef = {'sortable': True, 'editable': True},
                               
                               classes='w-full')

        # table with devices
        self.devices_table = ui.table(title=f'{project_name.capitalize()}\'s Devices', 
                                      columns=self.devices_cols, rows=self.devices_rows).classes('w-full')
        with self.devices_table.add_slot('top-right'):
            with ui.row():
                with ui.input(placeholder='Search').props('type=search').bind_value(self.devices_table, 'filter').add_slot('append'):
                    ui.icon('search')
                ui.button('New', icon='add').props('color=primary').classes('w-24').on_click(self.device_new_dialog.show)
        self.devices_table.on('row-click', lambda msg: (
            ui.navigate.to(f'/projects/{self.project_name}/devices/{msg.args[1]["id"]}?tab=Settings'),
        ))


# ***************************************************************************

@ui.page('/projects/{project_name:str}')
async def projects_project_page(project_name: str, request: Request, tab: Optional[str] = None):
    """Project page."""
    # check if project exists, if not, redirect to projects page
    project = get_project(project_name)
    if not project:
        ui.notify(f"Project {project_name} does not exist", type='negative')
        ui.navigate.to('/projects')
        return
    
    with frame(f'Project {project.name.capitalize()}'):
        with ui.tabs().classes('w-full') as tabs:
            dashboard_tab = ui.tab('Dashboard')
            devices_tab = ui.tab('Devices')
            settings_tab = ui.tab('Settings')
        with ui.tab_panels(tabs).classes('w-full'):
            with ui.tab_panel(dashboard_tab):
                ui.textarea('This note is kept between visits') \
                    .classes('w-96').bind_value(app.storage.user, 'note')
                ui.button('Click me')
                project = get_project(project_name)
                try:
                    tel_backend = get_tel(project_name,project.telemetryBackend)
                    metrics = await tel_backend.read(end=datetime.datetime.now(pytz.timezone(app_config.timezone)),timeframe=datetime.timedelta(days=3),step='1m')
                    fig = go.Figure()
                    for metric in metrics:
                        vals = metric["values"]
                        name = metric["metric"]["__name__"].split("_")[-1]
                        device = metric["metric"]["device"]
                        kind = metric["metric"]["kind"]
                        fig.add_trace(go.Scatter(x=[datetime.datetime.fromtimestamp(val[0],pytz.timezone(app_config.timezone)) for val in vals],y=[float(val[1]) for val in vals]
                                                ,name=f'{name},{device},{kind}'))
                    #fig['layout']['yaxis'].update(autorange=True)
                    ui.plotly(fig).classes('w-full h-100')
                except Exception as e:
                    ui.notify(f'Could not display metric graph:{e}')
            with ui.tab_panel(devices_tab):
                device_card = ProjectDevicesTable(project_name)
                with ui.column():
                    with ui.list().props('bordered separator'):
                        ui.item_label('Devices').props('header').classes('text-bold')
                        ui.separator()
                        with ui.item(on_click=lambda: ui.notify('Selected contact 1')):
                            with ui.item_section().props('avatar'):
                                ui.icon('person')
                            with ui.item_section():
                                ui.item_label('Nice Guy')
                                ui.item_label('name').props('caption')
                            with ui.item_section().props('side'):
                                ui.icon('chat')
                        with ui.item(on_click=lambda: ui.notify('Selected contact 2')):
                            with ui.item_section().props('avatar'):
                                ui.icon('person')
                            with ui.item_section():
                                ui.item_label('Nice Person')
                                ui.item_label('name').props('caption')
                            with ui.item_section().props('side'):
                                ui.icon('chat')
                with ui.column():
                    with ui.table(title='Devices', columns=device_selection_cols, rows=device_rows).classes('w-96') as table:
                        with table.add_slot('header'):
                            with ui.input(placeholder='Search').props('type=search').bind_value(table, 'filter').add_slot('append'):
                                ui.icon('search')
                with ui.column():
                    with ui.card().tight():
                        ui.textarea('This note is kept between visits') \
                            .classes('w-96').bind_value(app.storage.user, 'note')
                        ui.button('Click me')
                    with ui.card().tight():
                        ui.textarea('This note is kept between visits') \
                            .classes('w-96').bind_value(app.storage.user, 'note')
                        ui.button('Click me')

            with ui.tab_panel(settings_tab):
                settings_card = ProjectSettingsCard(project_name)

        # set the tab from the url query parameter
        if tab:
            tabs.set_value(tab)
        else:
            tabs.set_value(dashboard_tab)
        request
        tabs.on_value_change(lambda msg: (
            # TODO das funktioniert noch nicht!
            print(request.url_for('projects_project_page', project_name=project_name, tab=msg.value)),
            ui.navigate.history.push(
                request.url_for('projects_project_page', project_name=project_name, tab=msg.value)
            )))


# ***************************************************************************

class AuthTokenDialog:
    """Dialog for editing device authentication tokens."""

    def __init__(self, device_settings: "DeviceSettingsCard", token_duration_days: int):
        self.device_settings = device_settings
        self.token_duration_days = token_duration_days
        self.token = AuthToken(value='', created_at=datetime.datetime.now(datetime.timezone.utc), expires_at=datetime.datetime.now(datetime.timezone.utc))
        self.created_at = ''
        self.expires_at = ''
        self.token_index = -1

        with ui.dialog().style('width: 400px') as self.dialog, ui.card():
            ui.label('Edit authentication token').classes('text-h6 center')
            token_input = ui.input(label='Token').bind_value(self.token, 'value').classes('w-full')
            with token_input.add_slot('after'):
                ui.button(icon='content_copy').props('size=sm').on_click(lambda: ui.clipboard.write(self.token.value))
            with ui.row():
                ui.label().bind_text(self, 'expires_at')
                ui.button('Refresh', icon='loop').props('size=sm').on_click(self.on_refresh_expiry)
            ui.label().bind_text_from(self, 'created_at').classes('text-sm text-gray-500')

            with ui.row().classes('w-full place-content-end'):
                self.delete_button = ui.button('Delete').props('color=red').on_click(self.on_delete)
                ui.space()
                ui.button('Cancel').props('color=secondary').on_click(self.on_cancel)
                ui.button('Ok').bind_text_from(self, 'ok_button').on_click(self.on_ok)

    def show(self, token_index: int = -1, token: AuthToken = None) -> None:
        """Open the dialog for editing/creating a token."""
        # setup values
        self.token_index = token_index
        if token:
            # copy contents to the self.token instance
            for field, value in token.model_dump().items():
                setattr(self.token, field, value)
        else:
            # copy contents to the self.token instance
            for field, value in create_token(datetime.timedelta(days=self.token_duration_days), app_config.device_token_length).model_dump().items():
                setattr(self.token, field, value)
        self.created_at = f'Created at {render_datetime(token.created_at)}'
        self.expires_at = f'Expires at {render_datetime(token.expires_at)}'
        self.delete_button.set_visibility(self.token_index >= 0)
        self.dialog.open()

    def on_refresh_expiry(self) -> None:
        """Handle the refresh button click."""
        now = datetime.datetime.now(datetime.timezone.utc)
        self.token.expires_at = now + datetime.timedelta(days=self.token_duration_days)
        self.expires_at = f'Expires at {render_datetime(self.token.expires_at)}'

    async def on_delete(self) -> None:
        """Handle the delete button click."""
        result = await build_dialog('Delete Authentication Token', 
                                    f'Are you sure you want to delete the authentication token {self.token.value}?', 
                                    ['|2Cancel', '-Delete'])
        if result == 'Delete':
            self.device_settings.on_token_delete(self.token_index)
        else:
            ui.notify('Token deletion cancelled', type='negative')
        self.dialog.close()

    def on_cancel(self) -> None:
        """Handle the cancel button click."""
        self.dialog.close()

    def on_ok(self) -> None:
        """Handle the OK button click."""
        now = datetime.datetime.now(datetime.timezone.utc)
        if self.token_index < 0:
            self.token.created_at = now
        self.device_settings.on_token_update(self.token_index, copy.copy(self.token))
        self.dialog.close()


# ***************************************************************************

class DeviceSettingsCard:
    """Card for device settings."""

    def __init__(self, project_name: str, device_name: str):
        self.project_name = project_name
        self.device_name = device_name
        self.device = get_device(project_name, device_name)
        self.authtoken_cols = [
            {'name': 'token', 'label': 'Token', 'field': 'value' },
            {'name': 'created_at', 'label': 'Created at', 'field': 'created_at' },
            {'name': 'expires_at', 'label': 'Expires at', 'field': 'expires_at' },
        ]
        self.authtoken_rows = []
        self.update_authtoken_rows()
        project = get_project(self.project_name)
        self.authtoken_dialog = AuthTokenDialog(self, project.device_tokens_expire_in.days)
        with ui.card().classes('w-full') as self.card:
            ui.label(f'{self.device.project_name.capitalize()}/{self.device.name} Settings').tailwind('text-lg')
            ui.separator()
            ui.input(label='Name').bind_value(self.device, 'name').classes('w-full')
            ui.input(label='Location').bind_value(self.device, 'location').classes('w-full')
            ui.textarea(label='Description').bind_value(self.device, 'description').classes('w-full')
            ui.checkbox(text='Device is active').bind_value(self.device, 'is_active')
            ui.checkbox(text='Provisioning approved').bind_value(self.device, 'is_provisioning_approved')
            ui.label(f'Last seen at {render_datetime(self.device.last_seen_at)}')
            ui.label(f'Last provisioning request at {render_datetime(self.device.last_provisioning_request_at)}')
            ui.label(f'Last successful provisioning at {render_datetime(self.device.last_provisioned_at)}')

            # table with auth keys
            self.authtoken_table = ui.table(title='Authentication Tokens', column_defaults={'sortable': True}, columns=self.authtoken_cols, rows=self.authtoken_rows).classes('w-full')
            with self.authtoken_table.add_slot('top-right'):
                with ui.row():
                    with ui.input(placeholder='Search').props('type=search').bind_value(self.authtoken_table, 'filter').add_slot('append'):
                        ui.icon('search')
                    ui.button('New', icon='add').props('color=primary').classes('w-24').on_click(self.add_authtoken)
            self.authtoken_table.on('row-click', lambda msg: (
                # TODO
                id := msg.args[1]['id'],
                index := next((i for i, t in enumerate(self.authtoken_rows) if t['id'] == id), -1),
                token := self.device.tokens[index] if index >= 0 else None,
                self.authtoken_dialog.show(index, token),
            ))

            ui.label(f'Device created at {render_datetime(self.device.created_at)}, last update at {render_datetime(self.device.updated_at)}')

            with ui.row().classes('w-full place-content-end'):
                ui.button('Delete').props('color=negative').on_click(lambda: (
                    # TODO confirm delete dialog
                    # delete_device(device.project_name, device.name),
                    ui.notify(f"TODO Deleted {self.device.project_name}/{self.device_name}", type='positive'),
                    ui.navigate.to(f'/projects/{self.project_name}?tab=Devices'),
                ))
                ui.space()
                ui.button('Reload').props('color=secondary').on_click(lambda: (
                    device := get_device(self.project_name), # type: ignore
                    self.update_authtoken_rows(),
                    ui.notify(f"Reloaded device {self.device.project_name}/{self.device.name}", type='positive'),
                ))
                ui.button('Save').on_click(lambda: (
                    self.save(),
                ))

    def update_authtoken_rows(self) -> None:
        """Update the authkey rows in the table."""
        self.authtoken_rows.clear()
        for token in self.device.tokens:
            self.authtoken_rows.append({
                'id': token.value,
                'value': (token.value[:17] + '...') if len(token.value) > 20 else token.value,
                'created_at': render_datetime(token.created_at),
                'expires_at': render_datetime(token.expires_at),
            })

    def save(self) -> None:
        """Save self.device."""
        if self.device.name != self.device_name:
            if not is_valid_filename(self.device.name):
                ui.notify(f"Invalid device name {self.device.name}, device was not saved", type='negative')
                return
            if os.path.exists(os.path.join(app_config.projects_dir, self.device.project_name, self.device.name)):
                ui.notify(f"Device {self.device.project_name}/{self.device.name} already exists, device was not saved", type='negative')
                return
            # rename device
            os.rename(os.path.join(app_config.projects_dir, self.device.project_name, self.device_name), 
                      os.path.join(app_config.projects_dir, self.device.project_name, self.device.name))
            self.device = update_device(self.device)
            ui.notify(f"Renamed device {self.device.project_name}/{self.device_name} to {self.device.name} & saved device", type='positive')
            ui.navigate.to(f'/projects/{self.device.project_name}/devices/{self.device.name}?tab=Settings')
        self.device = update_device(self.device)
        ui.notify(f"Saved device {self.device.name}", type='positive')

    def add_authtoken(self) -> None:
        """Add a new auth token."""
        project = get_project(self.project_name)
        self.device.tokens.append(create_token(project.device_tokens_expire_in, app_config.device_token_length))
        ui.notify(f"New auth token added for device {self.device.project_name}/{self.device.name}", type='positive')
        self.update_authtoken_rows()
        self.authtoken_table.update()

    def on_token_delete(self, token_index: int) -> None:
        """Handle token deletion."""
        deleted = self.device.tokens.pop(token_index)
        self.authtoken_rows.remove(next((t for t in self.authtoken_rows if t['id'] == deleted.value), None))
        self.authtoken_table.update()
        ui.notify(f"Deleted authentication token {deleted.value}", type='positive')

    def on_token_update(self, token_index: int, token: AuthToken) -> None:
        """Handle token change."""
        if token_index < 0:
            self.device.tokens.append(token)
        else:
            self.device.tokens[token_index] = token
        self.update_authtoken_rows()
        self.authtoken_table.update()
        ui.notify(f"Updated authentication token {token.value}", type='positive')


# ***************************************************************************

