import asyncio
import signal
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from nicegui import app as nicegui_app, ui
import niceview

from app.config import app_config
from app.util import app_version
from app.sbom import app_commit_date, app_revision

# Build identity, resolved once at startup (git may fork on a source run) and
# surfaced on /health for deployment verification and monitoring.
_BUILD_INFO = {
    "version": app_version(),
    "commit": app_revision(),
    "commit_date": app_commit_date(),
}
from app.api.provisioning import router as provisioning_router
from app.api.device import router as device_router
from app.api.file import router as file_router

import app.frontend as frontend  # noqa: F401  (side-effect import: registers @ui.page routes)


def _configure_logging() -> None:
    """Configure standard log format with timestamp, level, logger name, and message."""
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.root.setLevel(logging.INFO)
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        log_obj = logging.getLogger(logger_name)
        for handler in log_obj.handlers:
            handler.setFormatter(formatter)
    if not logging.root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)


_configure_logging()
_main_log = logging.getLogger("uvicorn")


def _on_sigusr1(signum, frame) -> None:
    """Flush all in-process caches. Useful after out-of-band filesystem changes.

    Usage: kill -USR1 <pid>
    """
    from app.core.device.backend import flush_device_list_cache
    from app.core.telemetry.backend import flush_telemetry_backend_cache
    flush_device_list_cache()
    flush_telemetry_backend_cache()
    _main_log.info("SIGUSR1: all in-process caches flushed")


signal.signal(signal.SIGUSR1, _on_sigusr1)


async def _mqtt_loop_wrapper() -> None:
    from app.mqtt.backend import mqtt_main_loop
    await mqtt_main_loop()


async def _alarm_check_loop() -> None:
    """Periodically evaluate the built-in alarm rules (device offline, token expiry)."""
    import anyio
    while True:
        await asyncio.sleep(60)
        try:
            from app.core.project.backend import get_projects
            from app.core.alarm.backend import (
                evaluate_device_offline, evaluate_provisioning_expiry, prune_alarms_for_deleted_devices,
            )
            projects = await anyio.to_thread.run_sync(get_projects)
            for project in projects:
                await anyio.to_thread.run_sync(
                    lambda pn=project.name: prune_alarms_for_deleted_devices(pn)
                )
                await anyio.to_thread.run_sync(
                    lambda pn=project.name: evaluate_device_offline(pn)
                )
                await anyio.to_thread.run_sync(
                    lambda pn=project.name: evaluate_provisioning_expiry(pn)
                )
        except Exception as e:
            _main_log.error(f"alarm_check_loop error: {e}")


async def _firmware_auto_pull_loop() -> None:
    """Periodically pull firmware for sources with auto-pull enabled (per-source
    interval and conditional ETag requests keep this cheap)."""
    while True:
        await asyncio.sleep(60)
        try:
            from app.core.firmware.backend import auto_pull_tick
            await auto_pull_tick()
        except Exception as e:
            _main_log.error(f"firmware_auto_pull_loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    # Register callbacks to wire up MQTT ↔ file-backend without circular imports
    from app.core.file.backend import register_publish_callback, file_watcher_loop
    from app.mqtt.backend import publish_file, register_file_publish_callback

    register_publish_callback(publish_file)
    # Upload notifications from MQTT → file backend: no-op (upload = device→server,
    # no re-publish needed; state is updated by the watcher loop).
    register_file_publish_callback(lambda *args, **kwargs: None)

    # Start background tasks
    mqtt_task = asyncio.create_task(_mqtt_loop_wrapper())
    watcher_task = asyncio.create_task(file_watcher_loop())
    alarm_task = asyncio.create_task(_alarm_check_loop())
    firmware_task = asyncio.create_task(_firmware_auto_pull_loop())

    yield

    for task in (mqtt_task, watcher_task, alarm_task, firmware_task):
        task.cancel()
    for task in (mqtt_task, watcher_task, alarm_task, firmware_task):
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan, title="nice4iot", version=app_version())

_cors_origins = app_config.cors_allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # The CORS spec forbids combining a wildcard origin with credentials (the
    # browser ignores it), so only allow credentials once origins are restricted.
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root(request: Request):
    # The UI lives under /ui; the bare root just redirects there. Honours a
    # reverse-proxy root_path so it works when served under a sub-path too.
    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/ui")


@app.get("/health")
async def health():
    return {"status": "ok", **_BUILD_INFO}


app.include_router(provisioning_router, prefix='/api', tags=['provisioning'])
app.include_router(device_router, prefix='/api', tags=['device'])
app.include_router(file_router, prefix='/api', tags=['file'])
# doc endpoint generated by FastAPI

# Discover and register extensions (see docs/extensions.md). extensions.*
# is a PEP 420 namespace package: each installed extension contributes its
# own extensions/<name>/ submodule, found here by walking the namespace.
import importlib
import pkgutil
from app.extensions import registering as _registering
try:
    import extensions as _extensions_ns
    _ext_paths = _extensions_ns.__path__
    _ext_prefix = _extensions_ns.__name__ + '.'
except ModuleNotFoundError:
    # No extension installed and no extensions/ directory on the path: a
    # namespace package with no members simply does not exist. That is the
    # normal case for a plain install, not an error.
    _ext_paths, _ext_prefix = [], 'extensions.'
for _, _ext_module_name, _ in pkgutil.iter_modules(_ext_paths, _ext_prefix):
    _ext_module = importlib.import_module(_ext_module_name)
    _ext_name = _ext_module_name.removeprefix(_extensions_ns.__name__ + '.')
    if not hasattr(_ext_module, 'register'):
        # Deliberately fail-fast (like any other register() error): a broken
        # extension should be fixed or uninstalled, not silently skipped.
        raise RuntimeError(
            f"extension module {_ext_module_name!r} has no register(app) function "
            f"(see docs/extensions.md)"
        )
    with _registering(_ext_name):
        _ext_module.register(app)
    _main_log.info(f"Registered extension {_ext_module_name!r}")

# Fence the device-API namespace. NiceGUI's ui.run_with (below) mounts the UI
# as a catch-all sub-app at '/', so any request under /api/* that no real route
# above answered — an unknown path, or a wrong HTTP method on a known path —
# would otherwise fall through to the UI and receive an HTML page instead of a
# JSON error. Devices must always see JSON on /api/*, and the two auth domains
# must stay separate (see SECURITY.md). Registered after the API routers and
# every extension route, so those still win on an exact method+path match; this
# only catches the leftovers. Regression-tested in tests/test_api_namespace.py.
@app.api_route('/api/{_path:path}', include_in_schema=False,
               methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
async def _api_not_found(_path: str):
    raise HTTPException(status_code=404, detail='Not Found')

# niceview styles only the chrome it draws itself; "every button of this app looks
# like that" is NiceGUI's own default_props. The icon shape is the one thing the
# chrome has to be told: an icon-only chrome button is round here.
niceview.set_chrome_style(toolbar_icon_button_props='dense round')
niceview.set_chrome_style(form_icon_button_props='dense flat')
niceview.set_chrome_style(button_group=False)
niceview.set_chrome_style(form_row_classes='w-full items-center gap-2')
niceview.set_field_style(default_classes='w-full')
niceview.set_field_style(input_props='dense outlined hide-bottom-space')

# Vendored esp-web-tools JS for the Web-Serial-Flash dialog (app.core.seed.action_dialogs)
# — see app/static/esp-web-tools/README.md. Non-security-critical, served unauthenticated.
nicegui_app.add_static_files('/static/esp-web-tools', 'app/static/esp-web-tools')

ui.run_with(app, title="nice4iot", storage_secret=app_config.nicegui_storage_secret)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
