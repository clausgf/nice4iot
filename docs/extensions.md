# Writing nice4iot extensions

nice4iot can be extended by separately versioned Python packages that add
their own REST endpoints, MQTT publish/subscribe, and UI elements (cards
and tabs on the project and device pages), and that get notified when a
new device is provisioned.

An extension is a normal `uv`/pip dependency — there is no plugin config
file and no separate "enable this extension" setting. Installing the
package *is* enabling it.

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

## REST API

Extensions own their FastAPI routing directly — there is no separate REST
registry. Build an `APIRouter` and mount it yourself:

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/screens/{screen_id}/image.png")
async def get_image(screen_id: str):
    ...

def register(app):
    app.include_router(router, prefix="/api/epaper")
```

Nothing prevents you from also exposing a NiceGUI page directly on `app`
if you need routes outside the card/tab mechanism below, but prefer the
card/tab APIs for anything meant to appear inside the normal project/device
navigation.

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
project or device page, alongside the built-in cards:

```python
def register_project_card(section: Literal['dashboard', 'general'],
                           render_fn: Callable[[str], None]) -> None: ...

def register_device_card(section: Literal['dashboard', 'general'],
                          render_fn: Callable[[str, str], None]) -> None: ...
```

`render_fn` is called with `(project_name)` or `(project_name,
device_name)` while nicegui is already building the surrounding
`ui.grid()` — just create your own `ui.card()` inside it:

```python
def _epaper_status_card(project_name: str) -> None:
    with ui.card().classes('w-full'):
        ui.label('E-Paper Displays')
        ...

def register(app):
    register_project_card('dashboard', _epaper_status_card)
```

`render_fn` may be a regular function or an `async def` — both are
supported.

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
`ui.tab_panel(...)`).

## MQTT

Import from `app.mqtt.backend`:

```python
from app.mqtt.backend import mqtt_publish, register_topic_handler
```

Two primitives, deliberately independent of nice4iot's own project/device
topic scheme — your extension can use any topic layout it likes:

```python
async def mqtt_publish(topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None: ...

def register_topic_handler(topic_filter: str,
                            handler: Callable[[str, bytes], Awaitable[None]]) -> None: ...
```

`topic_filter` uses standard MQTT wildcards (`+` for one level, `#` for
the rest), e.g. `epaper/+/status`. `handler` is awaited for every incoming
message whose topic matches the filter, with the message's full topic and
raw payload.

```python
async def _on_status(topic: str, payload: bytes) -> None:
    logger.info(f"epaper status: {topic} = {payload!r}")

def register(app):
    register_topic_handler('epaper/+/status', _on_status)
```

If nice4iot has no active broker connection, `mqtt_publish` logs a warning
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
manually through the UI. If you only care about one of those paths,
branch on `device` fields yourself (there is no separate hook per path).
Exceptions raised by a callback are logged and do not prevent the device
from being created or affect other callbacks.

**The callback must be synchronous.** `create_device()` is a synchronous
backend function that commonly runs in a worker thread
(`anyio.to_thread.run_sync`), where there is no running event loop to
schedule async work on. If you need to do async work in response (e.g. an
HTTP call), hand it off to your own background task/queue instead of
awaiting it inline.

## Worked example

```python
# extensions/epaper/__init__.py
from typing import Any
from fastapi import APIRouter, FastAPI
from nicegui import ui

from app.extensions import register_project_card, register_project_tab, register_device_provisioned_callback
from app.mqtt.backend import register_topic_handler
from app.core.device.models import Device
from app.util import logger

router = APIRouter()

@router.get("/ping")
async def ping():
    return {"status": "ok"}

def _dashboard_card(project_name: str) -> None:
    with ui.card().classes('w-full'):
        ui.label('E-Paper Displays')

async def _screens_tab(project_name: str) -> Any:
    ui.label(f'Screens for {project_name}')

async def _on_status(topic: str, payload: bytes) -> None:
    logger.info(f"epaper status: {topic} = {payload!r}")

def _on_new_device(device: Device) -> None:
    logger.info(f"epaper: new device {device.project_name}/{device.name}")

def register(app: FastAPI) -> None:
    app.include_router(router, prefix="/api/epaper")
    register_project_card('dashboard', _dashboard_card)
    register_project_tab('E-Paper', _screens_tab)
    register_topic_handler('epaper/+/status', _on_status)
    register_device_provisioned_callback(_on_new_device)
```
