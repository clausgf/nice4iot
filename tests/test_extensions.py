"""
Unit tests for the extension mechanism (see docs/extensions.md):
- app.extensions registries, registering() context, per-project enablement
- app.core.device.backend.create_device() firing the device-provisioned hook
- app.mqtt.backend extension topic scheme (ext/<name>/<project>/<suffix>) and mqtt_publish()
- app.paths.extension_project_dir()
- app.extensions.mount_extension_router() REST gating
"""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import app.extensions as extensions
import app.mqtt.backend as mqtt_backend
from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.project.backend import create_project, project_adapter
from app.extensions import (
    get_device_cards,
    get_device_tabs,
    get_project_cards,
    get_project_tabs,
    get_registered_extension_names,
    is_extension_enabled,
    mount_extension_router,
    register_device_card,
    register_device_provisioned_callback,
    register_device_tab,
    register_project_card,
    register_project_tab,
    registering,
)
from app.mqtt.backend import (
    _dispatch_extension_topic,
    _extension_topic_pattern,
    mqtt_publish,
    register_topic_handler,
)
from app.paths import extension_project_dir, project_dir


@pytest.fixture(autouse=True)
def clear_extension_registries():
    yield
    extensions._clear_registries()
    mqtt_backend._extension_topic_handlers.clear()


@pytest.fixture
def project(projects_dir):
    create_project("proj")
    return "proj"


def _enable(project_name: str, extension_name: str) -> None:
    adapter = project_adapter(project_name)
    p = adapter.read()
    p.enabled_extensions.append(extension_name)
    adapter.save(p)


# ---------------------------------------------------------------------------
# registering() / extension identity
# ---------------------------------------------------------------------------

def test_registering_sets_and_resets_current_extension():
    assert extensions._current_extension.get() is None
    with registering('testext'):
        assert extensions._current_extension.get() == 'testext'
    assert extensions._current_extension.get() is None


def test_registering_tracks_name_even_with_empty_register():
    with registering('noop'):
        pass
    assert get_registered_extension_names() == ['noop']


def test_register_outside_context_raises():
    with pytest.raises(RuntimeError):
        register_project_card('dashboard', lambda project_name: None)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def test_project_card_only_returned_when_enabled(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_card('dashboard', fn)

    assert get_project_cards('dashboard', project) == []
    _enable(project, 'ext1')
    assert get_project_cards('dashboard', project) == [fn]
    assert get_project_cards('general', project) == []


def test_device_card_only_returned_when_enabled(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_card('general', fn)

    assert get_device_cards('general', project) == []
    _enable(project, 'ext1')
    assert get_device_cards('general', project) == [fn]


def test_get_project_cards_returns_a_copy(project):
    with registering('ext1'):
        register_project_card('dashboard', lambda project_name: None)
    _enable(project, 'ext1')

    cards = get_project_cards('dashboard', project)
    cards.append(lambda project_name: None)
    assert len(get_project_cards('dashboard', project)) == 1


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def test_project_tab_only_returned_when_enabled(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_tab('Extra', fn)

    assert get_project_tabs(project) == []
    _enable(project, 'ext1')
    assert get_project_tabs(project) == [('Extra', fn)]


def test_device_tab_only_returned_when_enabled(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_tab('Extra', fn)

    assert get_device_tabs(project) == []
    _enable(project, 'ext1')
    assert get_device_tabs(project) == [('Extra', fn)]


# ---------------------------------------------------------------------------
# is_extension_enabled
# ---------------------------------------------------------------------------

def test_is_extension_enabled_false_by_default(project):
    assert is_extension_enabled(project, 'ext1') is False


def test_is_extension_enabled_true_after_enabling(project):
    _enable(project, 'ext1')
    assert is_extension_enabled(project, 'ext1') is True


def test_is_extension_enabled_false_for_missing_project(projects_dir):
    assert is_extension_enabled('does-not-exist', 'ext1') is False


# ---------------------------------------------------------------------------
# Device-provisioned event
# ---------------------------------------------------------------------------

def test_device_provisioned_callback_fires_when_enabled(project):
    received = []
    with registering('ext1'):
        register_device_provisioned_callback(received.append)
    _enable(project, 'ext1')

    device = create_device(Device(name="dev1", project_name=project))

    assert len(received) == 1
    assert received[0].name == device.name


def test_device_provisioned_callback_silent_when_disabled(project):
    received = []
    with registering('ext1'):
        register_device_provisioned_callback(received.append)
    # not enabled

    create_device(Device(name="dev1", project_name=project))

    assert received == []


def test_device_provisioned_callback_error_does_not_prevent_creation(project):
    def bad_callback(device):
        raise RuntimeError("boom")

    with registering('ext1'):
        register_device_provisioned_callback(bad_callback)
    _enable(project, 'ext1')

    device = create_device(Device(name="dev1", project_name=project))

    assert device.name == "dev1"


def test_device_provisioned_callback_receives_multiple_registrations(project):
    calls = []
    with registering('ext1'):
        register_device_provisioned_callback(lambda d: calls.append('first'))
        register_device_provisioned_callback(lambda d: calls.append('second'))
    _enable(project, 'ext1')

    create_device(Device(name="dev1", project_name=project))

    assert calls == ['first', 'second']


# ---------------------------------------------------------------------------
# MQTT topic pattern
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("topic,extension_name,suffix,expected_project", [
    ("ext/epaper/proj1/status", "epaper", "status", "proj1"),
    ("ext/epaper/proj1/screens/foo/status", "epaper", "screens/+/status", "proj1"),
    ("ext/epaper/proj1/x/y", "epaper", "#", "proj1"),
    ("ext/other/proj1/status", "epaper", "status", None),
    ("ext/epaper/proj1/status/extra", "epaper", "status", None),
])
def test_extension_topic_pattern(topic, extension_name, suffix, expected_project):
    m = _extension_topic_pattern(extension_name, suffix).match(topic)
    if expected_project is None:
        assert m is None
    else:
        assert m.group('project') == expected_project


def test_register_topic_handler_stores_extension_and_suffix():
    async def handler(project_name, topic, payload):
        pass

    with registering('ext1'):
        register_topic_handler('status', handler)

    assert mqtt_backend._extension_topic_handlers == [('ext1', 'status', handler)]


# ---------------------------------------------------------------------------
# MQTT dispatch
# ---------------------------------------------------------------------------

def test_dispatch_extension_topic_calls_handler_when_enabled(project):
    calls = []

    async def handler(project_name, topic, payload):
        calls.append((project_name, topic, payload))

    with registering('ext1'):
        register_topic_handler('status', handler)
    _enable(project, 'ext1')

    matched = asyncio.run(_dispatch_extension_topic(f'ext/ext1/{project}/status', b'hi'))

    assert matched is True
    assert calls == [(project, f'ext/ext1/{project}/status', b'hi')]


def test_dispatch_extension_topic_skips_handler_when_disabled(project):
    calls = []

    async def handler(project_name, topic, payload):
        calls.append(1)

    with registering('ext1'):
        register_topic_handler('status', handler)
    # not enabled

    matched = asyncio.run(_dispatch_extension_topic(f'ext/ext1/{project}/status', b'hi'))

    assert matched is True  # pattern matched, just not enabled
    assert calls == []


def test_dispatch_extension_topic_no_match_returns_false():
    matched = asyncio.run(_dispatch_extension_topic('completely/unrelated/topic', b'hi'))
    assert matched is False


# ---------------------------------------------------------------------------
# mqtt_publish
# ---------------------------------------------------------------------------

def test_mqtt_publish_without_client_logs_and_noops(monkeypatch):
    monkeypatch.setattr(mqtt_backend, '_client', None)
    asyncio.run(mqtt_publish('foo/bar', b'payload'))  # must not raise


def test_mqtt_publish_calls_client_publish(monkeypatch):
    calls = []

    class StubClient:
        async def publish(self, topic, payload, qos, retain):
            calls.append((topic, payload, qos, retain))

    monkeypatch.setattr(mqtt_backend, '_client', StubClient())
    asyncio.run(mqtt_publish('foo/bar', b'payload', qos=1, retain=True))

    assert calls == [('foo/bar', b'payload', 1, True)]


# ---------------------------------------------------------------------------
# extension_project_dir
# ---------------------------------------------------------------------------

def test_extension_project_dir_path(project):
    path = extension_project_dir(project, 'epaper')
    assert path == project_dir(project) / '.epaper'


def test_extension_project_dir_invalid_name(project):
    with pytest.raises(ValueError):
        extension_project_dir(project, 'bad/name')


# ---------------------------------------------------------------------------
# mount_extension_router
# ---------------------------------------------------------------------------

def _make_ping_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{project_name}/ping")
    async def ping(project_name: str):
        return {"status": "ok"}

    return router


def test_mount_extension_router_enabled_returns_200(project):
    app = FastAPI()
    with registering('ext1'):
        mount_extension_router(app, _make_ping_router())
    _enable(project, 'ext1')

    client = TestClient(app)
    resp = client.get(f"/api/ext/ext1/{project}/ping")
    assert resp.status_code == 200


def test_mount_extension_router_disabled_returns_404(project):
    app = FastAPI()
    with registering('ext1'):
        mount_extension_router(app, _make_ping_router())
    # not enabled

    client = TestClient(app)
    resp = client.get(f"/api/ext/ext1/{project}/ping")
    assert resp.status_code == 404


def test_mount_extension_router_missing_project_returns_404(projects_dir):
    app = FastAPI()
    with registering('ext1'):
        mount_extension_router(app, _make_ping_router())

    client = TestClient(app)
    resp = client.get("/api/ext/ext1/does-not-exist/ping")
    assert resp.status_code == 404


def test_mount_extension_router_route_without_project_name_raises():
    router = APIRouter()

    @router.get("/ping")
    async def ping():
        return {"status": "ok"}

    app = FastAPI()
    with registering('ext1'):
        mount_extension_router(app, router)

    client = TestClient(app)
    with pytest.raises(RuntimeError):
        client.get("/api/ext/ext1/ping")
