import plotly.graph_objects as go

from typing import Optional
from nicegui import PageArguments, app, ui

from app.core.project.ui import all_projects_subpage, project_subpage
from app.ui.theme import frame
import logging
log = logging.getLogger('uvicorn')


# ***************************************************************************

async def device_subpage(args: PageArguments, title: ui.label, breadcrumbs: ui.element, project_id: str, device_id: str, tab: Optional[str] = None):
    title.text = f'Device {project_id}/{device_id}'
    breadcrumbs.clear()
    with breadcrumbs:
        ui.element('q-breadcrumbs-el').props('icon=home').on('click', lambda: ui.navigate.to('/'))
        ui.element('q-breadcrumbs-el').props(f'label={project_id}').on('click', lambda: ui.navigate.to(f'/{project_id}'))
        ui.element('q-breadcrumbs-el').props(f'label={device_id}').on('click', lambda: ui.navigate.to(f'/{project_id}/{device_id}'))

    with ui.tabs().classes('w-full') as tabs:
        dashboard_tab = ui.tab('Dashboard')
        settings_tab = ui.tab('Settings')
        data_explorer_tab = ui.tab('Data')
        log_explorer_tab = ui.tab('Logs')
    tab = 'Dashboard' if not tab else tab
    with ui.tab_panels(tabs, value=tab) as panels:
        with ui.tab_panel(dashboard_tab):
            ui.label('Alarms').classes('text-h6 font-bold')
            ui.label('Monitoring').classes('text-h6 font-bold')
            ui.label('Logs').classes('text-h6 font-bold')
        with ui.tab_panel(settings_tab):
            ui.label('Device Settings').classes('text-h6 font-bold')
            ui.label('Authentication Tokens').classes('text-h6 font-bold')
        with ui.tab_panel(data_explorer_tab):
            ui.label('Data Visualization').classes('text-h6 font-bold')
        with ui.tab_panel(log_explorer_tab):
            ui.label('Logs').classes('text-h6 font-bold')

logo = '''
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="32" height="32">
  <g fill="none" stroke="white" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
    <!-- Globe outline -->
    <circle cx="32" cy="32" r="15.37"/>
    <!-- Parallels -->
    <ellipse cx="32" cy="32" rx="15.37" ry="5.13"/>
    <ellipse cx="32" cy="32" rx="15.37" ry="10.26"/>
    <!-- Meridians -->
    <ellipse cx="32" cy="32" rx="5.13" ry="15.37"/>
    <ellipse cx="32" cy="32" rx="10.26" ry="15.37"/>
    <!-- Spokes to outer nodes -->
    <line x1="47.37" y1="32" x2="53.33" y2="32"/>
    <line x1="41.03" y1="17.33" x2="43.59" y2="12.11"/>
    <line x1="22.97" y1="17.33" x2="20.41" y2="12.11"/>
    <line x1="16.63" y1="32" x2="10.67" y2="32"/>
    <line x1="22.97" y1="46.67" x2="20.41" y2="51.89"/>
    <line x1="41.03" y1="46.67" x2="43.59" y2="51.89"/>
    <!-- Nodes -->
    <circle cx="53.33" cy="32" r="1.92"/>
    <circle cx="43.59" cy="12.11" r="1.92"/>
    <circle cx="20.41" cy="12.11" r="1.92"/>
    <circle cx="10.67" cy="32" r="1.92"/>
    <circle cx="20.41" cy="51.89" r="1.92"/>
    <circle cx="43.59" cy="51.89" r="1.92"/>
  </g>
</svg>
'''


@ui.page('/')
@ui.page('/{_:path}')
async def home_page():
    with ui.header(elevated=True).classes('items-center justify-between'):
        ui.html(logo).props('width=16 height=16').classes('text-white')
        ui.label('4IoT').classes('text-h6 font-bold')
        breadcrumbs = ui.element('q-breadcrumbs').props('active-color=white')
        # with breadcrumbs:
        #     ui.element('q-breadcrumbs-el').props('icon=home').on('click', lambda: ui.navigate.to('/'))
        ui.space()
        title = ui.label().classes('text-h6 font-bold')
        ui.space()
        search = ui.input(placeholder='Search').props('type=search clearable rounded outlined dense bg-color=white').classes('w-64')
        user_menu = ui.button(icon='person').props('outline round size=md dense color=white')

    # left_drawer = ui.left_drawer(fixed=False).props('bordered')

    with ui.column().classes('w-full'):
        ui.sub_pages({
                '/': all_projects_subpage,
                '/{project_id}': project_subpage,
                '/{project_id}/devices/{device_id}': device_subpage,
            },
            data={
                'title': title,
                'breadcrumbs': breadcrumbs
            },
        ).classes('w-full')
