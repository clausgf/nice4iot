"""Tests for the sidebar-based navigation (app/ui.py's NavItem/render_sidebar,
project_subpage's nested ui.sub_pages routing, device_subpage reusing the
project sidebar). No browser available in this environment, so these render
headlessly and inspect the resulting nicegui element tree directly — see
test_data_ui.py for the same approach and the reasoning behind the
core.loop-patching / draining helpers below.
"""
import asyncio

import pytest
from nicegui import core, ui
from starlette.datastructures import QueryParams

from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.project.ui import project_nav_items, project_subpage, slugify_tab_label
from app.core.device.ui import device_subpage
from app.routes import project_url

from tests.conftest import setup_project


class _FakeToggle:
    """Stands in for the drawer / hamburger button: show_sidebar()/hide_sidebar()
    only ever call .show()/.hide()/.set_visibility() on them, and a real
    ui.left_drawer() requires a true top-level page layout this test doesn't have."""

    def __init__(self):
        self.shown = None
        self.visible = None

    def show(self):
        self.shown = True

    def hide(self):
        self.shown = False

    def set_visibility(self, value: bool):
        self.visible = value


def _page_args():
    from nicegui import PageArguments
    return PageArguments(path='', frame=None, path_parameters={}, query_parameters=QueryParams(), data={})


def _find_all(el, cls, out=None):
    out = [] if out is None else out
    for slot in el.slots.values():
        for child in slot.children:
            if isinstance(child, cls):
                out.append(child)
            _find_all(child, cls, out)
    return out


def _labels(el) -> list[str]:
    """Text of every ui.label AND ui.item_label descendant (sidebar rows use
    item_label, a distinct class from plain ui.label)."""
    return [label.text for label in _find_all(el, ui.label) + _find_all(el, ui.item_label)]


async def _drain() -> None:
    """Let ui.sub_pages' background task (an async route builder) actually run."""
    for _ in range(3):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending)


@pytest.fixture
def project_with_device(projects_dir):
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    return 'proj', 'dev'


# ---------------------------------------------------------------------------
# slugify_tab_label / project_nav_items — pure logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('label,expected', [
    ('E-Paper', 'e-paper'),
    ('My Extension!', 'my-extension'),
    ('  spaced out  ', 'spaced-out'),
    ('', 'tab'),
])
def test_slugify_tab_label(label, expected):
    assert slugify_tab_label(label) == expected


def test_project_nav_items_built_in_and_extension():
    items = project_nav_items('proj', [('E-Paper', 'tv', object())])
    labels = [i.label for i in items]
    assert labels == ['Dashboard', 'General', 'Files', 'Devices', 'E-Paper']
    assert items[0].url == project_url('proj')
    assert items[1].url == project_url('proj', tab='general')
    assert items[3].url == project_url('proj', tab='devices')
    assert items[4].url == project_url('proj', tab='tab/e-paper')
    assert items[4].icon == 'tv'


# ---------------------------------------------------------------------------
# project_subpage — sidebar + nested routing
# ---------------------------------------------------------------------------

def _render_project_subpage(project_id: str):
    """Render project_subpage for project_id and return (nav, sidebar,
    drawer, hamburger, container) for inspection."""
    nav = ui.row()
    sidebar = ui.column()
    drawer = _FakeToggle()
    hamburger = _FakeToggle()
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            from nicegui import context
            # Matches what the router would already show for a real visit to
            # this project's (default) dashboard — the auto-index client's own
            # default ('/') wouldn't, so "is Dashboard the active row" would
            # trivially fail for the wrong reason.
            context.client.sub_pages_router.current_path = f'/project/{project_id}'
            await project_subpage(_page_args(), nav, sidebar, drawer, hamburger, project_id)
        await _drain()

    asyncio.run(run())
    return nav, sidebar, drawer, hamburger, container


def test_project_subpage_shows_sidebar_and_dashboard_by_default(project_with_device):
    project, _device = project_with_device
    nav, sidebar, drawer, hamburger, container = _render_project_subpage(project)

    assert drawer.shown is True
    assert hamburger.visible is True
    sidebar_labels = _labels(sidebar)
    assert sidebar_labels[0] == project  # heading
    for expected in ('Dashboard', 'General', 'Files', 'Devices'):
        assert expected in sidebar_labels

    # Dashboard is the default (root) route.
    assert 'Device Health' in _labels(container)


def test_project_subpage_dashboard_row_is_active_by_default(project_with_device):
    project, _device = project_with_device
    _nav, sidebar, _drawer, _hamburger, _container = _render_project_subpage(project)

    items = _find_all(sidebar, ui.item)
    dashboard_item = next(i for i in items if 'Dashboard' in _labels(i))
    assert 'bg-primary' in dashboard_item._classes


def test_project_subpage_missing_project_hides_sidebar(projects_dir):
    nav, sidebar, drawer, hamburger, container = _render_project_subpage('does-not-exist')

    assert drawer.shown is False
    assert hamburger.visible is False
    assert 'does not exist' in ' '.join(_labels(container))


def test_project_subpage_general_route(project_with_device):
    project, _device = project_with_device
    nav = ui.row()
    sidebar = ui.column()
    drawer = _FakeToggle()
    hamburger = _FakeToggle()
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            from nicegui import context
            context.client.sub_pages_router.current_path = '/general'
            await project_subpage(_page_args(), nav, sidebar, drawer, hamburger, project)
        await _drain()

    asyncio.run(run())
    # config_expansion() titles are Quasar-rendered (not plain ui.label text),
    # so assert on genuine General-tab content instead — a project_card()
    # field and the MQTT status card's own label, both absent from Dashboard.
    labels = _labels(container)
    assert any('MQTT broker' in label for label in labels)
    assert 'Device Health' not in labels


# ---------------------------------------------------------------------------
# device_subpage — reuses the project sidebar, own tabs unaffected
# ---------------------------------------------------------------------------

def test_device_subpage_shows_project_sidebar_with_devices_active(project_with_device):
    project, device = project_with_device
    nav = ui.row()
    sidebar = ui.column()
    drawer = _FakeToggle()
    hamburger = _FakeToggle()
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            from nicegui import context
            context.client.sub_pages_router.current_path = f'/project/{project}/device/{device}'
            await device_subpage(_page_args(), nav, sidebar, drawer, hamburger, project, device)
        await _drain()

    asyncio.run(run())

    assert drawer.shown is True
    assert hamburger.visible is True
    sidebar_labels = _labels(sidebar)
    for expected in ('Dashboard', 'General', 'Files', 'Devices'):
        assert expected in sidebar_labels

    items = _find_all(sidebar, ui.item)
    devices_item = next(i for i in items if 'Devices' in _labels(i))
    assert 'bg-primary' in devices_item._classes

    # the device's own horizontal tab strip is untouched
    tab_labels = [t.props.get('label') or t.props.get('name') for t in _find_all(container, ui.tab)]
    assert 'Dashboard' in tab_labels
    assert 'Data' in tab_labels
    assert 'Logs' in tab_labels
