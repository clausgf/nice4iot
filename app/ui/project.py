import copy
import datetime
from typing import Optional, Unpack

from nicegui import PageArguments, app, ui
from nicegui.events import ClickEventArguments

from app.core.auth import generate_token
from app.core.logging.logging import LoggingBackendTypes, create_log
from app.core.telemetry.models import TelemetryBackendTypes
from app.core.telemetry.telemetry import create_tel
from app.ui.forwarding_config_card import ForwardingConfigCard
from app.ui.util import build_dialog
from app.util import is_valid_filename, render_datetime
from app.config import app_config
from app.core.models import AuthToken, Project
from app.core.project import ProjectModelAdapter, create_project, get_project, get_projects, update_project
from app.ui.theme import frame

from niceview.modeledit import _EditGridWrapperInputs, EditGridWrapper
from niceview.modelgrid import ModelGrid

import logging
log = logging.getLogger("uvicorn")

DEFAULT_PROVISIONING_TOKEN_LENGTH = 64
DEFAULT_PROVISIONING_TOKEN_EXPIRY_DAYS = 7


# ***************************************************************************

class EditProjectGridWrapper(EditGridWrapper):
    def __init__(self, project_grid: ModelGrid) -> None:
        super().__init__(project_grid, title='Projects')
    
    async def update_item(self, event: ClickEventArguments) -> None:
        project_name = await self._get_selected_row_key()
        if not project_name:
            ui.notify('No project selected. Please select a project first!')
            return
        ui.navigate.to(f"/{project_name}")
    
    async def delete_item(self, event: ClickEventArguments) -> None:
        project_name = await self._get_selected_row_key()
        if not project_name:
            ui.notify('No project selected. Please select a project first!')
            return
        result = await build_dialog('Delete Project', 
                                    f'Are you sure you want to delete the project {project_name}?', 
                                    ['|2Cancel', '-Delete'])
        if result == 'Delete':
            ui.notify(f"Delete project {project_name}", type='positive')
        else:
            ui.notify('Project deletion cancelled', type='negative')

        ui.navigate.to(f"/")


async def all_projects_subpage(args: PageArguments, title: ui.label, breadcrumbs: ui.element):
    log.info(f'project_main_page {args=}')
    title.text = 'Projects'
    breadcrumbs.clear()
    with breadcrumbs:
        ui.element('q-breadcrumbs-el').props('icon=home').on('click', lambda: ui.navigate.to('/'))

    project_grid = ModelGrid(
        Project, ProjectModelAdapter(),
        fields=['name', 'tags', 'created_at', 'updated_at'],
        rowSelection='single',
    )
    project_edit = EditProjectGridWrapper(project_grid)
    # project_grid.on_select(lambda e: ui.navigate.to(f"/{e.value['name']}"))
    project_edit.render()

# ***************************************************************************

async def project_subpage(args: PageArguments, title: ui.label, breadcrumbs: ui.element, project_id: str, tab: Optional[str] = None):
    title.text = 'Project ' + project_id
    breadcrumbs.clear()
    with breadcrumbs:
        ui.element('q-breadcrumbs-el').props('icon=home').on('click', lambda: ui.navigate.to('/'))
        ui.element('q-breadcrumbs-el').props(f'label={project_id}').on('click', lambda: ui.navigate.to(f'/{project_id}'))

    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        settings_tab = ui.tab('Settings')
        devices_tab = ui.tab('Devices')
    tab = 'Dashboard' if not tab else tab
    with ui.tab_panels(tabs, value=tab) as panels:
        with ui.tab_panel(dashboard_tab):
            ui.label('Alarms').classes('text-h6 font-bold')
            ui.label('Monitoring').classes('text-h6 font-bold')
        with ui.tab_panel(settings_tab):
            await project_settings_panel(args, project_id)
        with ui.tab_panel(devices_tab):
            ui.label('Project Devices').classes('text-h6 font-bold')
            ui.button('Edit Device MyDevice').on_click(lambda: ui.navigate.to(f'/{project_id}/MyDevice'))

# ***************************************************************************

async def project_settings_panel(args: PageArguments, project_id: str):
    with ui.column().classes('w-full'):
        ui.label('Project Settings').classes('text-h6 font-bold')
        ui.label('Provisioning Tokens').classes('text-h6 font-bold')


# ***************************************************************************

@ui.page('/projects')
async def projects_page():
    """Projects page."""
    project_new_dialog = ProjectCreationDialog()
    with frame('Projects'):
        cols = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'sortable': True},
            {'name': 'tags', 'label': 'Tags', 'field': 'tags', 'sortable': True},
            {'name': 'created_at', 'label': 'Created At', 'field': 'created_at', 'sortable': True},
            {'name': 'updated_at', 'label': 'Updated At', 'field': 'updated_at', 'sortable': True},
        ]
        data = []
        for project in get_projects():
            data.append({
                'id': project.name,
                'name': project.name,
                'tags': ', '.join(project.tags) if project.tags else '',
                'created_at': render_datetime(project.created_at),
                'updated_at': render_datetime(project.updated_at),
            })
        with ui.table(title='Projects', columns=cols, rows=data).classes('w-full') as table:
            with table.add_slot('top-right'):
                with ui.row():
                    with ui.input(placeholder='Search').props('type=search').bind_value(table, 'filter').add_slot('append'):
                        ui.icon('search')
                    ui.button('New', icon='add').on_click(project_new_dialog.show).props('color=primary').classes('w-24')
            table.on('row-click', lambda msg: ui.navigate.to(f'/projects/{msg.args[1]["id"]}'))


# ***************************************************************************

class ProjectCreationDialog:
    """Dialog for creating a new project."""

    def __init__(self):
        self.project_name = ''
        self.telemetry_backend = TelemetryBackendTypes.SQL
        self.logging_backend = LoggingBackendTypes.LOKI
        with ui.dialog().style('width: 400px') as self.dialog:
            with ui.card().classes('w-full'):
                ui.label('Create Project').classes('text-h6 center')
                val_rules = { "Project name contains invalid characters. Please use letters, number, underscore, plus and minus only.": lambda x: is_valid_filename(x) }
                ui.input(label='Project Name', placeholder='enter a project name here', validation=val_rules).bind_value(self, 'project_name').classes('w-full')
                with ui.dropdown_button("Choose a Telemetry Backend",auto_close=True):
                    ui.item('Prometheus',on_click=lambda: (lambda obj: setattr(obj,'telemetry_backend',TelemetryBackendTypes.PROMETHEUS))(self))
                    ui.item('InfluxDB',on_click=lambda: (lambda obj: setattr(obj,'telemetry_backend',TelemetryBackendTypes.SQL))(self))
                    ui.item('SQL',on_click=lambda: (lambda obj: setattr(obj,'telemetry_backend',TelemetryBackendTypes.INFLUX2)(self)))
                with ui.row().classes('w-full place-content-end'):
                    ui.space()
                    ui.button('Cancel').props('color=secondary').on_click(lambda: self.dialog.submit(False))
                    ui.button('Create').on_click(lambda: self.dialog.submit(True))

    async def show(self):
        """Show the dialog."""
        result = await self.dialog
        if result and self.project_name and is_valid_filename(self.project_name):
            project = create_project(Project(name=self.project_name,telemetryBackend=self.telemetry_backend,logging_backend=self.logging_backend))
            create_tel(self.project_name,self.telemetry_backend)
            create_log(self.project_name,self.logging_backend)
            ui.notify(f"Created project {project.name}", type='positive'),
            ui.navigate.to(f'/projects/{project.name}?tab=Settings')
        else:
            ui.notify("Project creation cancelled", type='negative')


# ***************************************************************************

class ProvisioningTokenDialog:
    """Dialog for editing/creating provisioning token."""

    def __init__(self, project_settings: "ProjectSettingsCard"):
        self.project_settings = project_settings
        self.token_index = -1
        self.token = AuthToken(value='')
        self.heading = 'Create Provisioning Token'
        self.ok_button = ''
        self.token_length = DEFAULT_PROVISIONING_TOKEN_LENGTH
        self.last_use = ''
        self.creation = ''

        with ui.dialog().style('width: 400px') as self.dialog, ui.card():
            ui.label().classes('text-h6 center').bind_text_from(self, 'heading')
            ui.checkbox(text='Active').bind_value(self.token, 'is_active')
            ui.input(label='Token').bind_value(self.token, 'value').classes('w-full')
            with ui.row():
                ui.number(label='Token Length', precision=0, min=1).bind_value(self, 'token_length')
                ui.button('Generate', icon='loop').props('color=primary').on_click(lambda: (
                    self.set_random_token(),
                    ui.notify(f"Generated new token {self.token.value}", type='positive'),
                ))
                ui.button('Copy', icon='content_copy').props('color=primary').on_click(lambda: (
                    ui.clipboard.write(self.token.value),
                    ui.notify(f"Copied token {self.token.value} to clipboard", type='positive'),
                ))
            ui.label().bind_text_from(self, 'last_use').classes('text-sm text-gray-500')
            ui.label().bind_text_from(self, 'creation').classes('text-sm text-gray-500')

            with ui.row().classes('w-full place-content-end'):
                self.delete_button = ui.button('Delete').props('color=red').on_click(self.on_delete)
                ui.space()
                ui.button('Cancel').props('color=secondary').on_click(self.on_cancel)
                ui.button().bind_text_from(self, 'ok_button').on_click(self.on_ok)

    def show(self, token_index: int = -1, token: AuthToken = None) -> None:
        """Open the dialog for editing/creating a provisioning token."""
        # setup values
        self.token_index = token_index
        if token:
            # copy contents to the self.token instance
            for field, value in token.model_dump().items():
                setattr(self.token, field, value)
            self.heading = 'Edit Provisioning Token'
            self.ok_button = 'Save'
        else:
            # copy contents to the self.token instance
            for field, value in AuthToken(value='').model_dump().items():
                setattr(self.token, field, value)
            self.set_random_token()
            self.heading = 'Create Provisioning Token'
            self.ok_button = 'Create'
        self.token_length = DEFAULT_PROVISIONING_TOKEN_LENGTH
        self.last_use = f'Last use at {render_datetime(token.last_use_at)}' if token_index >= 0 else 'never'
        self.creation = f'Created at {render_datetime(token.created_at)}, last update at {render_datetime(token.updated_at)}' if token_index >= 0 else ''
        self.delete_button.set_visibility(self.token_index >= 0)
        self.dialog.open()

    def set_random_token(self) -> None:
        """Create a random token of given length."""
        self.token.value = generate_token(self.token_length)

    def on_ok(self) -> None:
        """Handle the OK button click."""
        now = datetime.datetime.now(datetime.timezone.utc)
        if self.token_index < 0:
            self.token.created_at = now
        #self.token.updated_at = now
        self.project_settings.on_token_update(self.token_index, copy.copy(self.token))
        self.dialog.close()

    def on_cancel(self) -> None:
        """Handle the cancel button click."""
        self.dialog.close()

    async def on_delete(self) -> None:
        """Handle the delete button click."""
        result = await build_dialog('Delete Provisioning Token', 
                                    f'Are you sure you want to delete the provisioning token {self.token.value}?', 
                                    ['|2Cancel', '-Delete'])
        if result == 'Delete':
            self.project_settings.on_token_delete(self.token_index)
        else:
            ui.notify('Token deletion cancelled', type='negative')
        self.dialog.close()


# ***************************************************************************

class ProjectSettingsCard:
    """Card for project settings."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.project = get_project(project_name)
        self.token_expiry = self.project.device_tokens_expire_in.days   # has to be stored separately for editing
        self.provisioning_cols = [
            {'name': 'is_active', 'label': 'Active', 'field': 'is_active', 'sortable': True },
            {'name': 'token', 'label': 'Token', 'field': 'value', 'sortable': True },
            {'name': 'last_use_at', 'label': 'Last use', 'field': 'last_use_at', 'sortable': True },
        ]
        self.provisioning_rows = []
        self.update_provisioning_rows()
        self.provisioning_token_dialog = ProvisioningTokenDialog(self)
        with ui.card().classes('w-full') as self.card:
            ui.label(f'{self.project.name.capitalize()} Settings').tailwind('text-lg')
            ui.separator()
            ui.input(label='Project Name', placeholder='placeholder').bind_value(self.project, 'name').classes('w-full')
            ui.textarea(label='Project Description').bind_value(self.project, 'description').classes('w-full')
            ui.checkbox(text='Project is active').bind_value(self.project, 'is_active')
            ui.checkbox(text='Auto create devices').bind_value(self.project, 'is_autocreate_devices')
            ui.checkbox(text='Auto approve provisioning').bind_value(self.project, 'is_provisioning_autoapproval')
            ui.number(label='Auth token expiry (days)').bind_value(self, 'token_expiry')

            # forwardings
            self.forwardings_card = ForwardingConfigCard(self.project_name)

            # table with provisioning tokens
            self.provisioning_table = ui.table(title='Provisioning Tokens', columns=self.provisioning_cols, rows=self.provisioning_rows).classes('w-full')
            with self.provisioning_table.add_slot('top-right'):
                with ui.row():
                    with ui.input(placeholder='Search').props('type=search').bind_value(self.provisioning_table, 'filter').add_slot('append'):
                        ui.icon('search')
                    ui.button('New', icon='add').props('color=primary').classes('w-24').on_click(lambda: self.provisioning_token_dialog.show())
            self.provisioning_table.on('row-click', lambda msg: (
                id := msg.args[1]['id'],
                index := next((i for i, t in enumerate(self.provisioning_rows) if t['id'] == id), -1),
                token := self.project.provisioning_tokens[index] if index >= 0 else None,
                self.provisioning_token_dialog.show(index, token),
            ))

            ui.label(f'Project created at {render_datetime(self.project.created_at)}, last update at {render_datetime(self.project.updated_at)}')
            with ui.row().classes('w-full place-content-end'):
                ui.button('Delete').props('color=red').on_click(lambda: (
                    # TODO confirm delete dialog
                    # delete_project(project.name),
                    ui.notify(f"TODO Deleted {self.project.name}", type='positive'),
                    ui.navigate.to('/projects'),
                ))
                ui.space()
                ui.button('Reload').props('color=secondary').on_click(lambda: (
                    project := get_project(self.project_name),
                    self.update_provisioning_rows(),
                    ui.notify(f"Reloaded project {self.project.name}", type='positive'),
                ))
                ui.button('Save').props('color=primary').on_click(lambda: (
                    self.save(),
                ))

    def update_provisioning_rows(self) -> None:
        """Update the provisioning rows in the table."""
        self.provisioning_rows.clear()
        for token in self.project.provisioning_tokens:
            self.provisioning_rows.append({
                'id': token.value,
                'is_active': token.is_active,
                'token': (token.value[:17] + '...') if len(token.value) > 20 else token.value,
                'last_use_at': render_datetime(token.last_use_at),
            })

    def save(self) -> None:
        """Save self.project."""
        self.project.device_tokens_expire_in = datetime.timedelta(days=self.token_expiry)
        if self.project.name != self.project_name:
            if not is_valid_filename(self.project.name):
                ui.notify(f"Invalid project name {self.project.name}, project was not saved", type='negative')
                return
            if os.path.exists(os.path.join(app_config.projects_dir, self.project.name)):
                ui.notify(f"Project {self.project.name} already exists, project was not saved", type='negative')
                return
            # rename project
            os.rename(os.path.join(app_config.projects_dir, self.project_name), os.path.join(app_config.projects_dir, self.project.name))
            self.project = update_project(self.project)
            ui.notify(f"Renamed project {self.project_name} to {self.project.name} & saved project", type='positive')
            ui.navigate.to(f'/projects/{self.project.name}')
        self.project = update_project(self.project)
        ui.notify(f"Saved project {self.project.name}", type='positive')

    def on_token_delete(self, token_index: int) -> None:
        """Handle token deletion."""
        deleted = self.project.provisioning_tokens.pop(token_index)
        self.provisioning_rows.remove(next((t for t in self.provisioning_rows if t['id'] == deleted.value), None))
        self.provisioning_table.update()
        ui.notify(f"Deleted provisioning token {deleted.value}", type='positive')

    def on_token_update(self, token_index: int, token: AuthToken) -> None:
        """Handle token change."""
        if token_index < 0:
            self.project.provisioning_tokens.append(token)
        else:
            self.project.provisioning_tokens[token_index] = token
        self.update_provisioning_rows()
        self.provisioning_table.update()
        ui.notify(f"Updated provisioning token {token.value}", type='positive')


