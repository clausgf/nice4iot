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
    items = project_nav_items('proj', [('epaper', 'E-Paper', 'tv', object())],
                              [('Some Card', object())])
    labels = [i.label for i in items]
    assert labels == ['Project', 'epaper', 'Settings']

    project_group = items[0]
    assert project_group.url is None  # a group, not a leaf — see app.ui.NavItem
    assert [c.label for c in project_group.children] == ['Dashboard', 'Files', 'Devices']
    assert project_group.children[0].url == project_url('proj')
    assert project_group.children[1].url == project_url('proj', tab='files')
    assert project_group.children[2].url == project_url('proj', tab='devices')

    ext_group = items[1]
    assert ext_group.url is None
    assert [c.label for c in ext_group.children] == ['E-Paper']
    assert ext_group.children[0].url == project_url('proj', tab='tab/e-paper')
    assert ext_group.children[0].icon == 'tv'

    settings = items[2]
    assert settings.url is None
    child_labels = [c.label for c in settings.children]
    assert child_labels[:2] == ['Project', 'Provisioning']
    assert 'Some Card' in child_labels
    project_child = next(c for c in settings.children if c.label == 'Project')
    assert project_child.url == project_url('proj', tab='settings/project')
    card_child = next(c for c in settings.children if c.label == 'Some Card')
    assert card_child.url == project_url('proj', tab='settings/tab/some-card')


def test_project_nav_items_groups_multiple_tabs_under_one_extension():
    fn = object()
    items = project_nav_items('proj', [
        ('epaper', 'Rooms', 'meeting_room', fn),
        ('epaper', 'Screens', 'wallpaper', fn),
    ])
    ext_groups = [i for i in items if i.label == 'epaper']
    assert len(ext_groups) == 1  # one group, not one per tab
    assert [c.label for c in ext_groups[0].children] == ['Rooms', 'Screens']


def test_project_nav_items_separate_groups_per_extension():
    fn = object()
    items = project_nav_items('proj', [
        ('epaper', 'Rooms', 'meeting_room', fn),
        ('weather', 'Forecast', 'cloud', fn),
    ])
    labels = [i.label for i in items]
    assert labels == ['Project', 'epaper', 'weather', 'Settings']


# ---------------------------------------------------------------------------
# render_sidebar — two-level groups (Settings and its children)
# ---------------------------------------------------------------------------

def test_render_sidebar_group_header_is_not_clickable_only_children_are():
    from app.ui import NavItem, render_sidebar

    container = ui.column()
    items = [
        NavItem('Dashboard', 'dashboard', '/ui/project/proj'),
        NavItem('Settings', 'settings', children=(
            NavItem('General', 'info', '/ui/project/proj/settings/general'),
            NavItem('Alarms', 'notifications', '/ui/project/proj/settings/alarms'),
        )),
    ]
    render_sidebar(container, 'proj', items)

    items_found = _find_all(container, ui.item)
    # every ui.item() we build is clickable via .props('clickable ...') except
    # the group header, which omits it.
    group_header = next(i for i in items_found if _labels(i) == ['Settings'])
    assert 'clickable' not in group_header._props
    general_row = next(i for i in items_found if _labels(i) == ['General'])
    assert 'clickable' in general_row._props


def test_render_sidebar_highlights_active_child_and_indents_children():
    from app.ui import NavItem, render_sidebar
    from nicegui import context

    # current_path is UI_PREFIX-prefixed in production (nice4iot mounts NiceGUI
    # at the ASGI root, so nothing strips '/ui' from it) — see app.ui._current_path.
    context.client.sub_pages_router.current_path = '/ui/project/proj/settings/alarms'
    container = ui.column()
    items = [
        NavItem('Dashboard', 'dashboard', '/ui/project/proj'),
        NavItem('Settings', 'settings', children=(
            NavItem('General', 'info', '/ui/project/proj/settings/general'),
            NavItem('Alarms', 'notifications', '/ui/project/proj/settings/alarms'),
        )),
    ]
    render_sidebar(container, 'proj', items)

    items_found = _find_all(container, ui.item)
    alarms_row = next(i for i in items_found if _labels(i) == ['Alarms'])
    general_row = next(i for i in items_found if _labels(i) == ['General'])
    assert 'bg-primary' in alarms_row._classes
    assert 'bg-primary' not in general_row._classes
    assert alarms_row._props.get('inset-level') == '0.5'


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
            # trivially fail for the wrong reason. UI_PREFIX-prefixed: see the
            # test above and app.ui._current_path.
            context.client.sub_pages_router.current_path = f'/ui/project/{project_id}'
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
    for expected in ('Dashboard', 'Project', 'Files', 'Devices'):
        assert expected in sidebar_labels

    # Dashboard is the default (root) route.
    assert 'Device Health' in _labels(container)

    # Regression: ui.sub_pages is itself a flex column with align-items:
    # flex-start, so every route rendered through it (Project's two-column
    # grid, extension tabs, ...) silently shrink-wraps without this.
    from nicegui.elements.sub_pages import SubPages
    sub_pages = _find_all(container, SubPages)[0]
    assert 'w-full' in sub_pages._classes


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
            context.client.sub_pages_router.current_path = '/settings/project'
            await project_subpage(_page_args(), nav, sidebar, drawer, hamburger, project)
        await _drain()

    asyncio.run(run())
    # config_expansion() titles are Quasar-rendered (not plain ui.label text),
    # so assert on genuine content instead — project_card()'s own MQTT-toggle
    # description, absent from Dashboard.
    labels = _labels(container)
    assert any('MQTT broker' in label for label in labels)
    assert 'Device Health' not in labels


def test_project_subpage_extension_settings_card_gets_config_expansion_chrome(project_with_device):
    """Regression: an extension 'settings' card (register_project_card) renders
    fields only — nice4iot must supply the config_expansion chrome, same as
    the old flat General tab gave it. A first cut of the Settings routing
    reused the plain (chrome-less) extension-tab route for these too."""
    from app.extensions import register_project_card, registering
    from app.core.project.backend import project_adapter

    project, _device = project_with_device
    with registering('ext1'):
        register_project_card('settings', lambda project_name: ui.label('card body'), title='Ext Card')
    adapter = project_adapter(project)
    p = adapter.read()
    p.enabled_extensions.append('ext1')
    adapter.save(p)

    nav = ui.row()
    sidebar = ui.column()
    drawer = _FakeToggle()
    hamburger = _FakeToggle()
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            from nicegui import context
            context.client.sub_pages_router.current_path = '/settings/tab/ext-card'
            await project_subpage(_page_args(), nav, sidebar, drawer, hamburger, project)
        await _drain()

    asyncio.run(run())
    from nicegui.elements.expansion import Expansion
    expansions = _find_all(container, Expansion)
    assert any(e.text == 'Ext Card' for e in expansions)
    assert 'card body' in _labels(container)


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
    for expected in ('Dashboard', 'Project', 'Files', 'Devices'):
        assert expected in sidebar_labels

    items = _find_all(sidebar, ui.item)
    devices_item = next(i for i in items if 'Devices' in _labels(i))
    assert 'bg-primary' in devices_item._classes

    # the device's own horizontal tab strip is untouched
    tab_labels = [t.props.get('label') or t.props.get('name') for t in _find_all(container, ui.tab)]
    assert 'Dashboard' in tab_labels
    assert 'Data' in tab_labels
    assert 'Logs' in tab_labels


def test_device_general_tab_has_firmware_download_card(project_with_device):
    """Regression: a 2026-08-05 refactor (commit d472c1a) silently dropped the
    device-level Firmware Download card from device_general_panel() — the
    backend (per-directory FirmwareSource) never lost the ability, only the
    UI wiring did, unnoticed for 15+ releases since nothing rendered this
    panel in a test."""
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
            await device_subpage(_page_args(), nav, sidebar, drawer, hamburger, project, device, tab='General')
        await _drain()

    asyncio.run(run())

    # config_expansion() titles are Quasar-rendered (the expansion's own
    # `text`, a prop), not plain ui.label/item_label text — see
    # test_project_subpage_extension_settings_card_gets_config_expansion_chrome.
    from nicegui.elements.expansion import Expansion
    expansion_titles = [e.text for e in _find_all(container, Expansion)]
    assert 'Firmware Seed' in expansion_titles
    assert 'Firmware Download' in expansion_titles
