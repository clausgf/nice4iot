import asyncio
import re

import anyio
from nicegui import context, PageArguments, ui
from fastapi.responses import RedirectResponse

from app.core.project.ui import all_projects_subpage, preferences_subpage, project_subpage
from app.core.device.ui import device_subpage
from app.routes import (
    about_url, login_url, preferences_url, project_url, projects_url,
    UI_PREFIX, ROUTE_ABOUT, ROUTE_DEVICE, ROUTE_PREFERENCES, ROUTE_PROJECT, ROUTE_PROJECTS,
)
from app.auth import get_auth_provider, PasswordAuthProvider
from app.util import app_version

import logging
log = logging.getLogger('uvicorn')


# ---------------------------------------------------------------------------

_logo = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="32" height="32">
  <g fill="none" stroke="white" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="32" cy="32" r="15.37"/>
    <ellipse cx="32" cy="32" rx="15.37" ry="5.13"/>
    <ellipse cx="32" cy="32" rx="15.37" ry="10.26"/>
    <ellipse cx="32" cy="32" rx="5.13" ry="15.37"/>
    <ellipse cx="32" cy="32" rx="10.26" ry="15.37"/>
    <line x1="47.37" y1="32" x2="53.33" y2="32"/>
    <line x1="41.03" y1="17.33" x2="43.59" y2="12.11"/>
    <line x1="22.97" y1="17.33" x2="20.41" y2="12.11"/>
    <line x1="16.63" y1="32" x2="10.67" y2="32"/>
    <line x1="22.97" y1="46.67" x2="20.41" y2="51.89"/>
    <line x1="41.03" y1="46.67" x2="43.59" y2="51.89"/>
    <circle cx="53.33" cy="32" r="1.92"/>
    <circle cx="43.59" cy="12.11" r="1.92"/>
    <circle cx="20.41" cy="12.11" r="1.92"/>
    <circle cx="10.67" cy="32" r="1.92"/>
    <circle cx="20.41" cy="51.89" r="1.92"/>
    <circle cx="43.59" cy="51.89" r="1.92"/>
  </g>
</svg>'''


def login_redirect():
    """
    Server-side redirect to the login page for unauthenticated users, or
    None if the page may be shown. Nice4iot routes almost everything
    through the single home_page() catch-all below, so this is checked
    there once rather than on every individual page.
    """
    provider = get_auth_provider()
    request = context.client.request
    if provider.login_required and provider.get_user(request) is None:
        root_path = request.scope.get('root_path', '') if request else ''
        return RedirectResponse(f"{root_path}{login_url()}")
    return None


def _user_menu() -> None:
    provider = get_auth_provider()
    username = provider.get_user(context.client.request)

    # One dark-mode element for this page; both menu items drive the same
    # instance. Creating a fresh ui.dark_mode() per click (as before) left
    # conflicting elements behind, so switching back to light needed a refresh.
    dark = ui.dark_mode()

    with ui.button(username or '', icon='person').props('flat color=white'):
        with ui.menu():
            if provider.login_required:
                if not username:
                    ui.menu_item('Not signed in').props('disable')
                if provider.logout_url():
                    def do_logout():
                        provider.logout()
                        ui.navigate.to(provider.logout_url() or projects_url())
                    with ui.menu_item(on_click=do_logout).classes('items-center gap-x-2'):
                        ui.icon('logout').props('size=large')
                        ui.label('Logout')
                ui.separator()
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('settings').props('size=large')
                ui.link('Preferences', preferences_url()).classes('no-underline text-inherit')
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('light_mode').props('size=large')
                ui.label('Light Mode').on('click', dark.disable)
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('dark_mode').props('size=large')
                ui.label('Dark Mode').on('click', dark.enable)
            ui.separator()
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('api').props('size=large')
                ui.link('API Docs', '/docs', new_tab=True).classes('no-underline text-inherit')
            # The repository link is also what AGPL-3.0 section 13 asks for:
            # users interacting with this application over a network must be
            # able to get its source.
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('code').props('size=large')
                ui.link('Repository', 'https://github.com/clausgf/nice4iot', new_tab=True).classes('no-underline text-inherit')
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('info').props('size=large')
                ui.link('About', about_url()).classes('no-underline text-inherit')
            ui.separator()
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.label(f'nice4iot {app_version()} · AGPL-3.0').classes('text-xs opacity-60')


@ui.page('/ui/login')
def page_login():
    provider = get_auth_provider()
    if not isinstance(provider, PasswordAuthProvider) or provider.get_user():
        request = context.client.request
        root_path = request.scope.get('root_path', '') if request else ''
        return RedirectResponse(f"{root_path}{projects_url()}")

    with ui.card().classes('absolute-center items-stretch'):
        ui.label('4IoT').classes('text-h6')
        username = ui.input('Username').props('autofocus')
        password = ui.input('Password', password=True, password_toggle_button=True)

        async def try_login():
            # bcrypt verification is CPU bound, keep it off the event loop
            if await asyncio.to_thread(provider.verify, username.value, password.value):
                provider.login(username.value)
                ui.navigate.to(projects_url())
            else:
                ui.notify('Wrong username or password', type='negative')

        username.on('keydown.enter', try_login)
        password.on('keydown.enter', try_login)
        ui.button('Log in', on_click=try_login).classes('w-full')


async def about_subpage(args: PageArguments, nav: ui.element):
    """About / Software Bill of Materials, as a client-side sub-page so it routes
    through ui.sub_pages like the rest of the app (a standalone @ui.page is not
    reachable — the sub_pages router intercepts internal navigation first).

    nice4iot's own version and build revision come first, then the key
    components, then every installed package.
    """
    nav.clear()
    with nav:
        ui.label('/').classes('text-h6 text-white opacity-50')
        ui.label('About').classes('text-h6 font-bold text-white')

    from app.sbom import app_revision, collect_sbom, package_version
    packages = await anyio.to_thread.run_sync(collect_sbom)
    revision = await anyio.to_thread.run_sync(app_revision)
    niceview_v = await anyio.to_thread.run_sync(lambda: package_version('niceview'))
    nicepaper_v = await anyio.to_thread.run_sync(lambda: package_version('nicepaper'))

    # Own version first (with the build commit when known), then key components.
    own_version = app_version() + (f' · {revision}' if revision else '')
    highlights = [
        ('nice4iot', own_version),
        ('niceview', niceview_v),
        ('E-Paper (nicepaper)', nicepaper_v),
    ]

    with ui.column().classes('w-full max-w-3xl mx-auto p-4 gap-4'):
        ui.label('About').classes('text-h5')
        ui.label('AGPL-3.0 · Software Bill of Materials').classes('text-subtitle2 text-grey')

        with ui.row().classes('w-full gap-4'):
            for title, ver in highlights:
                with ui.card().classes('grow'):
                    ui.label(title).classes('text-subtitle1 font-bold')
                    ui.label(ver or 'not installed').classes(
                        'text-body2' + ('' if ver else ' text-grey italic'))

        ui.separator()
        ui.label(f'All installed packages ({len(packages)})').classes('text-subtitle1 font-bold')
        table = ui.table(
            columns=[
                {'name': 'name', 'label': 'Package', 'field': 'name', 'align': 'left', 'sortable': True},
                {'name': 'version', 'label': 'Version', 'field': 'version', 'align': 'left', 'sortable': True},
            ],
            rows=[{'name': name, 'version': ver} for name, ver in packages],
            row_key='name',
        ).classes('w-full').props('dense flat bordered')
        with table.add_slot('top-left'):
            ui.input(placeholder='Filter').props('dense clearable borderless') \
                .bind_value_to(table, 'filter')


_EXTENSION_PAGE_PATTERN = re.compile(
    r'^/ui/project/(?P<project_id>[^/]+)/ext/(?P<extension_name>[^/]+)/?$')


@ui.page('/ui')
@ui.page('/ui/{_:path}')
async def home_page():
    if (redirect := login_redirect()):
        return redirect

    # Standalone extension pages (docs/extensions.md) get full control of
    # the page — no header/navigation below. Matched here rather than as
    # a separate @ui.page(...) per extension: NiceGUI/Starlette routes
    # are matched in registration order, and this catch-all is already
    # registered by the time extensions register themselves at startup,
    # so a separate route would silently never be reached.
    request = context.client.request
    path = request.url.path if request else ''
    if (m := _EXTENSION_PAGE_PATTERN.match(path)):
        from app.extensions import get_project_page, is_extension_enabled, maybe_await
        project_id, extension_name = m.group('project_id'), m.group('extension_name')
        render_fn = get_project_page(extension_name)
        if render_fn is not None:
            enabled = await anyio.to_thread.run_sync(
                lambda: is_extension_enabled(project_id, extension_name))
            if not enabled:
                return RedirectResponse(project_url(project_id))
            await maybe_await(render_fn(project_id))
            return

    with ui.header(elevated=True).classes('items-center gap-3'):
        ui.html(_logo).props('width=16 height=16').classes('text-white cursor-pointer shrink-0') \
            .on('click', lambda: ui.navigate.to(projects_url()))
        ui.label('4IoT').classes('text-h6 font-bold cursor-pointer shrink-0') \
            .on('click', lambda: ui.navigate.to(projects_url()))
        # Sub-pages populate this row with clickable path segments (e.g. project / device).
        nav = ui.row().classes('items-center gap-1')
        ui.space()
        _user_menu()

    with ui.column().classes('w-full'):
        # root_path=UI_PREFIX strips the /ui prefix before matching, so the route
        # keys stay relative. The literal 'project' segment keeps project names
        # from ever colliding with /about or /preferences.
        ui.sub_pages(
            {
                ROUTE_PROJECTS:    all_projects_subpage,
                ROUTE_ABOUT:       about_subpage,
                ROUTE_PREFERENCES: preferences_subpage,
                ROUTE_PROJECT:     project_subpage,
                ROUTE_DEVICE:      device_subpage,
            },
            data={'nav': nav},
            root_path=UI_PREFIX,
        ).classes('w-full')
