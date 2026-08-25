"""Smoke tests for the Firmware Seed cards.

Device-level: has the "AP based Setup" button (QR icon) for this already-
existing device. Project-level: deliberately has no device-seeding shortcut —
device creation belongs on the Devices tab, not buried in Settings (see
seed_settings_card's docstring). The dialog/creation logic itself
(ap_qr_dialog, prompt_create_device) is covered elsewhere (test_seed_actions.py,
app/core/device/ui.py's own callers).
"""
import asyncio

import pytest
from nicegui import ui

from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.seed.ui import device_seed_override_card, seed_settings_card
from app.paths import device_dir, project_dir

from tests.conftest import setup_project


@pytest.fixture
def project_with_device(projects_dir):
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    return 'proj', 'dev'


def _find_all(el, cls, out=None):
    out = [] if out is None else out
    for slot in el.slots.values():
        for child in slot.children:
            if isinstance(child, cls):
                out.append(child)
            _find_all(child, cls, out)
    return out


def _render(coro):
    container = ui.column()

    async def run() -> None:
        with container:
            await coro

    asyncio.run(run())
    return container


def _ap_setup_button(container):
    return next((b for b in _find_all(container, ui.button)
                if b._props.get('icon') == 'qr_code'), None)


def test_project_seed_card_has_no_ap_based_setup_button(project_with_device):
    project, _device = project_with_device
    container = _render(seed_settings_card(project_dir(project)))

    assert _ap_setup_button(container) is None


def test_device_seed_card_has_ap_based_setup_button(project_with_device):
    project, device = project_with_device
    container = _render(device_seed_override_card(
        device_dir(project, device), project_name=project, device_name=device))

    button = _ap_setup_button(container)
    assert button is not None
    assert button.text == 'AP based Setup'
