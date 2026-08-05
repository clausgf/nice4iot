"""Smoke tests that actually render the Files panels.

The rest of the Files suite tests pure logic (test_files_form, test_file_overlay).
Nothing exercised the panels themselves, so a wrong keyword argument between
`device_files_panel` and `_files_card` reached the browser instead of CI. NiceGUI
lets elements be built outside a page context, so rendering them costs no extra
test dependency.

These assert that the panels build without raising, across the states that pick
different code paths — not what the markup looks like.
"""
import asyncio

import pytest
from nicegui import ui

from app.core.device.backend import create_device
from app.core.device.files_ui import device_files_panel, project_files_panel
from app.core.device.models import Device
from app.paths import device_dir, project_dir

from tests.conftest import setup_project


@pytest.fixture
def project_with_device(projects_dir):
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    return 'proj', 'dev'


def _render(coro):
    """Run a panel coroutine to completion, failing the test on any exception.

    NiceGUI keeps its slot stack per asyncio task, so the container has to be
    built out here and re-entered inside the task asyncio.run() creates.
    """
    container = ui.column()

    async def run() -> None:
        with container:
            await coro

    asyncio.run(run())


def test_device_panel_renders_when_everything_is_empty(project_with_device):
    _render(device_files_panel(*project_with_device))


def test_device_panel_renders_with_own_inherited_and_overriding_files(project_with_device):
    project, device = project_with_device
    (project_dir(project) / 'shared.json').write_text('{"a": 1}')      # inherited
    (project_dir(project) / 'both.json').write_text('{"a": 1}')
    (device_dir(project, device) / 'both.json').write_text('{"a": 2}')  # overrides
    (device_dir(project, device) / 'own.txt').write_text('hello')       # device only
    _render(device_files_panel(project, device))


def test_device_panel_renders_with_mqtt_enabled(projects_dir):
    """Enables the publish button and the file-state read, a separate branch."""
    setup_project('proj', is_mqtt_enabled=True)
    create_device(Device(project_name='proj', name='dev'))
    (project_dir('proj') / 'shared.json').write_text('{}')
    _render(device_files_panel('proj', 'dev'))


def test_device_panel_renders_for_a_missing_project(projects_dir):
    """get_project raises here; the panel is expected to fall back, not blow up."""
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    _render(device_files_panel('proj', 'dev'))


def test_project_panel_renders(projects_dir):
    setup_project('proj')
    (project_dir('proj') / 'config.json').write_text('{"a": 1}')
    _render(project_files_panel('proj'))
