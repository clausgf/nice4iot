# Writing nice4iot extensions

nice4iot can be extended by separately versioned Python packages that add
their own REST endpoints, MQTT publish/subscribe, and UI elements (cards
and tabs on the project and device pages), and that get notified when a
new device is provisioned.

An extension is a normal `uv`/pip dependency — there is no plugin config
file to list installed extensions. Installing the package makes it
*available*; each project then opts in individually (see Activation below,
disabled by default).

## Package layout

Every extension's top-level package must be `extensions.<name>`, e.g.
`extensions.epaper`. `extensions` is a
[PEP 420 namespace package](https://peps.python.org/pep-0420/): nice4iot
itself ships an empty `extensions/` directory (no `__init__.py`), and each
installed extension contributes its own `extensions/<name>/` directory.
Python merges all of them into one importable `extensions` package at
runtime, and nice4iot discovers every installed extension by walking its
submodules — no registration list to keep in sync with your dependencies.

```
my-epaper-extension/
├── pyproject.toml
└── extensions/
    └── epaper/
        ├── __init__.py      # must define register(app), see below
        └── ...
```

**Critical rule: never add an `extensions/__init__.py`.** Only the
`extensions/<name>/__init__.py` files may exist. An `__init__.py` directly
inside `extensions/` turns it from a namespace package into a regular
package, which breaks the merge for *every other installed extension*, not
just yours.

A minimal `pyproject.toml` for a hatchling-based extension:

```toml
[project]
name = "my-epaper-extension"
dependencies = ["fastapi", "nicegui"]

[tool.hatch.build.targets.wheel]
packages = ["extensions/epaper"]
```

Only `extensions/epaper` is packaged (not `extensions/` itself), which is
what keeps the namespace package `__init__.py`-free after installation.

Also: your top-level package must not be named `app` — that collides with
nice4iot's own top-level package and one will shadow the other.

## Deployment

Add the extension as a normal dependency, exactly like `niceview`:

```
uv add git+https://example.com/your-org/my-epaper-extension.git
```

That's the only configuration step. On the next `uv sync` and process
restart, nice4iot will find and load it automatically.

## The `register(app)` entry point

`extensions/<name>/__init__.py` (or any submodule reachable from it) must
define:

```python
from fastapi import FastAPI

def register(app: FastAPI) -> None:
    ...
```

nice4iot calls `register(app)` once per installed extension at startup,
before it starts serving requests. This is the one place where you wire
up everything else described below — mount routers, register UI cards and
tabs, subscribe to MQTT topics, register event callbacks.

`register(app)` only declares what your extension *can* do — it runs once
globally, not per project. Whether any of it actually fires for a given
project is decided by activation (next section).

Errors are **fail-fast**: a missing `register()` function, an exception
raised inside it, or an invalid `register_*()` call (wrong section, missing
title, bad MQTT qos/suffix, ...) aborts nice4iot startup with a clear error
naming your extension. A broken extension should be fixed or uninstalled,
not silently skipped.

## Activation

Every extension is **disabled by default** for every project. A project
admin turns it on from the project's General tab → **Extensions** card,
which lists every installed (i.e. discovered) extension with a switch.

There is no `register()`/`deregister()` per project — that would require
extensions to symmetrically undo everything they registered, which is
fragile, and REST routes / MQTT subscriptions can't be cleanly unmounted
at runtime anyway. Instead, nice4iot filters centrally at the point of
use:

- **Cards, tabs, the device-provisioned callback** already receive
  `project_name` — nice4iot checks activation before calling your code.
  You don't write any enablement check yourself.
- **REST and MQTT** are mounted/subscribed globally at startup (they have
  to be — routes and subscriptions aren't per-project resources), so
  nice4iot instead requires your topics and routes to *contain* the
  project name in a fixed, predictable place, so it can extract it and
  check activation before your handler runs. See the REST and MQTT
  sections below for the exact shape.

## REST API

Build a normal `APIRouter`, but mount it with `mount_extension_router()`
instead of `app.include_router()` directly:

```python
from fastapi import APIRouter, FastAPI
from app.extensions import mount_extension_router

router = APIRouter()

@router.get("/{project_name}/screens/{screen_id}/image.png")
async def get_image(project_name: str, screen_id: str):
    ...

def register(app: FastAPI) -> None:
    mount_extension_router(app, router)
```

`mount_extension_router` mounts the router under `/api/ext/<extension_name>`
(so the route above becomes
`/api/ext/epaper/{project_name}/screens/{screen_id}/image.png`) and adds a
dependency that 404s the request when the extension is disabled for
`project_name` — before your handler runs. **Every route in the router
must declare `project_name` as a path parameter**; a route that doesn't
raises `RuntimeError` at request time (a loud failure, not a silent
bypass).

### Authenticating the caller

By itself, `mount_extension_router` only gates on *enablement* — it checks
that the extension is switched on for the project, **not who is calling.**
The example above is therefore open to anyone who can reach the URL. Decide
who the caller is and secure it accordingly:

- **Called by a device** (the common case — e.g. a display fetching its
  image): pass `require_device_auth=True`. Every request must then carry a
  valid device bearer token (`Authorization: Bearer <token>`), validated by
  the same `device_auth` dependency the built-in device endpoints use;
  missing / invalid / expired tokens get 401. This requires every route to
  also carry a `device_name` path parameter (the token is checked against
  `project_name`/`device_name`), enforced at mount time:

  ```python
  @router.get("/{project_name}/{device_name}/screens/{screen_id}/image.png")
  async def get_image(project_name: str, device_name: str, screen_id: str):
      ...

  def register(app: FastAPI) -> None:
      mount_extension_router(app, router, require_device_auth=True)
  ```

- **Called by the logged-in operator's browser** (e.g. an extension tab's own
  `fetch`): that request rides the UI session, not a device token, so
  `require_device_auth` is the wrong tool — leave it off. The UI auth
  (`AUTH_PROVIDER`) already guards who reaches the app, and the enablement
  gate covers the rest.

- **Custom scheme**: add your own FastAPI dependency to the router or its
  routes as usual.

If you genuinely need a route with no project scope (rare), mount it with
plain `app.include_router()` instead — it then bypasses activation
entirely, so make sure that's actually what you want.

## UI: cards and tabs

Import these from `app.extensions`:

```python
from app.extensions import (
    register_project_card, register_device_card,
    register_project_tab, register_device_tab,
)
```

### Cards

Cards render inside the existing **Dashboard** or **General** tab of a
project or device page, alongside the built-in cards. The two sections
have different conventions:

```python
def register_project_card(section: Literal['dashboard', 'general'],
                           render_fn: Callable[[str], None], *,
                           title: str | None = None) -> None: ...

def register_device_card(section: Literal['dashboard', 'general'],
                          render_fn: Callable[[str, str], None], *,
                          title: str | None = None) -> None: ...
```

**`'dashboard'`** cards are compact, always-visible summaries. `render_fn`
is called with `(project_name)` or `(project_name, device_name)` while
nicegui is already building the surrounding `ui.grid()` — create your own
`ui.card()` inside it, and don't pass `title=`:

```python
def _epaper_status_card(project_name: str) -> None:
    with ui.card().classes('w-full'):
        ui.label('E-Paper Displays')
        ...

def register(app):
    register_project_card('dashboard', _epaper_status_card)
```

**`'general'`** cards are settings sections and must look uniform with the
built-in ones (MQTT, Forwarding, Telemetry, ...): nice4iot renders the
card and its foldable header itself, using the required `title=` —
`render_fn` renders only the fields, no wrapping `ui.card()`/
`ui.expansion()`:

```python
def _epaper_settings_card(project_name: str) -> None:
    ui.label('Some description').classes('text-caption')
    ...

def register(app):
    register_project_card('general', _epaper_settings_card, title='E-Paper')
```

`render_fn` may be a regular function or an `async def` — both are
supported. The card simply isn't rendered for projects where your
extension is disabled; nothing to check yourself.

### Global config card

Some settings aren't per-project at all — a global API key, a shared
broker connection, etc. (nice4iot's own MQTT broker settings are exactly
this kind of card). For that, register a project-independent card:

```python
from app.extensions import register_global_card

def _epaper_global_card() -> None:
    ui.label('Some description').classes('text-caption')
    ...

def register(app):
    register_global_card('E-Paper', _epaper_global_card)
```

Same convention as a `'general'` project/device card: nice4iot renders the
card and foldable header for you using `title`, so `render_fn` should not
create its own `ui.card()`/`ui.expansion()`. It's rendered once, on the
Projects overview page, alongside the built-in MQTT broker card, and is
**not** gated by per-project enablement — there is no project to check, so
it renders as soon as your extension is installed, regardless of whether
any project has turned it on. `render_fn()` takes no arguments and may be
sync or async.

### Tabs

Tabs add a whole new tab next to the built-in ones (Dashboard, General,
...). They are addressed through the existing `?tab=<label>` deep-link
query parameter — there is no separate routing mechanism:

```python
def register_project_tab(label: str, render_fn: Callable[[str], Any]) -> None: ...
def register_device_tab(label: str, render_fn: Callable[[str, str], Any]) -> None: ...
```

`render_fn` receives the same arguments as a card's `render_fn` and is
expected to build the full tab content (it runs inside the page's
`ui.tab_panel(...)`). Like cards, the tab simply doesn't appear when your
extension is disabled for that project.

Because tabs are addressed by label, pick labels that don't collide with
the built-in ones (Dashboard, General, Provisioning, Files, Devices, Data,
Logs, Alarms) — a duplicate label would make the `?tab=` deep link
ambiguous. nice4iot doesn't enforce this; collisions only surface visually.

## Standalone project pages

Cards and tabs render *inside* nice4iot's normal project page. Sometimes
you want the opposite — a dedicated, simplified UI at its own URL, e.g.
for a kiosk display or wall tablet that shouldn't look like the admin
tool at all:

```python
from app.extensions import register_project_page

async def _kiosk_view(project_name: str) -> None:
    ui.label(f'Screens for {project_name}')
    # full control: no nice4iot header, breadcrumb, or user menu here

def register(app):
    register_project_page(_kiosk_view)
```

This serves at `/<project_name>/ext/<extension_name>` (get the URL with
`app.routes.project_extension_url(project_name, extension_name)` — handy
for linking to it from one of your own cards). `render_fn` owns the
**entire** page; nice4iot renders nothing around it. There is no
mandatory "back to nice4iot" link — add one yourself with
`app.routes.project_url(project_name)` if you want one, e.g. as a small
link in the corner.

Login and per-project enablement are still enforced before `render_fn`
runs, same as everywhere else — nothing to check yourself. Only one
standalone page per extension; calling `register_project_page` twice
raises `RuntimeError`.

## MQTT

Import from `app.mqtt.backend`:

```python
from app.mqtt.backend import mqtt_publish, register_topic_handler
```

```python
async def mqtt_publish(topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None: ...

def register_topic_handler(suffix: str,
                            handler: Callable[[str, str, bytes], Awaitable[None]],
                            qos: int = 0) -> None: ...
```

`register_topic_handler` subscribes to
`ext/<extension_name>/<project>/<suffix>` — nice4iot builds the
`ext/<extension_name>/` prefix and wildcards the project segment for you;
you only choose `suffix` (which may itself use MQTT wildcards `+`/`#` for
its own sub-hierarchy, e.g. `screens/+/status`) and, optionally, the
subscription `qos` (0, 1, or 2; default 0). An empty suffix, a suffix
starting with `/`, or an invalid qos raises `ValueError` at registration
time. `handler(project_name,
topic, payload)` is awaited for every incoming message that matches, but
**only when the extension is enabled for `project_name`** — nice4iot
extracts the project from the topic and checks activation before calling
you, same as the REST dependency does.

```python
async def _on_status(project_name: str, topic: str, payload: bytes) -> None:
    logger.info(f"epaper status for {project_name}: {topic} = {payload!r}")

def register(app):
    register_topic_handler('status', _on_status)  # subscribes ext/epaper/+/status
```

`mqtt_publish(topic, payload, ...)` is a plain outbound primitive, not
subject to this scheme — publish to whatever topic your device firmware
expects (commonly the same `ext/<extension_name>/<project>/...` shape, but
that's your choice, nice4iot doesn't enforce it for outbound messages). If
nice4iot has no active broker connection, `mqtt_publish` logs a warning
and drops the message rather than raising — the same behavior as the
built-in file-publish path.

## Events: new device provisioned

```python
from app.extensions import register_device_provisioned_callback
from app.core.device.models import Device

def _on_new_device(device: Device) -> None:
    ...

def register(app):
    register_device_provisioned_callback(_on_new_device)
```

The callback fires for every newly created device — auto-provisioned via
MQTT, auto-provisioned via the HTTP provisioning API, *and* devices added
manually through the UI — but only when your extension is enabled for
`device.project_name`; nice4iot checks that before calling you. If you
only care about one of the creation paths, branch on `device` fields
yourself (there is no separate hook per path). Exceptions raised by a
callback are logged and do not prevent the device from being created or
affect other callbacks.

**The callback must be synchronous.** `create_device()` is a synchronous
backend function that commonly runs in a worker thread
(`anyio.to_thread.run_sync`), where there is no running event loop to
schedule async work on. If you need to do async work in response (e.g. an
HTTP call), hand it off to your own background task/queue instead of
awaiting it inline.

## Per-project file storage

If your extension needs to persist its own files within a project, use:

```python
from app.paths import extension_project_dir

dir = extension_project_dir(project_name, 'epaper')  # <project>/.epaper/
dir.mkdir(exist_ok=True)
```

Mirrors `project_dir`/`device_dir` — it only computes and validates the
path (raising `ValueError` for an invalid project or extension name), you
create the directory yourself.

## Worked example

```python
# extensions/epaper/__init__.py
from typing import Any
from fastapi import APIRouter, FastAPI
from nicegui import ui

from app.extensions import (
    mount_extension_router, register_project_card, register_global_card,
    register_project_tab, register_project_page, register_device_provisioned_callback,
)
from app.mqtt.backend import register_topic_handler
from app.paths import extension_project_dir
from app.core.device.models import Device
from app.util import logger

router = APIRouter()

@router.get("/{project_name}/ping")
async def ping(project_name: str):
    return {"status": "ok"}

def _dashboard_card(project_name: str) -> None:
    with ui.card().classes('w-full'):
        ui.label('E-Paper Displays')

def _global_card() -> None:
    ui.label('E-Paper Global Settings').classes('text-caption')

async def _screens_tab(project_name: str) -> Any:
    ui.label(f'Screens for {project_name}')

async def _kiosk_view(project_name: str) -> None:
    ui.label(f'Screens for {project_name}')  # no nice4iot header/nav around this

async def _on_status(project_name: str, topic: str, payload: bytes) -> None:
    logger.info(f"epaper status for {project_name}: {topic} = {payload!r}")

def _on_new_device(device: Device) -> None:
    dir = extension_project_dir(device.project_name, 'epaper')
    dir.mkdir(exist_ok=True)
    logger.info(f"epaper: new device {device.project_name}/{device.name}")

def register(app: FastAPI) -> None:
    mount_extension_router(app, router)
    register_project_card('dashboard', _dashboard_card)
    register_global_card('E-Paper', _global_card)
    register_project_tab('E-Paper', _screens_tab)
    register_project_page(_kiosk_view)  # /<project_name>/ext/epaper
    register_topic_handler('status', _on_status)  # ext/epaper/+/status
    register_device_provisioned_callback(_on_new_device)
```
