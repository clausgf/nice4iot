"""Shared NiceGUI presentation helpers used across nice4iot's own UI and by extensions."""
from contextlib import contextmanager
from typing import Generator

from nicegui import ui

from app.routes import device_url, project_url

# ***************************************************************************

def refresh_breadcrumbs(nav: ui.element, project_id: str | None = None, device_id: str | None = None) -> None:
    nav.clear()
    with nav:
        if project_id is not None:
            ui.label('/').classes('text-h6 text-white')
            ui.label(project_id).classes('text-h6 cursor-pointer text-white') \
                .tooltip('Project page') \
                .on('click', lambda: ui.navigate.to(project_url(project_id)))
            if device_id is not None:
                ui.label('/').classes('text-h6 text-white')
                ui.label(device_id).classes('text-h6 cursor-pointer text-white') \
                    .tooltip('Device page') \
                    .on('click', lambda: ui.navigate.to(device_url(project_id, device_id)))

# ***************************************************************************

@contextmanager
def config_expansion(title: str, *, value: bool = False) -> Generator[ui.expansion, None, None]:
    """Foldable card shared by every config-style card (General tab, global settings).

    Opens the enclosing ui.card() itself, so callers only need one `with`:

        with config_expansion('Telemetry'):
            TelemetryCard(project_id)

    nice4iot renders this around each card's content itself rather than
    letting each card build its own header, so the look stays uniform —
    including for extension-registered 'general'/global cards (see
    app.extensions.register_project_card() et al.).
    """
    with ui.card().classes('w-full dense'):
        with ui.expansion(title, value=value).classes('w-full q-mb-none').props(
            'dense header-class="text-h6 font-bold"'
        ) as expansion:
            yield expansion

# ***************************************************************************

def status_avatar(ok: bool | None, icons: str | list[str], tooltips: str | list[str]) -> None:
    index = 0 if ok is None else (1 if ok is True else 2)
    icon = icons if isinstance(icons, str) else icons[index]
    t = ['disabled', 'enabled', 'error']
    tooltip = f'{tooltips} {t[index]}' if isinstance(tooltips, str) else tooltips[index]
    colors = ['grey', 'positive', 'negative']
    color = colors[index]
    ui.avatar(icon) \
        .props(f'color={color} text-color=white size=sm') \
        .tooltip(tooltip)

