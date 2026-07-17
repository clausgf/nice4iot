"""
Extension registries.

Extensions are separately installed packages under the ``extensions.*``
namespace (see docs/extensions.md). Each extension's ``register(app)`` is
called once at startup (app/main.py) inside a ``registering(name)``
context, so every register_*() call here automatically knows which
extension it belongs to. UI code (app/core/project/ui.py,
app/core/device/ui.py) and the device backend (app/core/device/backend.py)
consume the registries; project/device-scoped entries are filtered by
per-project enablement (Project.enabled_extensions) at the point of use —
extensions are never re-registered/deregistered when toggled.

No framework here on purpose — plain lists, appended to and iterated.
"""
import contextlib
import contextvars
import inspect
from typing import Any, Callable, Literal

import anyio
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from app.core.device.models import Device
from app.util import logger

CardSection = Literal['dashboard', 'general']

_project_dashboard_cards: list[tuple[str, Callable[[str], Any]]] = []
_project_general_cards: list[tuple[str, str, Callable[[str], Any]]] = []  # (extension_name, title, render_fn)
_device_dashboard_cards: list[tuple[str, Callable[[str, str], Any]]] = []
_device_general_cards: list[tuple[str, str, Callable[[str, str], Any]]] = []
_global_cards: list[tuple[str, str, Callable[[], Any]]] = []  # (extension_name, title, render_fn)

_project_tabs: list[tuple[str, str, Callable[[str], Any]]] = []  # (extension_name, label, render_fn)
_device_tabs: list[tuple[str, str, Callable[[str, str], Any]]] = []

_project_pages: dict[str, Callable[[str], Any]] = {}  # extension_name -> render_fn

_device_provisioned_callbacks: list[tuple[str, Callable[[Device], None]]] = []

_current_extension: contextvars.ContextVar[str | None] = contextvars.ContextVar('_current_extension', default=None)
_registered_extension_names: set[str] = set()


@contextlib.contextmanager
def registering(extension_name: str):
    """Mark *extension_name* as the extension whose register(app) is currently running.

    Every register_*() call made while this context is active is attributed
    to extension_name. Called once per installed extension by app/main.py's
    discovery loop.
    """
    _registered_extension_names.add(extension_name)
    token = _current_extension.set(extension_name)
    try:
        yield
    finally:
        _current_extension.reset(token)


def _extension_name() -> str:
    name = _current_extension.get()
    if name is None:
        raise RuntimeError(
            "app.extensions.register_*() called outside of an extension's "
            "register(app) — must be called from within register(app)"
        )
    return name


def get_registered_extension_names() -> list[str]:
    """Return the sorted names of every installed extension (see docs/extensions.md)."""
    return sorted(_registered_extension_names)


def _enabled_extensions(project_name: str) -> set[str]:
    """Extension names enabled for *project_name*, loaded with a single project read.

    Empty if the project can't be loaded, mirroring the defensive style
    already used for project lookups throughout app/mqtt/backend.py.
    The get_*() functions below use this instead of one is_extension_enabled()
    call per registered entry, which would re-read the project file each time.
    """
    from app.core.project.backend import get_project

    try:
        project = get_project(project_name, check_active=False)
    except Exception:
        return set()
    return set(project.enabled_extensions)


def is_extension_enabled(project_name: str, extension_name: str) -> bool:
    """Return whether *extension_name* is enabled for *project_name*."""
    return extension_name in _enabled_extensions(project_name)


async def maybe_await(result: Any) -> None:
    """Await *result* if it is awaitable (extension render_fn/callbacks may be sync or async)."""
    if inspect.isawaitable(result):
        await result


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def register_project_card(section: CardSection, render_fn: Callable[[str], Any], *,
                           title: str | None = None) -> None:
    """Register a card rendered on the project Dashboard or General tab.

    render_fn(project_name) is called while a surrounding ui.grid() is being
    built. May be sync or async.

    'dashboard' cards create their own ui.card() inside render_fn (a
    compact, always-visible summary — no title= here). 'general' cards do
    NOT create their own card/expansion: nice4iot renders a uniform
    foldable header for you, using the required title=, matching the
    built-in config cards on that tab.
    """
    extension_name = _extension_name()
    if section == 'dashboard':
        if title is not None:
            raise ValueError("register_project_card('dashboard', ...) does not take title= "
                              "— dashboard cards render their own ui.card()")
        _project_dashboard_cards.append((extension_name, render_fn))
    elif section == 'general':
        if title is None:
            raise ValueError("register_project_card('general', ...) requires title= "
                              "— nice4iot renders the card chrome for you")
        _project_general_cards.append((extension_name, title, render_fn))
    else:
        raise ValueError(f"unknown card section {section!r} (must be 'dashboard' or 'general')")


def register_device_card(section: CardSection, render_fn: Callable[[str, str], Any], *,
                          title: str | None = None) -> None:
    """Register a card rendered on the device Dashboard or General tab.

    render_fn(project_name, device_name), same conventions (and the same
    title= rule for 'general') as register_project_card().
    """
    extension_name = _extension_name()
    if section == 'dashboard':
        if title is not None:
            raise ValueError("register_device_card('dashboard', ...) does not take title= "
                              "— dashboard cards render their own ui.card()")
        _device_dashboard_cards.append((extension_name, render_fn))
    elif section == 'general':
        if title is None:
            raise ValueError("register_device_card('general', ...) requires title= "
                              "— nice4iot renders the card chrome for you")
        _device_general_cards.append((extension_name, title, render_fn))
    else:
        raise ValueError(f"unknown card section {section!r} (must be 'dashboard' or 'general')")


def get_project_dashboard_cards(project_name: str) -> list[Callable[[str], Any]]:
    """Return render functions for dashboard cards enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [fn for ext, fn in _project_dashboard_cards if ext in enabled]


def get_project_general_cards(project_name: str) -> list[tuple[str, Callable[[str], Any]]]:
    """Return (title, render_fn) for General-tab cards enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [(title, fn) for ext, title, fn in _project_general_cards if ext in enabled]


def get_device_dashboard_cards(project_name: str) -> list[Callable[[str, str], Any]]:
    """Return render functions for dashboard cards enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [fn for ext, fn in _device_dashboard_cards if ext in enabled]


def get_device_general_cards(project_name: str) -> list[tuple[str, Callable[[str, str], Any]]]:
    """Return (title, render_fn) for General-tab cards enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [(title, fn) for ext, title, fn in _device_general_cards if ext in enabled]


def register_global_card(title: str, render_fn: Callable[[], Any]) -> None:
    """Register a project-independent global configuration card.

    Rendered once on the Projects overview page, alongside the built-in
    MQTT broker card. render_fn should NOT create its own ui.card()/
    ui.expansion() — nice4iot renders a uniform foldable header for you,
    using title, same as 'general' project/device cards. Not gated by
    per-project enablement: there is no project to check, so it always
    renders once the extension is installed. May be sync or async.
    """
    _global_cards.append((_extension_name(), title, render_fn))


def get_global_cards() -> list[tuple[str, Callable[[], Any]]]:
    """Return (title, render_fn) for every registered global config card, in registration order."""
    return [(title, fn) for _ext, title, fn in _global_cards]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def register_project_tab(label: str, render_fn: Callable[[str], Any]) -> None:
    """Register a whole extra tab on the project page, addressed via ?tab=<label>."""
    _project_tabs.append((_extension_name(), label, render_fn))


def register_device_tab(label: str, render_fn: Callable[[str, str], Any]) -> None:
    """Register a whole extra tab on the device page, addressed via ?tab=<label>."""
    _device_tabs.append((_extension_name(), label, render_fn))


def get_project_tabs(project_name: str) -> list[tuple[str, Callable[[str], Any]]]:
    """Return (label, render_fn) for tabs enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [(label, fn) for ext, label, fn in _project_tabs if ext in enabled]


def get_device_tabs(project_name: str) -> list[tuple[str, Callable[[str, str], Any]]]:
    """Return (label, render_fn) for tabs enabled for project_name."""
    enabled = _enabled_extensions(project_name)
    return [(label, fn) for ext, label, fn in _device_tabs if ext in enabled]


# ---------------------------------------------------------------------------
# Standalone project pages
# ---------------------------------------------------------------------------

def register_project_page(render_fn: Callable[[str], Any]) -> None:
    """Register a standalone page at /<project_id>/ext/<extension_name>.

    render_fn(project_name) gets full control of the page content — no
    nice4iot header/navigation is rendered around it, and there is no
    mandatory back-link (add your own with app.routes.project_url() if
    you want one). Still gated by login and per-project enablement,
    both checked before render_fn runs. Only one page per extension.
    """
    extension_name = _extension_name()
    if extension_name in _project_pages:
        raise RuntimeError(
            f"extension {extension_name!r} already registered a project page (only one allowed)"
        )
    _project_pages[extension_name] = render_fn


def get_project_page(extension_name: str) -> Callable[[str], Any] | None:
    """Return the registered standalone-page render_fn for extension_name, or None."""
    return _project_pages.get(extension_name)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def register_device_provisioned_callback(fn: Callable[[Device], None]) -> None:
    """Register a callback invoked whenever a new device is created —

    auto-provisioned via MQTT, auto-provisioned via the HTTP provisioning
    API, or added manually through the UI. fn(device) must be synchronous:
    create_device() itself is synchronous and commonly runs in a worker
    thread (anyio.to_thread.run_sync), where there is no running event
    loop to schedule async work on. Only fires when the extension is
    enabled for device.project_name.
    """
    _device_provisioned_callbacks.append((_extension_name(), fn))


def notify_device_provisioned(device: Device) -> None:
    """Call every registered, enabled device-provisioned callback, logging (not raising) on error."""
    enabled = _enabled_extensions(device.project_name)
    for ext, fn in _device_provisioned_callbacks:
        if ext not in enabled:
            continue
        try:
            fn(device)
        except Exception as e:
            logger.error(f"device_provisioned callback {fn!r} failed: {e}")


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

def mount_extension_router(app: FastAPI, router: APIRouter) -> None:
    """Mount an extension's REST router under /api/ext/<extension_name>/...

    Every route in *router* must declare a project_name path parameter
    (e.g. "/{project_name}/screens/{screen_id}") — a dependency reads it
    and 404s the request when the extension is disabled for that project,
    before the route handler runs. A route without a project_name
    parameter raises RuntimeError at request time (a programming error,
    not a silent bypass).
    """
    extension_name = _extension_name()

    async def _require_enabled(request: Request) -> None:
        if 'project_name' not in request.path_params:
            raise RuntimeError(
                f"extension {extension_name!r}: route {request.url.path!r} has no "
                f"'project_name' path parameter, required by mount_extension_router()"
            )
        project_name = request.path_params['project_name']
        # Async-IO rule (CLAUDE.md): this dependency runs on the event loop,
        # but the enablement check reads the project file from disk.
        enabled = await anyio.to_thread.run_sync(
            lambda: is_extension_enabled(project_name, extension_name))
        if not enabled:
            raise HTTPException(status_code=404)

    app.include_router(router, prefix=f"/api/ext/{extension_name}", dependencies=[Depends(_require_enabled)])


# ---------------------------------------------------------------------------
# Test/reload support
# ---------------------------------------------------------------------------

def _clear_registries() -> None:
    """Reset all registries. For test isolation only."""
    _project_dashboard_cards.clear()
    _project_general_cards.clear()
    _device_dashboard_cards.clear()
    _device_general_cards.clear()
    _global_cards.clear()
    _project_tabs.clear()
    _device_tabs.clear()
    _project_pages.clear()
    _device_provisioned_callbacks.clear()
    _registered_extension_names.clear()
