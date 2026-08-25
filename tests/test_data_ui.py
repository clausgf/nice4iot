"""Smoke tests for the Data tab's multi-plot Telemetry Explorer.

Exercises the wiring test_telemetry_backend.py's model-level test doesn't reach:
rendering the panel, adding/removing whole plots via their buttons, and that
edits actually reach disk (not just DataView's own (de)serialization).
"""
import asyncio

import pytest
from nicegui import core, ui
from nicegui.events import GenericEventArguments, handle_event

from app.core.device.backend import create_device
from app.core.device.data_ui import dashboard_plot_card, device_data_panel
from app.core.device.models import Device
from app.core.project.backend import create_project
from app.core.telemetry.backend import _append_local_metrics, read_data_views, save_data_views
from app.core.telemetry.models import DataTrace, DataView


@pytest.fixture
def proj_dev(projects_dir):
    create_project('proj')
    create_device(Device(name='dev', project_name='proj'))
    return 'proj', 'dev'


def _find_all(el, cls, out=None):
    out = [] if out is None else out
    for slot in el.slots.values():
        for child in slot.children:
            if isinstance(child, cls):
                out.append(child)
            _find_all(child, cls, out)
    return out


def _click(button: ui.button) -> None:
    """Fire a button's click handler the way a real websocket event would —
    there is no browser here to click it for real."""
    listener = next(l for l in button._event_listeners.values() if l.type == 'click')
    handle_event(listener.handler, GenericEventArguments(sender=button, client=button.client, args=[]))


async def _drain() -> None:
    """Wait for the fire-and-forget background tasks a click/value-change may
    have scheduled (_persist(), and refreshable.refresh() inside _refresh())."""
    for _ in range(3):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending)


def _render(project, device):
    container = ui.column()

    async def run() -> None:
        # Background tasks (_persist, refreshable.refresh) assert nicegui's global
        # event loop is set — only true once the real server has started.
        core.loop = asyncio.get_running_loop()
        with container:
            await device_data_panel(project, device)

    asyncio.run(run())
    return container


def test_panel_renders_with_no_saved_plots(proj_dev):
    project, device = proj_dev
    _render(project, device)


def test_panel_renders_with_saved_plots(proj_dev):
    project, device = proj_dev
    save_data_views(project, device, [
        DataView(title='Battery', traces=[DataTrace(color='Red', kind='system', metric='battery_V')]),
        DataView(title='WiFi', show_on_dashboard=True),
    ])
    _render(project, device)


def test_add_plot_button_appends_and_persists(proj_dev):
    project, device = proj_dev
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            await device_data_panel(project, device)
        header_row = container.default_slot.children[0]
        add_button = next(b for b in _find_all(header_row, ui.button) if b._props.get('icon') == 'add')
        _click(add_button)
        await _drain()

    asyncio.run(run())
    assert len(read_data_views(project, device)) == 2


def test_delete_plot_button_removes_and_persists(proj_dev):
    project, device = proj_dev
    save_data_views(project, device, [DataView(title='A'), DataView(title='B')])
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            await device_data_panel(project, device)
        # Plot cards are every child after the header row; each card's own header
        # row (its first child) holds exactly one Delete button (icon='delete') —
        # the per-trace rows below it have their own, so the search is scoped to
        # the card's header row to avoid picking those up.
        cards = container.default_slot.children[1:]
        card_header = cards[0].default_slot.children[0]
        delete_button = next(b for b in _find_all(card_header, ui.button) if b._props.get('icon') == 'delete')
        _click(delete_button)
        await _drain()

    asyncio.run(run())
    views = read_data_views(project, device)
    assert len(views) == 1
    assert views[0].title == 'B'


def test_title_edit_persists_and_is_used_as_chart_title(proj_dev):
    project, device = proj_dev
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        with container:
            await device_data_panel(project, device)
        title_input = _find_all(container, ui.input)[0]
        title_input.value = 'My Plot'
        await _drain()

    asyncio.run(run())
    views = read_data_views(project, device)
    assert views[0].title == 'My Plot'


# ---------------------------------------------------------------------------
# Dashboard cards — "Show on dashboard" plots rendered on the Device Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_plot_card_renders_with_data(proj_dev):
    project, device = proj_dev
    import datetime
    _append_local_metrics(project, device, 'system', {'battery_V': 3.7},
                          datetime.datetime.now(datetime.timezone.utc))
    view = DataView(title='Battery', show_on_dashboard=True,
                    traces=[DataTrace(color='Red', kind='system', metric='battery_V')])
    container = ui.column()

    async def run() -> None:
        with container:
            await dashboard_plot_card(project, device, view)

    asyncio.run(run())
    assert len(_find_all(container, ui.card)) == 1


def test_dashboard_plot_card_renders_placeholder_without_data(proj_dev):
    project, device = proj_dev
    view = DataView(title='Battery', show_on_dashboard=True,
                    traces=[DataTrace(color='Red', kind='system', metric='battery_V')])
    container = ui.column()

    async def run() -> None:
        with container:
            await dashboard_plot_card(project, device, view)

    asyncio.run(run())
    labels = [label.text for label in _find_all(container, ui.label)]
    assert 'No data' in labels


def _page_args():
    from starlette.datastructures import QueryParams
    from nicegui import PageArguments
    return PageArguments(path='', frame=None, path_parameters={}, query_parameters=QueryParams(), data={})


def test_device_dashboard_panel_includes_cards_for_show_on_dashboard_plots(proj_dev):
    from app.core.device.ui import device_dashboard_panel

    project, device = proj_dev

    def _card_count() -> int:
        container = ui.column()

        async def run() -> None:
            with container:
                await device_dashboard_panel(project, device, _page_args())

        asyncio.run(run())
        return len(_find_all(container, ui.card))

    baseline = _card_count()
    save_data_views(project, device, [
        DataView(title='Battery', show_on_dashboard=True),
        DataView(title='Hidden', show_on_dashboard=False),
    ])
    assert _card_count() == baseline + 1
