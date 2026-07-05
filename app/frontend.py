from nicegui import ui

from app.core.project.ui import all_projects_subpage, project_subpage
from app.core.device.ui import device_subpage
from app.routes import projects_url, ROUTE_DEVICE, ROUTE_PROJECT, ROUTE_PROJECTS
from app.config import app_config

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


def _user_menu() -> None:
    with ui.button(icon='person').props('flat color=white'):
        with ui.menu():
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('light_mode').props('size=large')
                ui.label('Light Mode').on('click', lambda: ui.dark_mode().disable())
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('dark_mode').props('size=large')
                ui.label('Dark Mode').on('click', lambda: ui.dark_mode().enable())


@ui.page('/')
@ui.page('/{_:path}')
async def home_page():
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
        ui.sub_pages(
            {
                ROUTE_PROJECTS: all_projects_subpage,
                ROUTE_PROJECT:  project_subpage,
                ROUTE_DEVICE:   device_subpage,
            },
            data={'nav': nav},
        ).classes('w-full')
