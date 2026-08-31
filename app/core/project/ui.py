import datetime
import re
from typing import Sequence, cast

import anyio
from nicegui import context, PageArguments, ui

from app.config import app_config
from app.core.token.backend import get_provisioning_token_adapter
from app.core.token.ui import TokenListCard
from app.core.device.backend import get_devices, is_device_online
from app.core.device.ui import ProjectDevicesTable, prompt_create_device
from app.core.logging.ui import LoggingCard
from app.core.telemetry.ui import TelemetryCard
from app.core.forwarding.ui import ForwardingCard
from app.core.file.browser_ui import project_files_panel
from app.core.firmware.ui import firmware_source_card
from app.core.seed.action_dialogs import ap_qr_dialog, web_serial_flash_dialog
from app.core.seed.ui import seed_settings_card
from app.paths import project_dir
from app.core.file.ui import file_config_card
from app.routes import device_url, project_url, projects_url
from app.ui import NavItem, config_expansion, hide_sidebar, refresh_breadcrumbs, render_sidebar, show_sidebar, status_avatar
from app.util import is_valid_name, render_datetime
from app.core.project.models import Project
from app.core.project.backend import create_project, delete_project, get_project, get_projects, project_adapter, rename_project
from app.core.alarm.ui import alarm_config_card, dashboard_alarms_card
from app.exceptions import NotFoundError
from app.extensions import (
    call_with_page_args, get_project_dashboard_cards, get_project_settings_cards,
    get_project_tabs, get_registered_extension_names, maybe_await,
)
from niceview import ModelForm
from niceview.util import confirm_dialog, input_dialog

import logging
log = logging.getLogger("uvicorn")


# ***************************************************************************

async def all_projects_subpage(args: PageArguments, nav: ui.element, sidebar: ui.element,
                               drawer: ui.left_drawer, hamburger: ui.element):
    log.debug(f'project_main_page {args=}')
    refresh_breadcrumbs(nav)
    hide_sidebar(drawer, hamburger, sidebar)

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
        ui.navigate.to(project_url(project.name, tab='general'))

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

        ui.button('New Project', icon='add').on_click(_new_project).classes('w-full')

# ***************************************************************************

def slugify_tab_label(label: str) -> str:
    """URL-safe path segment for an extension-registered tab's sidebar route,
    e.g. 'E-Paper' -> 'e-paper'. See app.routes.project_url()'s tab= param."""
    return re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-') or 'tab'


def project_nav_items(project_id: str, extension_tab_defs: Sequence[tuple[str, str, str, object]],
                      settings_card_defs: Sequence[tuple[str, object]] = ()) -> list[NavItem]:
    """The project sidebar's rows — a 'Project' group (Dashboard/Files/Devices),
    one group per enabled extension (its project tabs, in registration order),
    and a trailing 'Settings' group (the old General tab's sections, plus any
    extension-registered 'settings' cards, each its own child page — see
    SETTINGS_SECTIONS). Shared with device_subpage, which shows the same
    sidebar (with 'Devices' as the active row) while drilled into a device,
    rather than growing a third sidebar level of its own — see
    find_nav_item() for locating a row nested under one of these groups."""
    settings_children = [
        NavItem(label, icon, project_url(project_id, tab=f'settings/{slug}'))
        for slug, label, icon in SETTINGS_SECTIONS
    ] + [
        NavItem(title, 'extension', project_url(project_id, tab=f'settings/tab/{slugify_tab_label(title)}'))
        for title, _fn in settings_card_defs
    ]
    extension_groups: dict[str, list[NavItem]] = {}
    for extension_name, label, icon, _fn in extension_tab_defs:
        extension_groups.setdefault(extension_name, []).append(
            NavItem(label, icon, project_url(project_id, tab=f'tab/{slugify_tab_label(label)}'))
        )
    return [
        NavItem('Project', 'dashboard', children=(
            NavItem('Dashboard', 'dashboard', project_url(project_id)),
            NavItem('Files', 'folder', project_url(project_id, tab='files')),
            NavItem('Devices', 'devices', project_url(project_id, tab='devices')),
        )),
        *(NavItem(extension_name, 'extension', children=tuple(items))
          for extension_name, items in extension_groups.items()),
        NavItem('Settings', 'settings', children=tuple(settings_children)),
    ]


def find_nav_item(items: list[NavItem], label: str) -> NavItem:
    """Locate a row by label anywhere in items — top-level or nested one level
    under a group (see project_nav_items(), NavItem: "only one level of
    nesting is supported"). Raises StopIteration if not found, same as a bare
    next(...) would."""
    return next(item for parent in items for item in (parent.children or (parent,)) if item.label == label)


async def project_subpage(args: PageArguments, nav: ui.element, sidebar: ui.element,
                          drawer: ui.left_drawer, hamburger: ui.element, project_id: str) -> None:
    try:
        get_project(project_id, check_active=False)
    except (ValueError, NotFoundError):
        hide_sidebar(drawer, hamburger, sidebar)
        ui.label(f'Project "{project_id}" does not exist.').classes('text-h6 text-negative')
        return

    refresh_breadcrumbs(nav, project_id=project_id)

    extension_tab_defs = await anyio.to_thread.run_sync(lambda: get_project_tabs(project_id))
    settings_card_defs = await anyio.to_thread.run_sync(lambda: get_project_settings_cards(project_id))
    nav_items = project_nav_items(project_id, extension_tab_defs, settings_card_defs)
    show_sidebar(drawer, hamburger, sidebar, project_id, nav_items)
    # Clicking a sidebar row navigates within this same project_subpage render
    # (the nested ui.sub_pages below swaps content in place) — project_subpage
    # itself doesn't re-run, so the active row has to be recomputed on every
    # such navigation rather than just once here (see app.ui.render_sidebar).
    context.client.sub_pages_router.on_path_changed(lambda _: render_sidebar(sidebar, project_id, nav_items))

    async def _dashboard_route() -> None:
        await project_dashboard_panel(project_id, args)

    async def _files_route() -> None:
        await project_files_panel(project_id)

    async def _devices_route() -> None:
        await project_devices_panel(project_id)

    def _tab_route(render_fn):
        """A whole extension tab: it builds its own complete UI (see
        register_project_tab), no chrome of nice4iot's own around it."""
        async def _route() -> None:
            await maybe_await(call_with_page_args(render_fn, args, project_id))
        return _route

    def _settings_card_route(title, render_fn):
        """An extension 'settings' card: fields only (see register_project_card),
        nice4iot supplies the same config_expansion chrome the old General tab
        gave it."""
        async def _route() -> None:
            with config_expansion(title, value=True):
                await maybe_await(call_with_page_args(render_fn, args, project_id))
        return _route

    routes: dict = {'/': _dashboard_route, '/files': _files_route, '/devices': _devices_route}
    for _ext, label, _icon, render_fn in extension_tab_defs:
        routes[f'/tab/{slugify_tab_label(label)}'] = _tab_route(render_fn)

    settings_renderers = _settings_section_renderers(project_id)
    for slug, _label, _icon in SETTINGS_SECTIONS:
        routes[f'/settings/{slug}'] = settings_renderers[slug]
    for title, render_fn in settings_card_defs:
        routes[f'/settings/tab/{slugify_tab_label(title)}'] = _settings_card_route(title, render_fn)

    with ui.column().classes('w-full'):
        # ui.sub_pages is itself a flex column with align-items:flex-start (like
        # ui.row/ui.column), so it shrink-wraps to its content's width unless
        # given w-full explicitly — every route rendered through it (Dashboard,
        # General, Files, Devices, every extension tab) inherited that missing
        # width without this.
        ui.sub_pages(routes).classes('w-full')

# ***************************************************************************

async def project_dashboard_panel(project_id: str, args: PageArguments) -> None:
    """Overview cards shown on the project Dashboard tab (auto-refreshes every 10 s)."""

    @ui.refreshable
    async def _content() -> None:
        from app.mqtt.backend import connection_status as mqtt_connection_status
        from app.core.alarm.backend import get_device_offline_threshold
        project = get_project(project_id, check_active=False)
        devices = get_devices(project_id)
        threshold = await anyio.to_thread.run_sync(lambda: get_device_offline_threshold(project_id))
        active = [d for d in devices if d.is_active]
        pending_approval = [d for d in active if not d.is_provisioning_approved]
        online = [d for d in active if is_device_online(d, threshold)]
        seen = sorted([d for d in devices if d.last_seen_at],
                     key=lambda d: cast(datetime.datetime, d.last_seen_at), reverse=True)

        with ui.grid().classes('grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full'):
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
                            dot_color = 'text-green' if is_device_online(d, threshold) else 'text-grey'
                            with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
                                ui.icon('fiber_manual_record').classes(f'text-sm {dot_color}')
                                ui.label(d.name).classes('grow text-body2 cursor-pointer') \
                                    .on('click', lambda _, dn=d.name: ui.navigate.to(device_url(project_id, dn)))
                                ui.label(render_datetime(d.last_seen_at)).classes('text-caption text-grey-7')

            # Extension cards
            for render_fn in await anyio.to_thread.run_sync(lambda: get_project_dashboard_cards(project_id)):
                await maybe_await(call_with_page_args(render_fn, args, project_id))

    await _content()
    ui.timer(10.0, _content.refresh)
    await dashboard_alarms_card(project_id)


# ***************************************************************************

# (slug, label, icon) for each of the "Settings" sidebar group's built-in
# children, in sidebar order. A child's page may stack more than one of the
# old General-tab expansions (all expanded by default, since there's only
# ever one or a few per page now, unlike the old single crowded General tab)
# — see _settings_section_renderers().
SETTINGS_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ('general', 'General', 'info'),
    ('provisioning', 'Provisioning', 'verified_user'),
    ('forwarding', 'Forwarding', 'call_split'),
    ('telemetry', 'Telemetry', 'insights'),
    ('firmware', 'Firmware', 'memory'),
    ('alarms', 'Alarms', 'notifications'),
)


def _settings_section_renderers(project_id: str) -> dict[str, object]:
    """One render_fn per Settings child (see SETTINGS_SECTIONS) — each wraps
    its card(s) in the same config_expansion chrome the old General tab used,
    now always expanded (value=True): there are at most a few per page,
    unlike the old single crowded General tab, so folding them away by
    default would just hide content the user came here to see."""
    async def _general() -> None:
        with config_expansion('General', value=True):
            await project_card(project_id)
        with config_expansion('Files', value=True):
            await file_config_card(project_id)
        with config_expansion('Extensions', value=True):
            await extensions_card(project_id)
        with config_expansion('Danger Zone', value=True):
            await danger_card(project_id)

    async def _provisioning() -> None:
        with config_expansion('Provisioning', value=True):
            await ProvisioningCard(project_id)

    async def _forwarding() -> None:
        with config_expansion('Forwarding', value=True):
            ForwardingCard(project_id)

    async def _telemetry() -> None:
        with config_expansion('Telemetry', value=True):
            TelemetryCard(project_id)
        with config_expansion('Logging', value=True):
            LoggingCard(project_id)

    async def _firmware() -> None:
        with config_expansion('Firmware Seed', value=True):
            await seed_settings_card(project_dir(project_id))
        with config_expansion('Firmware Download', value=True):
            await firmware_source_card(project_dir(project_id),
                                       project_name=project_id, device_name=None)

    async def _alarms() -> None:
        with config_expansion('Alarms', value=True):
            await alarm_config_card(project_id)

    return {
        'general': _general, 'provisioning': _provisioning, 'forwarding': _forwarding,
        'telemetry': _telemetry, 'firmware': _firmware, 'alarms': _alarms,
    }

# ***************************************************************************

async def project_card(project_id: str) -> None:
    form = ModelForm.from_adapter(Project, project_adapter(project_id),
            autosave=True,
            layout=[
                ['is_active:shrink', 'name'], 
                'description', 'tags',
                ['is_autocreate_devices', 'is_provisioning_autoapproval'],
                ['is_http_enabled', 'is_mqtt_enabled'],
                'mqtt_topic_base',
                ['device_tokens_expire_in', 'device_token_length'],
            ])
    form.render()
    with ui.row().classes('items-center gap-1') as mqtt_warning:
        ui.icon('warning').classes('text-warning text-sm')
        ui.label('Global MQTT broker disabled (set MQTT_ENABLED)') \
            .classes('text-caption text-warning')
    mqtt_warning.bind_visibility_from(
        form, 'item',
        backward=lambda item: cast(Project, item).is_mqtt_enabled and not app_config.mqtt_enabled
    )

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
                ui.button('Reload page', icon='refresh', on_click=ui.navigate.reload)

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
        f'Renaming **{old_name}** changes the API path of every device in it. '
        'They all stop reaching the server until each one is reconfigured with the new name.',
        ok_label='Rename',
        ok_role='delete',
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
        ok_role='delete',
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
        # Negative on purpose, and not to be normalised away: a rename is destructive
        # for deployed devices. Their configured API paths carry the project name, so
        # renaming breaks every client in the field until it is reconfigured.
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

                Click a device to edit its settings. Use the "New" button to
                add a device record only (it gets seeded some other way).
                "Flash Device" and "AP + Form Setup" below create a device record
                *and* immediately seed it — via a USB-serial flash, or a
                printable QR code for the device's own setup portal.
                """).classes('text-caption q-ma-none')

        @ui.refreshable
        async def devices_table() -> None:
            from app.core.device.backend import project_device_rows
            rows = await anyio.to_thread.run_sync(lambda: project_device_rows(project_id))
            ProjectDevicesTable(project_id, rows)

        async def _flash_new_device() -> None:
            name = await prompt_create_device(project_id)
            devices_table.refresh()
            if name is not None:
                web_serial_flash_dialog(project_id, name).open()

        async def _ap_qr_new_device() -> None:
            name = await prompt_create_device(project_id)
            devices_table.refresh()
            if name is not None:
                ap_qr_dialog(project_id, name).open()

        with ui.row().classes('gap-2 q-mb-sm'):
            ui.button('Flash Device', icon='usb', on_click=_flash_new_device).props('outline')
            ui.button('AP + Form Setup', icon='qr_code', on_click=_ap_qr_new_device).props('outline')

        await devices_table()


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
                # MQTT — 'connected' is healthy; 'disabled' is a neutral off state / don't show;
                # 'disconnected' and 'error: ...' are real failures (red).
                if mqtt_status != 'disabled':
                    _health_row('MQTT', mqtt_status == 'connected', '' if mqtt_status == 'connected' else mqtt_status)

                # Telemetry backend
                from app.core.telemetry.backend import get_telemetry_adapter
                tel_cfg = await anyio.to_thread.run_sync(lambda: get_telemetry_adapter(project_id).read())
                if tel_cfg.backend == 'none':
                    _health_row('Telemetry', None, 'Disabled')
                else:
                    tel = health.get(f'{project_id}:telemetry')
                    if tel is not None:
                        _health_row('Telemetry', tel['ok'], tel['message'] if not tel['ok'] else '')
                    else:
                        _health_row('Telemetry', None, 'No data received yet')

                # Logging backend
                from app.core.logging.backend import get_logging_adapter
                log_cfg = await anyio.to_thread.run_sync(lambda: get_logging_adapter(project_id).read())
                if not (log_cfg.file.is_active or log_cfg.loki.is_active):
                    _health_row('Logging', None, 'Disabled')
                else:
                    log_h = health.get(f'{project_id}:logging')
                    if log_h is not None:
                        _health_row('Logging', log_h['ok'], log_h['message'] if not log_h['ok'] else '')
                    else:
                        _health_row('Logging', None, 'No data received yet')

                # Firmware pulls (aggregated across project + all devices) —
                # only shown once a repo is configured somewhere in the project.
                from app.core.firmware.backend import project_has_firmware_source, project_has_auto_pull_enabled
                firmware_configured = await anyio.to_thread.run_sync(
                    lambda: project_has_firmware_source(project_id)
                )
                if firmware_configured:
                    auto_pull = await anyio.to_thread.run_sync(
                        lambda: project_has_auto_pull_enabled(project_id)
                    )
                    fw = health.get(f'{project_id}:firmware')
                    if fw is not None:
                        _health_row('Firmware', fw['ok'], fw['message'] if not fw['ok'] else '')
                    elif auto_pull:
                        _health_row('Firmware', None, 'No data received yet')
                    else:
                        _health_row('Firmware', None, 'Auto-pull disabled')

                # Forwarding rules — one row per configured rule
                from app.core.forwarding.backend import get_forwarding_adapter
                fwd_rules = await anyio.to_thread.run_sync(lambda: list(get_forwarding_adapter(project_id)))
                for fwd in fwd_rules:
                    fwd_h = health.get(f'{project_id}:forwarding:{fwd.name}')
                    if fwd_h is not None:
                        _health_row(f'Forwarding: {fwd.name}', fwd_h['ok'], fwd_h['message'] if not fwd_h['ok'] else '')
                    else:
                        _health_row(f'Forwarding: {fwd.name}', None, 'No data received yet')


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


