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

Cards render inside the existing **Dashboard**, or the settings area, of a
project or device page, alongside the built-in cards — a project's
**Project Settings** sidebar group and a device's **Device {id} Settings**
sidebar group, each its own child page per card. The two sections have
the same conventions:

```python
def register_project_card(section: Literal['dashboard', 'settings'],
                           render_fn: Callable[[str], None], *,
                           title: str | None = None) -> None: ...

def register_device_card(section: Literal['dashboard', 'settings'],
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

**`'settings'`** cards are settings sections and must look uniform with the
built-in ones (MQTT, Forwarding, Telemetry, ...): nice4iot renders the
card and its foldable header itself, using the required `title=` —
`render_fn` renders only the fields, no wrapping `ui.card()`/
`ui.expansion()`:

```python
def _epaper_settings_card(project_name: str) -> None:
    ui.label('Some description').classes('text-caption')
    ...

def register(app):
    register_project_card('settings', _epaper_settings_card, title='E-Paper')
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

Same convention as a `'settings'` project/device card: nice4iot renders the
card and foldable header for you using `title`, so `render_fn` should not
create its own `ui.card()`/`ui.expansion()`. It's rendered once, on the
Projects overview page, alongside the built-in MQTT broker card, and is
**not** gated by per-project enablement — there is no project to check, so
it renders as soon as your extension is installed, regardless of whether
any project has turned it on. `render_fn()` takes no arguments and may be
sync or async.

### User menu item

Extensions can add their own entry to the top-right user menu (the
person-icon dropdown), next to *Preferences*, *About*, etc.:

```python
from nicegui import ui
from app.extensions import register_user_menu_item

def register(app):
    register_user_menu_item('Screens', lambda: ui.navigate.to('/ext/epaper'),
                            icon='tv')
```

nice4iot renders the uniform menu-item chrome (`icon` optional) and calls
`on_click` when the entry is selected — use `ui.navigate.to(...)` inside it
to link somewhere, or do anything else NiceGUI allows. Like the global card,
it is project-independent and **not** gated by per-project enablement: the
user menu belongs to no project, so the entry appears as soon as your
extension is installed. `on_click` may be sync or async.

A [standalone project page](#standalone-project-pages) builds its own page
chrome, so it doesn't get the built-in header (and its user menu) for free.
To drop the *whole* standard user menu — Home, Preferences, dark mode, About,
and every registered extension item — into your own layout, call
`render_user_menu()`:

```python
from nicegui import ui
from app.extensions import render_user_menu

def _my_page(project_name: str) -> None:
    with ui.header().classes('items-center'):
        ui.label('My Extension')
        ui.space()
        render_user_menu()   # the same person-icon dropdown as the main app
    ...
```

It builds a single `ui.button` holding the menu, so it fits wherever a button
fits. The menu's first entry is a **Home** link back to the 4IoT entry page
(the projects overview), rendered before your extension's own items.

### Tabs

Tabs add a whole new section next to the built-in ones. A **project** tab
becomes a row in the project page's left sidebar, nested under a group named
after your extension (alongside every other tab your extension registers, in
registration order — each extension gets its own group, so several enabled
extensions don't turn the sidebar into one long flat list), addressed by its
own URL segment. A **device** tab becomes a row in the device page's sidebar
too — its own URL segment, appended flat after the built-in sections under
the device's "Device {id}" group (device tabs aren't grouped by extension the
way project tabs are, since a device usually has at most a couple):

```python
def register_project_tab(label: str, render_fn: Callable[[str], Any], *,
                         icon: str = 'extension') -> None: ...
def register_device_tab(label: str, render_fn: Callable[[str, str], Any], *,
                        icon: str = 'extension') -> None: ...
```

`render_fn` receives the same arguments as a card's `render_fn` and is
expected to build the full section's content. Like cards, the tab simply
doesn't appear when your extension is disabled for that project. `icon` is
a Material icon name — a project tab's sidebar row always shows one (default
`'extension'` if you don't have a more fitting choice); a device tab shows
it next to its label the same way the built-in tabs do.

**Naming the group.** A project tab's group header defaults to your
extension's directory/module name (e.g. `epaper`). To show something nicer,
register a label/icon for the group itself, once, from anywhere in
`register(app)`:

```python
from app.extensions import register_extension_group

def register(app):
    register_extension_group('E-Paper', icon='tv')
    register_project_tab('Rooms', _rooms_tab, icon='meeting_room')
    register_project_tab('Screens', _screens_tab, icon='wallpaper')
```

Both tabs above still nest under one group (their shared extension name), now
titled "E-Paper" with a `tv` icon instead of the default. Only meaningful for
extensions that register at least one project tab — that's what creates the
group in the first place; a device tab's row isn't grouped this way (see
above), so it's unaffected.

A project tab's URL is `.../project/<id>/tab/<slug>`; a device tab's is
`.../project/<id>/device/<id>/<slug>` — same slugifying (your label
lowercased, anything that isn't `[a-z0-9]` collapsed to a single `-`,
`'E-Paper'` → `'e-paper'`). Pick a label that slugifies to something
distinct from your other tabs and — for a device tab — from the built-in
device sections (`dashboard`, `general`, `files`, `data`, `logs`); nice4iot
doesn't enforce uniqueness, a collision only surfaces visually (two rows
opening the same URL).

**Deep-linkable views inside a tab or card.** A tab/card's own content can
have more than one "screen" of its own — e.g. a list view and a detail
view — addressable by URL, not just by clicking around. Add a trailing
parameter annotated `PageArguments` and nice4iot passes it in:

```python
from nicegui import PageArguments, ui

def _screens_tab(project_name: str, args: PageArguments) -> None:
    ui.sub_pages({
        '/': _screen_list,
        '/{screen_id}': _screen_detail,
    })
```

Your tab already runs inside nice4iot's own `ui.sub_pages`, so a nested
`ui.sub_pages(...)` you create here derives its `root_path` automatically
from the enclosing one — no URL bookkeeping on your side. This is the same
convention `ui.sub_pages` route builders use themselves (see nicegui's own
`PageArguments` docs); `render_fn` without the parameter keeps working
exactly as before, so adding it later is not a breaking change.

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

This serves at `/ui/project/<project_name>/ext/<extension_name>` (get the URL with
`app.routes.project_extension_url(project_name, extension_name)` — handy
for linking to it from one of your own cards). `render_fn` owns the
**entire** page; nice4iot renders nothing around it. There is no
mandatory "back to nice4iot" link — add one yourself with
`app.routes.project_url(project_name)`.

Login and per-project enablement are still enforced before `render_fn`
runs, same as everywhere else — nothing to check yourself. Only one
standalone page per extension; calling `register_project_page` twice
raises `RuntimeError`.

**Deep links within a standalone page.** nice4iot routes every path under
`/ext/<extension_name>/...` to your `render_fn`, not just the bare URL — so
for a kiosk UI with more than one screen, build your own routing inside it
with `ui.sub_pages`, passing `root_path` explicitly (there is no
nice4iot-provided `ui.sub_pages` to nest under here, unlike a tab — this
page is rendered before nice4iot's own is even created):

```python
from nicegui import ui
from app.extensions import register_project_page
from app.routes import project_extension_url

async def _kiosk_view(project_name: str) -> None:
    ui.sub_pages({
        '/': _screen_list,
        '/screens/{screen_id}': _screen_detail,
    }, root_path=project_extension_url(project_name, 'epaper'))

def register(app):
    register_project_page(_kiosk_view)
```

`/ui/project/<project_name>/ext/epaper/screens/5` now reaches
`_screen_detail(screen_id='5')` — bookmarkable and shareable, same as any
other nice4iot URL.

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

## Telemetry: caching your own kind in the runtime sidecar

`kind='system'` telemetry pushes (arduino4iot's `postSystemTelemetry`) are
reserved for nice4iot's own battery/RSSI/firmware fields and snapshotted
into the device runtime sidecar for O(1) access (see the *System-telemetry
snapshot* section in `docs/concepts.md`). Send your extension's own
application telemetry under your own `kind` instead — never `system` — and
opt that kind into the same caching mechanism if you want O(1) reads of its
latest numerics/labels (e.g. one value per row in a device table) instead of
scanning `.device_metrics.jsonl`:

```python
from app.extensions import register_telemetry_cache_kind

def register(app):
    register_telemetry_cache_kind('epaper')
```

```python
from app.core.device.backend import read_runtime

rt = read_runtime(project_name, device_name)
panel = rt.kind_labels.get('epaper', {}).get('panel')
```

Every push of your registered kind (`postTelemetry("epaper", ...)`) replaces
`rt.kind_metrics['epaper']`/`rt.kind_labels['epaper']`/
`rt.kind_reported_at['epaper']` wholesale, the same replace-on-each-push
semantics as the built-in `system` snapshot — capped at 32 metrics per kind.
Caching only takes effect while your extension is enabled for the device's
project; otherwise the push still reaches the configured telemetry backend
and the local JSONL store as normal, just without the sidecar snapshot.

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
    register_extension_group,
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
    register_extension_group('E-Paper', icon='tv')
    register_project_tab('E-Paper', _screens_tab)
    register_project_page(_kiosk_view)  # /ui/project/<project_name>/ext/epaper
    register_topic_handler('status', _on_status)  # ext/epaper/+/status
    register_device_provisioned_callback(_on_new_device)
```
