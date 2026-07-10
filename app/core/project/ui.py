import datetime
from typing import Optional, cast

from nicegui import PageArguments, ui

from app.config import app_config
from app.core.token.backend import get_provisioning_token_adapter
from app.core.token.ui import TokenListCard
from app.core.device.backend import get_devices, is_device_online
from app.core.device.ui import ProjectDevicesTable
from app.core.logging.ui import LoggingCard
from app.core.telemetry.ui import TelemetryCard
from app.core.forwarding.ui import ForwardingCard
from app.core.device.files_ui import project_files_panel
from app.mqtt.ui import MqttGlobalConfigCard
from app.core.file.ui import FileConfigCard
from app.routes import device_url, project_url, projects_url
from app.util import is_valid_filename, render_datetime
from app.core.project.models import Project
from app.core.project.backend import create_project, delete_project, get_project, get_projects, project_adapter, rename_project
from app.core.alarm.ui import AlarmConfigCard, ProjectAlarmPanel
from niceview.form import ModelForm
from niceview.util import confirm_dialog, input_dialog

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************

async def all_projects_subpage(args: PageArguments, nav: ui.element):
    log.debug(f'project_main_page {args=}')
    nav.clear()

    async def _new_project():
        name = await input_dialog(
            'Create Project',
            label='Project Name',
            placeholder='enter a project name here',
            validator=is_valid_filename,
            error_message='Invalid name: use letters, digits, underscore, plus, minus only.',
        )
        if name is None:
            return
        project = create_project(name)
        ui.notify(f"Created project {project.name}", type='positive')
        ui.navigate.to(project_url(project.name, tab='General'))

    with ui.grid().classes('grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 w-full'):
        for project in get_projects():
            with ui.card().classes('w-full') as card:
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label(project.name).classes('font-bold grow')
                    if not project.is_active:
                        ui.chip('Inactive').props('dense color=grey text-color=white')
                with ui.row().classes('w-full gap-1'):
                    for i, tag in enumerate(project.tags):
                        if i <= 1:
                            ui.chip(tag).props('dense color=primary text-color=white')
                        if i == 2:
                            ui.chip(f'+{len(project.tags)-2}').props('dense color=primary text-color=white')
            card.on('click', lambda e, p=project.name: ui.navigate.to(project_url(p)))

        ui.button('New Project', icon='add').props('color=primary').on_click(_new_project).classes('w-full')

    with ui.card().classes('w-full q-mt-md dense'):
        MqttGlobalConfigCard()

# ***************************************************************************

async def project_subpage(args: PageArguments, nav: ui.element, project_id: str, tab: Optional[str] = None):
    nav.clear()
    try:
        get_project(project_id, check_active=False)
    except (ValueError, FileNotFoundError):
        ui.label(f'Project "{project_id}" does not exist.').classes('text-h6 text-negative')
        return

    with nav:
        ui.label('/').classes('text-h6 text-white opacity-50')
        ui.label(project_id).classes('text-h6 font-bold cursor-pointer text-white') \
            .on('click', lambda: ui.navigate.to(project_url(project_id)))

    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        general_tab = ui.tab('General')
        provisioning_tab = ui.tab('Provisioning')
        files_tab = ui.tab('Files')
        devices_tab = ui.tab('Devices')
    tab = tab if tab else dashboard_tab.label
    with ui.tab_panels(tabs, value=tab).classes('w-full'):
        with ui.tab_panel(dashboard_tab):
            await project_dashboard_panel(project_id)
        with ui.tab_panel(general_tab):
            await general_panel(project_id)
        with ui.tab_panel(provisioning_tab):
            await provisioning_panel(project_id)
        with ui.tab_panel(files_tab):
            project_files_panel(project_id)
        with ui.tab_panel(devices_tab):
            await devices_panel(project_id)

# ***************************************************************************

async def project_dashboard_panel(project_id: str) -> None:
    """Overview cards shown on the project Dashboard tab (auto-refreshes every 10 s)."""

    @ui.refreshable
    def _content() -> None:
        from app.mqtt.backend import connection_status as mqtt_connection_status
        project = get_project(project_id, check_active=False)
        devices = get_devices(project_id)
        active = [d for d in devices if d.is_active]
        pending_approval = [d for d in active if not d.is_provisioning_approved]
        online = [d for d in active if is_device_online(d, project.device_online_threshold_s)]
        seen = sorted([d for d in devices if d.last_seen_at], key=lambda d: d.last_seen_at, reverse=True)
        now = datetime.datetime.now(datetime.timezone.utc)

        with ui.grid().classes('grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full'):
            # Overview card
            with ui.card().classes('w-full'):
                # Row 1: project name — space — tags
                with ui.row().classes('items-center w-full gap-2'):
                    ui.label(project.name).classes('text-subtitle1 font-bold')
                    ui.space()
                    if project.tags:
                        for tag in project.tags[:4]:
                            ui.chip(tag).props('dense color=primary text-color=white')
                        if len(project.tags) > 4:
                            ui.chip(f'+{len(project.tags) - 4}').props('dense color=grey text-color=white')
                # Row 2: status chips
                with ui.row().classes('items-center gap-2'):
                    color = 'green' if project.is_active else 'grey'
                    ui.chip('Active' if project.is_active else 'Inactive').props(f'dense color={color} text-color=white')
                    http_color = 'green' if project.is_http_enabled else 'grey'
                    ui.chip('HTTP').props(f'dense color={http_color} text-color=white')
                    if project.is_mqtt_enabled:
                        mqtt_color = 'green' if mqtt_connection_status == 'connected' else 'orange'
                    else:
                        mqtt_color = 'grey'
                    ui.chip('MQTT').props(f'dense color={mqtt_color} text-color=white')
                if project.description:
                    ui.label(project.description).classes('text-body2 q-mt-xs')
                ui.label(f'Created: {render_datetime(project.created_at)}').classes('text-caption text-grey-7 q-mt-sm')

            # Device health card
            with ui.card().classes('w-full'):
                ui.label('Device Health').classes('text-subtitle1 font-bold')
                ui.separator()
                with ui.grid().classes('grid-cols-4 text-center gap-2 q-mt-xs'):
                    with ui.column().classes('items-center'):
                        ui.label(str(len(devices))).classes('text-h5 font-bold')
                        ui.label('Total').classes('text-caption text-grey-7')
                    with ui.column().classes('items-center'):
                        ui.label(str(len(active))).classes('text-h5 font-bold text-green')
                        ui.label('Active').classes('text-caption text-grey-7')
                    with ui.column().classes('items-center'):
                        ui.label(str(len(online))).classes('text-h5 font-bold text-green')
                        ui.label('Online').classes('text-caption text-grey-7')
                    with ui.column().classes('items-center'):
                        warn_color = 'text-orange' if pending_approval else 'text-grey'
                        ui.label(str(len(pending_approval))).classes(f'text-h5 font-bold {warn_color}')
                        ui.label('Pending').classes('text-caption text-grey-7')

            # System health card
            _system_health_card(project_id)

            # Recent activity card
            if seen:
                with ui.card().classes('w-full'):
                    ui.label('Recent Activity').classes('text-subtitle1 font-bold')
                    ui.separator()
                    for d in seen[:8]:
                        dot_color = 'text-green' if is_device_online(d, project.device_online_threshold_s) else 'text-grey'
                        with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
                            ui.icon('fiber_manual_record').classes(f'text-sm {dot_color}')
                            ui.label(d.name).classes('grow text-body2 cursor-pointer') \
                                .on('click', lambda _, dn=d.name: ui.navigate.to(device_url(project_id, dn)))
                            ui.label(render_datetime(d.last_seen_at)).classes('text-caption text-grey-7')

    _content()
    ui.timer(10.0, _content.refresh)
    ProjectAlarmPanel(project_id)


# ***************************************************************************

async def general_panel(project_id: str):
    with ui.grid().classes('w-full gap-4 grid-cols-1 lg:grid-cols-2'):
        with ui.card().classes('w-full'):
            project_card(project_id)
        with ui.card().classes('w-full dense'):
            ForwardingCard(project_id)
        with ui.card().classes('w-full dense'):
            TelemetryCard(project_id)
        with ui.card().classes('w-full dense'):
            LoggingCard(project_id)
        with ui.card().classes('w-full dense'):
            FileConfigCard(project_id)
        with ui.card().classes('w-full dense'):
            AlarmConfigCard(project_id)
        with ui.card().classes('w-full'):
            await danger_card(project_id)

# ***************************************************************************

def project_card(project_id: str) -> None:
    with ui.expansion('General').classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"').mark('general-form'):
        form = ModelForm.from_adapter(Project, project_adapter(project_id),
                                      include=['name', 'description', 'tags', 'is_active',
                                               'is_autocreate_devices', 'is_provisioning_autoapproval',
                                               'is_http_enabled', 'is_mqtt_enabled', 'mqtt_topic_base',
                                               'device_tokens_expire_in', 'device_token_length',
                                               'device_online_threshold_s'],
                                      autosave=True)
        form.render_field('name', editable=False).props('outlined dense').classes('w-full')
        form.render_field('description').props('outlined dense hide-bottom-space').classes('w-full')
        form.render_field('tags').props('outlined dense hide-bottom-space').classes('w-full')
        with ui.row().classes('w-full gap-4 q-mt-none'):
            form.render_field('is_active')
            form.render_field('is_autocreate_devices')
            form.render_field('is_provisioning_autoapproval')
        with ui.row().classes('w-full gap-4 q-mt-none'):
            form.render_field('is_http_enabled')
            form.render_field('is_mqtt_enabled')
        form.render_field('mqtt_topic_base').props('outlined dense').classes('w-full')
        form.render_field('device_tokens_expire_in').props('outlined dense').classes('w-full')
        form.render_field('device_token_length').props('outlined dense').classes('w-full')
        form.render_field('device_online_threshold_s').props('outlined dense').classes('w-full')
        p = cast(Project, form.item)  # niceview types form.item as Any; cast enables attribute access for bind_text_from
        ui.label().classes('text-caption text-grey-7').bind_text_from(
            p, 'updated_at',
            backward=lambda v: f'Created {render_datetime(p.created_at)}, updated {render_datetime(v)}'
        )

# ***************************************************************************

async def _rename_project(old_name: str, new_name: str) -> None:
    if not is_valid_filename(new_name):
        ui.notify(f"Invalid project name: {new_name}", type='negative')
        return
    if old_name == new_name:
        ui.notify(f"Project name unchanged: {new_name}", type='warning')
        return
    if not await confirm_dialog(
        'Rename Project',
        'Renaming a project also changes its URLs. Are you sure?',
    ):
        ui.notify("Project rename cancelled", type='negative')
        return
    try:
        rename_project(old_name, new_name)
        ui.notify(f"Project renamed from {old_name} to {new_name}", type='positive')
        ui.navigate.to(project_url(new_name))
    except Exception as e:
        log.exception(f"Failed to rename project from {old_name} to {new_name}: {e}")
        ui.notify(f"Failed to rename project: {e}", type='negative')


async def _delete_project(project_id: str) -> None:
    if not await confirm_dialog(
        'Delete Project',
        'Deleting a project is irreversible. Are you sure?',
        ok_label='Delete',
        ok_color='negative',
    ):
        ui.notify("Project deletion cancelled", type='negative')
        return
    try:
        delete_project(project_id)
        ui.notify(f"Project deleted: {project_id}", type='positive')
        ui.navigate.to(projects_url())
    except Exception as e:
        log.exception(f"Failed to delete project {project_id}: {e}")
        ui.notify(f"Failed to delete project: {e}", type='negative')


async def danger_card(project_id: str) -> None:
    with ui.expansion('Danger Zone', value=False).classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
        with ui.row().classes('w-full gap-4 q-mt-none'):
            val_rules = {
                "Invalid name: use letters, digits, underscore, plus, minus only.": lambda x: is_valid_filename(x)
            }
            name_widget = ui.input(
                label='New Project Name', 
                value=project_id, 
                validation=val_rules
            ).classes('grow').props('dense outlined')
            async def _on_rename() -> None:
                await _rename_project(project_id, name_widget.value)
            ui.button('Rename Project').props('color=negative').on_click(_on_rename)
        async def _on_delete() -> None:
            await _delete_project(project_id)
        ui.button('Delete Project').props('color=negative').classes('w-full').on_click(_on_delete)

# ***************************************************************************

async def provisioning_panel(project_id: str):
    with ui.expansion('Provisioning Tokens', value=True).classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
        ui.markdown('Long-lived shared secrets used by devices to obtain bearer tokens.').classes('text-caption q-ma-none')
        TokenListCard(get_provisioning_token_adapter(project_id),
                        token_length=app_config.provisioning_token_length,
                        expires_in=app_config.provisioning_token_expires_in)

# ***************************************************************************

async def devices_panel(project_id: str):
    with ui.expansion('Devices', value=True).classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
        ui.markdown("""
                _Devices_ are physical IoT nodes that connect to this project.
                Each device has its own directory and can be provisioned with a
                short-lived bearer token.

                Double-click a device to edit its settings. Use the "New" button to create a new device.
                """).classes('text-caption q-ma-none')
        ProjectDevicesTable(project_id)


# ***************************************************************************

def _system_health_card(project_id: str) -> None:
    """Read-only card showing last known health of external backends."""
    from app.health import get_project_health
    import app.mqtt.backend as _mqtt_backend

    health = get_project_health(project_id)
    mqtt_status = _mqtt_backend.connection_status

    with ui.card().classes('w-full'):
        ui.label('System Health').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.column().classes('gap-1 q-mt-xs w-full'):
            # MQTT
            mqtt_ok = mqtt_status == 'connected'
            _health_row('MQTT', mqtt_ok, mqtt_status if not mqtt_ok else '')

            # Telemetry backend
            tel = health.get(f'{project_id}:telemetry')
            if tel is not None:
                _health_row('Telemetry', tel['ok'], tel['message'] if not tel['ok'] else '')
            else:
                _health_row('Telemetry', None, 'No data received yet')

            # Logging backend
            log_h = health.get(f'{project_id}:logging')
            if log_h is not None:
                _health_row('Logging', log_h['ok'], log_h['message'] if not log_h['ok'] else '')
            else:
                _health_row('Logging', None, 'No data received yet')


def _health_row(label: str, ok: bool | None, detail: str) -> None:
    color = 'green' if ok is True else ('red' if ok is False else 'grey')
    icon = 'check_circle' if ok is True else ('error' if ok is False else 'help')
    with ui.row().classes('items-center gap-2 w-full'):
        ui.icon(icon).classes(f'text-{color}')
        ui.label(label).classes('text-body2 font-bold w-24')
        if detail:
            ui.label(detail).classes('text-caption text-grey-7 grow').style(
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
            )
        else:
            ui.space()


