from typing import Optional, cast

import anyio
from nicegui import PageArguments, ui

from app.config import app_config
from app.core.token.backend import get_provisioning_token_adapter
from app.core.token.ui import TokenListCard
from app.core.device.backend import get_devices, is_device_online
from app.core.device.ui import ProjectDevicesTable
from app.core.logging.ui import LoggingCard
from app.core.telemetry.ui import TelemetryCard
from app.core.forwarding.ui import ForwardingCard
from app.core.file.browser_ui import project_files_panel
from app.core.firmware.ui import firmware_source_card
from app.paths import project_dir
from app.core.file.ui import file_config_card
from app.routes import device_url, project_url, projects_url
from app.ui import config_expansion, refresh_breadcrumbs, status_avatar
from app.util import is_valid_name, render_datetime
from app.core.project.models import Project
from app.core.project.backend import create_project, delete_project, get_project, get_projects, project_adapter, rename_project
from app.core.alarm.ui import alarm_config_card, dashboard_alarms_card
from app.exceptions import NotFoundError
from app.extensions import (
    get_project_dashboard_cards, get_project_general_cards,
    get_project_tabs, get_registered_extension_names, maybe_await,
)
from niceview import ModelForm
from niceview.util import confirm_dialog, input_dialog

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************

async def all_projects_subpage(args: PageArguments, nav: ui.element):
    log.debug(f'project_main_page {args=}')
    refresh_breadcrumbs(nav)
    
    async def _new_project():
        name = await input_dialog(
            'Create Project',
            label='Project Name',
            placeholder='enter a project name here',
            validator=is_valid_name,
            error_message='Invalid name: letters, digits, underscore only; must not start with a digit.',
        )
        if name is None:
            return
        project = create_project(name)
        ui.notify(f"Created project {project.name}", type='positive')
        ui.navigate.to(project_url(project.name, tab='General'))

    with ui.grid().classes('grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full'):
        for project in get_projects():
            # Project card
            with ui.card().tight().classes('w-full') as card:
                with ui.card_section().props('dense').classes('w-full'):
                    # Row 0 (header): project name, tags
                    with ui.row().classes('w-full gap-0 q-mt-sm'):
                        status_avatar(True if project.is_active else None, ['toggle_off', 'toggle_on'], 'Project')
                        ui.label(project.name).classes('text-subtitle1 font-bold q-ml-sm')
                        ui.space()
                        if project.tags:
                            for tag in project.tags[:4]:
                                ui.chip(tag).props('dense color=primary text-color=white')
                            if len(project.tags) > 4:
                                ui.chip(f'+{len(project.tags) - 4}').props('dense color=grey text-color=white')
                    # Row 1-: description, created_at
                    if project.description:
                        ui.label(project.description).classes('text-body2 q-mt-xs')
                    ui.label(f'Created: {render_datetime(project.created_at)}').classes('text-caption text-italic text-grey-7 q-mt-xs')
            card.on('click', lambda e, p=project.name: ui.navigate.to(project_url(p)))

        ui.button('New Project', icon='add').props('color=primary').on_click(_new_project).classes('w-full')

# ***************************************************************************

async def project_subpage(args: PageArguments, nav: ui.element, project_id: str, tab: Optional[str] = None):
    try:
        get_project(project_id, check_active=False)
    except (ValueError, NotFoundError):
        ui.label(f'Project "{project_id}" does not exist.').classes('text-h6 text-negative')
        return

    refresh_breadcrumbs(nav, project_id=project_id)

    extension_tab_defs = await anyio.to_thread.run_sync(lambda: get_project_tabs(project_id))
    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        general_tab = ui.tab('General')
        files_tab = ui.tab('Files')
        devices_tab = ui.tab('Devices')
        extension_tabs = [(ui.tab(label), render_fn) for label, render_fn in extension_tab_defs]
    tab = tab if tab else dashboard_tab.label
    tabs.on_value_change(lambda e: ui.navigate.history.replace(project_url(project_id, tab=cast(str, e.value))))
    with ui.tab_panels(tabs, value=tab).classes('w-full'):
        with ui.tab_panel(dashboard_tab):
            await project_dashboard_panel(project_id)
        with ui.tab_panel(general_tab):
            await project_general_panel(project_id)
        with ui.tab_panel(files_tab):
            await project_files_panel(project_id)
        with ui.tab_panel(devices_tab):
            await project_devices_panel(project_id)
        for extension_tab, render_fn in extension_tabs:
            with ui.tab_panel(extension_tab):
                await maybe_await(render_fn(project_id))

# ***************************************************************************

async def project_dashboard_panel(project_id: str) -> None:
    """Overview cards shown on the project Dashboard tab (auto-refreshes every 10 s)."""

    @ui.refreshable
    async def _content() -> None:
        from app.mqtt.backend import connection_status as mqtt_connection_status
        project = get_project(project_id, check_active=False)
        devices = get_devices(project_id)
        active = [d for d in devices if d.is_active]
        pending_approval = [d for d in active if not d.is_provisioning_approved]
        online = [d for d in active if is_device_online(d, project.device_online_threshold_s)]
        seen = sorted([d for d in devices if d.last_seen_at], key=lambda d: d.last_seen_at, reverse=True)

        with ui.grid().classes('grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full'):
            # Overview card
            with ui.card().tight().classes('w-full'):
                with ui.card_section().props('dense').classes('w-full'):
                    # Row 0 (header): card name — icons for project active, HTTP enabled, MQTT enabled/connected
                    with ui.row().classes('w-full gap-1 items-center'):
                        ui.label('Project status').classes('text-subtitle1 font-bold')
                        ui.space()
                        # status icons (icon-only, tooltip carries the label)
                        status_avatar(True if project.is_active else None, ['toggle_off', 'toggle_on'], 'Project')
                        status_avatar(True if project.is_http_enabled else None, 'language', 'HTTP')
                        status_avatar(mqtt_connection_status == 'connected' if project.is_mqtt_enabled else None, 'hub', ['MQTT connected', 'MQTT disabled', 'MQTT disconnected'])
                    ui.separator().classes('q-mt-xs q-mb-xs')

                    # Row 1: project name, tags
                    with ui.row().classes('w-full gap-0 q-mt-sm items-center'):
                        ui.label(project.name).classes('text-subtitle1 font-bold')
                        ui.space()
                        if project.tags:
                            for tag in project.tags[:4]:
                                ui.chip(tag).props('dense color=primary text-color=white')
                            if len(project.tags) > 4:
                                ui.chip(f'+{len(project.tags) - 4}').props('dense color=grey text-color=white')

                    # Row 2-: description
                    if project.description:
                        ui.label(project.description).classes('text-body2 q-mt-xs')
                    # ui.label(f'Created: {render_datetime(project.created_at)}').classes('text-caption text-italic text-grey-7 q-mt-xs')

            # Device health card
            with ui.card().tight().classes('w-full'):
                with ui.card_section().props('dense').classes('w-full'):
                    ui.label('Device Health').classes('text-subtitle1 font-bold')
                    ui.separator().classes('q-mt-xs q-mb-xs')
                    with ui.grid().classes('grid-cols-4 text-center q-mt-sm'):
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
                            ui.label('Pending').classes(f'text-caption {warn_color}')

            # System health card
            await _system_project_health_card(project_id)

            # Recent activity card
            if seen:
                with ui.card().tight().classes('w-full'):
                    with ui.card_section().props('dense').classes('w-full'):
                        ui.label('Recent Activity').classes('text-subtitle1 font-bold')
                        ui.separator().classes('q-mt-xs q-mb-xs')
                        for d in seen[:8]:
                            dot_color = 'text-green' if is_device_online(d, project.device_online_threshold_s) else 'text-grey'
                            with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
                                ui.icon('fiber_manual_record').classes(f'text-sm {dot_color}')
                                ui.label(d.name).classes('grow text-body2 cursor-pointer') \
                                    .on('click', lambda _, dn=d.name: ui.navigate.to(device_url(project_id, dn)))
                                ui.label(render_datetime(d.last_seen_at)).classes('text-caption text-grey-7')

            # Extension cards
            for render_fn in await anyio.to_thread.run_sync(lambda: get_project_dashboard_cards(project_id)):
                await maybe_await(render_fn(project_id))

    await _content()
    ui.timer(10.0, _content.refresh)
    await dashboard_alarms_card(project_id)


# ***************************************************************************

async def project_general_panel(project_id: str):
    with ui.grid().classes('w-full gap-4 grid-cols-1 lg:grid-cols-2'):
        with config_expansion('General'):
            await project_card(project_id)
        with config_expansion('Provisioning'):
            await ProvisioningCard(project_id)
        with config_expansion('Forwarding'):
            ForwardingCard(project_id)
        with config_expansion('Telemetry'):
            TelemetryCard(project_id)
        with config_expansion('Logging'):
            LoggingCard(project_id)
        with config_expansion('Files'):
            await file_config_card(project_id)
        with config_expansion('Firmware'):
            await firmware_source_card(project_dir(project_id),
                                       project_name=project_id, device_name=None)
        with config_expansion('Alarms'):
            await alarm_config_card(project_id)
        with config_expansion('Extensions'):
            await extensions_card(project_id)
        for title, render_fn in await anyio.to_thread.run_sync(lambda: get_project_general_cards(project_id)):
            with config_expansion(title):
                await maybe_await(render_fn(project_id))
        with config_expansion('Danger Zone'):
            await danger_card(project_id)

# ***************************************************************************

async def project_card(project_id: str) -> None:
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
    with ui.row().classes('w-full gap-3 q-mt-none'):
        form.render_field('is_active')
        form.render_field('is_autocreate_devices')
        form.render_field('is_provisioning_autoapproval')
    with ui.row().classes('w-full gap-3 q-mt-none'):
        form.render_field('is_http_enabled')
        form.render_field('is_mqtt_enabled')
    with ui.row().classes('items-center gap-1') as mqtt_warning:
        ui.icon('warning').classes('text-warning text-sm')
        ui.label('Global MQTT broker disabled (set MQTT_ENABLED)') \
            .classes('text-caption text-warning')
    mqtt_warning.bind_visibility_from(
        form, 'item',
        backward=lambda item: cast(Project, item).is_mqtt_enabled and not app_config.mqtt_enabled
    )

    form.render_field('mqtt_topic_base').props('outlined dense').classes('w-full')
    form.render_field('device_tokens_expire_in').props('outlined dense').classes('w-full')
    form.render_field('device_token_length').props('outlined dense').classes('w-full')
    form.render_field('device_online_threshold_s').props('outlined dense').classes('w-full')

    def _created_updated_caption(item: Project) -> str:
        return f'Created {render_datetime(item.created_at)}, updated {render_datetime(item.updated_at)}'
    ui.label().classes('text-caption text-grey-7').bind_text_from(
        form, 'item', backward=lambda item: _created_updated_caption(cast(Project, item))
    )

# ***************************************************************************

async def extensions_card(project_id: str) -> None:
    """Content for the Extensions toggle card (caller provides the card/header)."""
    names = get_registered_extension_names()
    if not names:
        ui.label('No extensions installed.').classes('text-caption text-grey-7')
        return

    adapter = project_adapter(project_id)
    changed = {'value': False}  # mutable flag: has anything been toggled this session?

    @ui.refreshable
    def _list() -> None:
        enabled = set(adapter.read().enabled_extensions)
        for name in names:
            async def _toggle(_, name=name) -> None:
                project = adapter.read()
                if name in project.enabled_extensions:
                    project.enabled_extensions.remove(name)
                else:
                    project.enabled_extensions.append(name)
                adapter.save(project)
                changed['value'] = True
                _list.refresh()

            ui.switch(name, value=name in enabled, on_change=_toggle)

        if changed['value']:
            with ui.row().classes('items-center gap-2 q-mt-sm'):
                ui.icon('info').classes('text-warning')
                ui.label('Extension tabs only update after a page reload.') \
                    .classes('text-caption text-warning')
                ui.button('Reload page', icon='refresh', on_click=ui.navigate.reload) \
                    .props('dense flat color=warning')

    _list()

# ***************************************************************************

async def _rename_project(old_name: str, new_name: str) -> None:
    if not is_valid_name(new_name):
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
    with ui.row().classes('w-full gap-4 q-mt-none q-mb-none'):
        val_rules = {
            "Invalid name: letters, digits, underscore only; must not start with a digit.": lambda x: is_valid_name(x)
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

async def ProvisioningCard(project_id: str):
    ui.markdown('Long-lived shared secrets used by devices to obtain bearer tokens.').classes('text-caption q-ma-none')
    TokenListCard(get_provisioning_token_adapter(project_id),
                    token_length=app_config.provisioning_token_length,
                    expires_in=app_config.provisioning_token_expires_in)

# ***************************************************************************

async def project_devices_panel(project_id: str):
    with ui.expansion('Devices', value=True).classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
        ui.markdown("""
                _Devices_ are physical IoT nodes that connect to this project.
                Each device has its own directory and can be provisioned with a
                short-lived bearer token.

                Double-click a device to edit its settings. Use the "New" button to create a new device.
                """).classes('text-caption q-ma-none')
        ProjectDevicesTable(project_id)


# ***************************************************************************

async def _system_project_health_card(project_id: str) -> None:
    """Read-only card showing last known health of external backends."""
    from app.health import get_project_health
    import app.mqtt.backend as _mqtt_backend

    health = get_project_health(project_id)
    mqtt_status = _mqtt_backend.connection_status

    with ui.card().tight().classes('w-full'):
        with ui.card_section().props('dense').classes('w-full'):
            ui.label('System & Project Health').classes('text-subtitle1 font-bold')
            ui.separator().classes('q-mt-xs q-mb-xs')
            with ui.column().classes('gap-1 q-mt-sm w-full'):
                # MQTT — 'connected' is healthy; 'disabled' is a neutral off state
                # (grey, like a backend with no data yet), not a failure; anything
                # else ('disconnected', 'error: ...') is a real failure (red).
                if mqtt_status == 'connected':
                    mqtt_ok: bool | None = True
                elif mqtt_status == 'disabled':
                    mqtt_ok = None
                else:
                    mqtt_ok = False
                _health_row('MQTT', mqtt_ok, '' if mqtt_ok is True else mqtt_status)

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

                # Firmware pulls (aggregated across project + all devices) —
                # only shown once a repo is configured somewhere in the project.
                from app.core.firmware.backend import project_has_firmware_source
                firmware_configured = await anyio.to_thread.run_sync(
                    lambda: project_has_firmware_source(project_id)
                )
                if firmware_configured:
                    fw = health.get(f'{project_id}:firmware')
                    if fw is not None:
                        _health_row('Firmware', fw['ok'], fw['message'] if not fw['ok'] else '')
                    else:
                        _health_row('Firmware', None, 'No data received yet')

                # Forwarding rules — one row per rule that has been used at least once
                prefix = f'{project_id}:forwarding:'
                for key in sorted(k for k in health if k.startswith(prefix)):
                    fwd_name = key[len(prefix):]
                    fwd_h = health[key]
                    _health_row(f'Forwarding: {fwd_name}', fwd_h['ok'], fwd_h['message'] if not fwd_h['ok'] else '')


def _health_row(label: str, ok: bool | None, detail: str) -> None:
    with ui.row().classes('items-center gap-2 w-full'):
        status_avatar(ok, ['help', 'check_circle', 'error'], label)
        ui.label(label).classes('text-body2 font-bold min-w-24 shrink-0')
        if detail:
            ui.label(detail).classes('text-caption text-grey-7 grow').style(
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
            )
        else:
            ui.space()


