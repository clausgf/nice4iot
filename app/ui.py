"""Shared NiceGUI presentation helpers used across nice4iot's own UI and by extensions."""
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

from nicegui import context, ui

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
    """Foldable card shared by every config-style card (Settings sections, global settings).

    Opens the enclosing ui.card() itself, so callers only need one `with`:

        with config_expansion('Telemetry'):
            TelemetryCard(project_id)

    nice4iot renders this around each card's content itself rather than
    letting each card build its own header, so the look stays uniform —
    including for extension-registered 'settings'/global cards (see
    app.extensions.register_project_card() et al.).
    """
    with ui.card().tight().classes('w-full'):
        with ui.expansion(title, value=value).classes('w-full q-mt-xs q-mb-xs').props(
            'dense header-class="text-h6 font-bold"'
        ) as expansion:
            yield expansion

# ***************************************************************************

@dataclass(frozen=True)
class NavItem:
    """One row in a page sidebar, or a two-level group of them.

    A leaf has a `url` (a full navigation target, e.g. from
    app.routes.project_url()) and no `children`. A group has `children` and
    no `url` of its own — it renders as a plain, non-clickable header (like
    nicepaper's own sidebar groups) with its children indented below it;
    clicking only ever navigates to a child, never the group itself. Only one
    level of nesting is supported, matching nicepaper's own sidebar.
    """
    label: str
    icon: str
    url: str | None = None
    children: tuple['NavItem', ...] = ()


def _current_path() -> str:
    """The browser's current path (UI_PREFIX-prefixed, no query string), for
    comparing against a NavItem's url.

    sub_pages_router.current_path is already UI_PREFIX-prefixed here: nice4iot
    mounts NiceGUI at the ASGI root ('/', ui.run_with()'s default), not at
    '/ui' -- '/ui' is just a matched @ui.page route pattern within that
    mount, not a submount, so nothing strips it from current_path. Prepending
    UI_PREFIX again used to double it (.../ui/ui/...), which never matched
    any NavItem.url and silently left every sidebar row unhighlighted."""
    return context.client.sub_pages_router.current_path.split('?')[0].rstrip('/')


def _leaves(items: list[NavItem]) -> list[NavItem]:
    return [item for top in items for item in ([top] if top.url is not None else top.children)]


def render_sidebar(container: ui.element, heading: str, items: list[NavItem], *,
                   active: NavItem | None = None) -> None:
    """(Re)populate `container`: a heading, then the nav rows — a leaf is one
    clickable row, a group a non-clickable header followed by its (indented)
    children. By default the active row is whichever leaf's url is the
    longest matching prefix of the current URL (longest, not first/exact, so
    a project tab that opens its own nested ui.sub_pages still highlights on
    any of its own sub-routes, while a plain leaf like Dashboard — whose url
    is every other item's own prefix — never wrongly outranks a more
    specific match). Pass `active` explicitly for a page whose real URL
    doesn't share a prefix with any item's own, so it can't be found this way.

    Call again whenever client-side sub_pages navigation changes the path,
    since the active row can change without this page's own builder re-running
    (see app/frontend.py's on_path_changed wiring).
    """
    if active is None:
        current = _current_path()
        active = max(
            (leaf for leaf in _leaves(items) if leaf.url is not None
             and (current == leaf.url.rstrip('/') or current.startswith(leaf.url.rstrip('/') + '/'))),
            key=lambda leaf: len(leaf.url or ''), default=None,
        )
    container.clear()
    with container:
        ui.label(heading).classes('text-subtitle1 font-bold q-pa-sm text-grey-8')
        ui.separator()
        with ui.list().props('padding').classes('w-full'):
            for item in items:
                if item.url is not None:
                    _nav_row(item, is_active=item is active)
                else:
                    with ui.item().props('dense').classes('rounded-borders'):
                        _nav_row_content(item, is_active=False)
                    for child in item.children:
                        _nav_row(child, is_active=child is active, inset=True)


def _nav_row_content(item: NavItem, *, is_active: bool) -> None:
    with ui.item_section().props('avatar').style('min-width: 0; padding-right: 12px'):
        ui.icon(item.icon).classes('' if is_active else 'text-primary')
    with ui.item_section():
        ui.item_label(item.label)


def _nav_row(item: NavItem, *, is_active: bool, inset: bool = False) -> None:
    assert item.url is not None
    row = ui.item(on_click=lambda _, u=item.url: ui.navigate.to(u)) \
        .props('clickable dense').classes('rounded-borders')
    if inset:
        row.props('inset-level=0.5')
    if is_active:
        row.classes('bg-primary text-white')
    with row:
        _nav_row_content(item, is_active=is_active)


def show_sidebar(drawer: ui.left_drawer, hamburger: ui.element, container: ui.element,
                 heading: str, items: list[NavItem], *, active: NavItem | None = None) -> None:
    """Populate `container` and reveal the drawer/hamburger — the project and
    device pages call this once per render. Call render_sidebar() again (not
    this) to just refresh which row is highlighted after an in-page
    navigation; re-showing/re-revealing on every such refresh is unnecessary."""
    render_sidebar(container, heading, items, active=active)
    drawer.show()
    hamburger.set_visibility(True)


def hide_sidebar(drawer: ui.left_drawer, hamburger: ui.element, container: ui.element) -> None:
    """No project/device context: nothing to show a sidebar for (Projects
    list, Preferences, About)."""
    container.clear()
    drawer.hide()
    hamburger.set_visibility(False)


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

