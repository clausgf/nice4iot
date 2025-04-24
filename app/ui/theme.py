from contextlib import contextmanager
from nicegui import ui


main_menu = [
    {'label': 'Projects', 'icon': None, 'link': '/projects'},
    {'label': 'Project Overview', 'icon': None, 'link': '/projects'},
    {'label': 'Devices', 'icon': None, 'link': '/devices'},
    {'label': 'Device Overview', 'icon': None, 'link': '/devices'},
    {'label': 'Adapters', 'icon': None, 'link': '/adapters'},
    {'label': 'Settings', 'icon': 'settings', 'link': '/settings'},
]


def user_menu():
    with ui.button(icon='person').props('flat color=white'):
        with ui.menu() as menu:
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('settings').props('size=large')
                ui.label('Settings') #.on('click', lambda: ui.dialog('Settings').show())
            ui.separator()
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('light_mode').props('size=large')
                ui.label('Light Mode').on('click', lambda: ui.dark_mode().disable())
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('dark_mode').props('size=large')
                ui.label('Dark Mode').on('click', lambda: ui.dark_mode().enable())
            with ui.menu_item().classes('items-center gap-x-2'):
                ui.icon('logout').props('size=large')
                ui.label('Logout')


@contextmanager
def frame(navigation_title: str):
    """Page frame to share the same styling and navigation across all pages."""
    with ui.header(elevated=True).classes('items-center justify-between'):
        ui.button(on_click=lambda: left_drawer.toggle(), icon='menu').props('flat color=white')
        ui.label('4IoT').classes('text-h6 font-bold')
        ui.space()
        title = navigation_title if navigation_title is not None else 'Internet of Things'
        ui.label(title).classes('text-h6 font-bold')
        ui.space()
        user_menu()
    with ui.left_drawer(fixed=False).props('bordered') as left_drawer:
        # main menu
        for item in main_menu:
            with ui.row().classes('w-full'):
                if item['icon']:
                    ui.icon(item['icon']).props('size=sm dense')
                ui.label(item['label']).classes('font-bold').on('click', lambda l=item['link']: ui.navigate.to(l)).props('size=sm dense')
    with ui.column().classes('w-full'):
        yield
