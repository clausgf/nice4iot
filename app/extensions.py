"""
Extension registries.

Extensions are separately installed packages under the ``extensions.*``
namespace (see docs/extensions.md). Each extension's ``register(app)`` is
called once at startup (app/main.py) and populates these registries. UI
code (app/core/project/ui.py, app/core/device/ui.py) and the device
backend (app/core/device/backend.py) consume them.

No framework here on purpose — plain lists, appended to and iterated.
"""
import inspect
from typing import Any, Callable, Literal

from app.core.device.models import Device
from app.util import logger

CardSection = Literal['dashboard', 'general']

_project_cards: dict[CardSection, list[Callable[[str], Any]]] = {'dashboard': [], 'general': []}
_device_cards: dict[CardSection, list[Callable[[str, str], Any]]] = {'dashboard': [], 'general': []}

_project_tabs: list[tuple[str, Callable[[str], Any]]] = []
_device_tabs: list[tuple[str, Callable[[str, str], Any]]] = []

_device_provisioned_callbacks: list[Callable[[Device], Any]] = []


async def maybe_await(result: Any) -> None:
    """Await *result* if it is awaitable (extension render_fn/callbacks may be sync or async)."""
    if inspect.isawaitable(result):
        await result


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def register_project_card(section: CardSection, render_fn: Callable[[str], Any]) -> None:
    """Register a card rendered on the project Dashboard or General tab.

    render_fn(project_name) is called while a surrounding ui.grid() is being
    built; create your own ui.card() inside it. May be sync or async.
    """
    _project_cards[section].append(render_fn)


def register_device_card(section: CardSection, render_fn: Callable[[str, str], Any]) -> None:
    """Register a card rendered on the device Dashboard or General tab.

    render_fn(project_name, device_name), same conventions as
    register_project_card().
    """
    _device_cards[section].append(render_fn)


def get_project_cards(section: CardSection) -> list[Callable[[str], Any]]:
    return list(_project_cards[section])


def get_device_cards(section: CardSection) -> list[Callable[[str, str], Any]]:
    return list(_device_cards[section])


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def register_project_tab(label: str, render_fn: Callable[[str], Any]) -> None:
    """Register a whole extra tab on the project page, addressed via ?tab=<label>."""
    _project_tabs.append((label, render_fn))


def register_device_tab(label: str, render_fn: Callable[[str, str], Any]) -> None:
    """Register a whole extra tab on the device page, addressed via ?tab=<label>."""
    _device_tabs.append((label, render_fn))


def get_project_tabs() -> list[tuple[str, Callable[[str], Any]]]:
    return list(_project_tabs)


def get_device_tabs() -> list[tuple[str, Callable[[str, str], Any]]]:
    return list(_device_tabs)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def register_device_provisioned_callback(fn: Callable[[Device], None]) -> None:
    """Register a callback invoked whenever a new device is created —

    auto-provisioned via MQTT, auto-provisioned via the HTTP provisioning
    API, or added manually through the UI. fn(device) must be synchronous:
    create_device() itself is synchronous and commonly runs in a worker
    thread (anyio.to_thread.run_sync), where there is no running event
    loop to schedule async work on.
    """
    _device_provisioned_callbacks.append(fn)


def notify_device_provisioned(device: Device) -> None:
    """Call every registered device-provisioned callback, logging (not raising) on error."""
    for fn in _device_provisioned_callbacks:
        try:
            fn(device)
        except Exception as e:
            logger.error(f"device_provisioned callback {fn!r} failed: {e}")


# ---------------------------------------------------------------------------
# Test/reload support
# ---------------------------------------------------------------------------

def _clear_registries() -> None:
    """Reset all registries. For test isolation only."""
    for section in _project_cards:
        _project_cards[section].clear()
    for section in _device_cards:
        _device_cards[section].clear()
    _project_tabs.clear()
    _device_tabs.clear()
    _device_provisioned_callbacks.clear()
