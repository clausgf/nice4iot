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
    call_with_page_args,
    get_device_dashboard_cards,
    get_device_settings_cards,
    get_device_tabs,
    get_global_cards,
    get_project_dashboard_cards,
    get_project_settings_cards,
    get_project_page,
    get_project_tabs,
    get_registered_extension_names,
    get_user_menu_items,
    is_extension_enabled,
    mount_extension_router,
    register_device_card,
    register_device_provisioned_callback,
    register_device_tab,
    register_global_card,
    register_project_card,
    register_project_page,
    register_project_tab,
    register_telemetry_cache_kind,
    register_user_menu_item,
    registering,
    telemetry_cache_kind_enabled,
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

def test_project_dashboard_card_only_returned_when_enabled(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_card('dashboard', fn)

    assert get_project_dashboard_cards(project) == []
    _enable(project, 'ext1')
    assert get_project_dashboard_cards(project) == [fn]
    assert get_project_settings_cards(project) == []


def test_project_dashboard_card_rejects_title():
    with registering('ext1'):
        with pytest.raises(ValueError):
            register_project_card('dashboard', lambda project_name: None, title='Nope')


def test_project_settings_card_requires_title():
    with registering('ext1'):
        with pytest.raises(ValueError):
            register_project_card('settings', lambda project_name: None)


def test_register_card_unknown_section_raises():
    with registering('ext1'):
        with pytest.raises(ValueError):
            register_project_card('settngs', lambda project_name: None, title='Typo')
        with pytest.raises(ValueError):
            register_device_card('sidebar', lambda project_name, device_name: None)


def test_project_settings_card_only_returned_when_enabled(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_card('settings', fn, title='E-Paper')

    assert get_project_settings_cards(project) == []
    _enable(project, 'ext1')
    assert get_project_settings_cards(project) == [('E-Paper', fn)]


def test_device_dashboard_card_only_returned_when_enabled(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_card('dashboard', fn)

    assert get_device_dashboard_cards(project) == []
    _enable(project, 'ext1')
    assert get_device_dashboard_cards(project) == [fn]


def test_device_settings_card_only_returned_when_enabled(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_card('settings', fn, title='E-Paper')

    assert get_device_settings_cards(project) == []
    _enable(project, 'ext1')
    assert get_device_settings_cards(project) == [('E-Paper', fn)]


def test_device_settings_card_requires_title():
    with registering('ext1'):
        with pytest.raises(ValueError):
            register_device_card('settings', lambda project_name, device_name: None)


def test_get_project_dashboard_cards_returns_a_copy(project):
    with registering('ext1'):
        register_project_card('dashboard', lambda project_name: None)
    _enable(project, 'ext1')

    cards = get_project_dashboard_cards(project)
    cards.append(lambda project_name: None)
    assert len(get_project_dashboard_cards(project)) == 1


def test_global_card_returned_regardless_of_enablement(project):
    fn = lambda: None
    with registering('ext1'):
        register_global_card('E-Paper', fn)

    # not enabled for any project — still returned, since it isn't project-scoped
    assert get_global_cards() == [('E-Paper', fn)]


def test_register_global_card_outside_context_raises():
    with pytest.raises(RuntimeError):
        register_global_card('E-Paper', lambda: None)


def test_get_global_cards_returns_a_copy():
    with registering('ext1'):
        register_global_card('E-Paper', lambda: None)

    cards = get_global_cards()
    cards.append(('Other', lambda: None))
    assert len(get_global_cards()) == 1


# ---------------------------------------------------------------------------
# User menu
# ---------------------------------------------------------------------------

def test_user_menu_item_returned_regardless_of_enablement(project):
    fn = lambda: None
    with registering('ext1'):
        register_user_menu_item('Screens', fn, icon='tv')

    # not enabled for any project — still returned, since it isn't project-scoped
    assert get_user_menu_items() == [('Screens', 'tv', fn)]


def test_user_menu_item_icon_is_optional():
    fn = lambda: None
    with registering('ext1'):
        register_user_menu_item('Screens', fn)

    assert get_user_menu_items() == [('Screens', None, fn)]


def test_register_user_menu_item_outside_context_raises():
    with pytest.raises(RuntimeError):
        register_user_menu_item('Screens', lambda: None)


def test_get_user_menu_items_returns_a_copy():
    with registering('ext1'):
        register_user_menu_item('Screens', lambda: None)

    items = get_user_menu_items()
    items.append(('Other', None, lambda: None))
    assert len(get_user_menu_items()) == 1


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def test_project_tab_only_returned_when_enabled(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_tab('Extra', fn)

    assert get_project_tabs(project) == []
    _enable(project, 'ext1')
    assert get_project_tabs(project) == [('ext1', 'Extra', 'extension', fn)]


def test_project_tab_custom_icon(project):
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_tab('Extra', fn, icon='star')
    _enable(project, 'ext1')
    assert get_project_tabs(project) == [('ext1', 'Extra', 'star', fn)]


def test_device_tab_only_returned_when_enabled(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_tab('Extra', fn)

    assert get_device_tabs(project) == []
    _enable(project, 'ext1')
    assert get_device_tabs(project) == [('Extra', 'extension', fn)]


def test_device_tab_custom_icon(project):
    fn = lambda project_name, device_name: None
    with registering('ext1'):
        register_device_tab('Extra', fn, icon='star')
    _enable(project, 'ext1')
    assert get_device_tabs(project) == [('Extra', 'star', fn)]


# ---------------------------------------------------------------------------
# call_with_page_args — routing info for tabs/cards that want it
# ---------------------------------------------------------------------------

def _page_args():
    from starlette.datastructures import QueryParams
    from nicegui import PageArguments
    return PageArguments(path='/here', frame=None, path_parameters={}, query_parameters=QueryParams(), data={})


def test_call_with_page_args_omits_args_for_plain_render_fn():
    calls = []
    call_with_page_args(lambda project_name: calls.append(project_name), _page_args(), 'proj')
    assert calls == ['proj']


def test_call_with_page_args_passes_args_when_annotated():
    from nicegui import PageArguments
    calls = []

    def render_fn(project_name, args: PageArguments):
        calls.append((project_name, args))

    page_args = _page_args()
    call_with_page_args(render_fn, page_args, 'proj')
    assert calls == [('proj', page_args)]


def test_call_with_page_args_finds_annotated_param_by_position():
    """The PageArguments parameter need not be named 'args' — matched by annotation."""
    from nicegui import PageArguments
    calls = []

    def render_fn(project_name, device_name, routing: PageArguments):
        calls.append((project_name, device_name, routing))

    page_args = _page_args()
    call_with_page_args(render_fn, page_args, 'proj', 'dev')
    assert calls == [('proj', 'dev', page_args)]


# ---------------------------------------------------------------------------
# Standalone project pages
# ---------------------------------------------------------------------------

def test_register_project_page_round_trip():
    fn = lambda project_name: None
    with registering('ext1'):
        register_project_page(fn)

    assert get_project_page('ext1') is fn


def test_get_project_page_unregistered_returns_none():
    assert get_project_page('does-not-exist') is None


def test_register_project_page_twice_raises():
    with registering('ext1'):
        register_project_page(lambda project_name: None)
        with pytest.raises(RuntimeError):
            register_project_page(lambda project_name: None)


def test_extension_page_pattern_matches_bare_and_deep_paths():
    """Standalone pages route the whole /ext/<name>/... subtree to render_fn, so an
    extension can nest its own ui.sub_pages for deep links (docs/extensions.md)."""
    from app.frontend import _EXTENSION_PAGE_PATTERN

    for path, project_id, extension_name in [
        ('/ui/project/demo/ext/epaper', 'demo', 'epaper'),
        ('/ui/project/demo/ext/epaper/', 'demo', 'epaper'),
        ('/ui/project/demo/ext/epaper/screens/5', 'demo', 'epaper'),
    ]:
        m = _EXTENSION_PAGE_PATTERN.match(path)
        assert m is not None, path
        assert m.group('project_id') == project_id
        assert m.group('extension_name') == extension_name

    assert _EXTENSION_PAGE_PATTERN.match('/ui/project/demo/device/dev1') is None


def _fake_request(path: str, root_path: str = '', forwarded_prefix: str = ''):
    from starlette.requests import Request
    headers = [(b'x-forwarded-prefix', forwarded_prefix.encode())] if forwarded_prefix else []
    scope = {
        'type': 'http',
        'path': path,
        'root_path': root_path,
        'headers': headers,
        'query_string': b'',
        'method': 'GET',
        'scheme': 'https',
        'server': ('example.com', 443),
    }
    return Request(scope)


def test_request_path_strips_root_path_when_proxy_forwards_prefix_unstripped():
    """A reverse proxy that forwards e.g. '/iot/*' without stripping it (Caddy's
    plain `reverse_proxy`, as opposed to `handle_path`) leaves the ops-level
    mount prefix in scope['path'] -- request.url.path echoes it verbatim, which
    would otherwise make _EXTENSION_PAGE_PATTERN's '^/ui/...' anchor silently
    never match (see docs/deploy or the Caddyfile for --root-path)."""
    from app.frontend import _request_path
    request = _fake_request('/iot/ui/project/demo/ext/epaper', root_path='/iot')
    assert _request_path(request) == '/ui/project/demo/ext/epaper'


def test_request_path_unchanged_when_proxy_already_stripped_prefix():
    """A proxy that strips the mount prefix before forwarding (Caddy's
    `handle_path`) already delivers the un-prefixed path; --root-path is still
    set (informational, for URL generation) but must not be subtracted twice."""
    from app.frontend import _request_path
    request = _fake_request('/ui/project/demo/ext/epaper', root_path='/iot')
    assert _request_path(request) == '/ui/project/demo/ext/epaper'


def test_request_path_unchanged_when_mounted_at_root():
    from app.frontend import _request_path
    request = _fake_request('/ui/project/demo/ext/epaper', root_path='')
    assert _request_path(request) == '/ui/project/demo/ext/epaper'


def test_request_path_uses_x_forwarded_prefix_too():
    from app.frontend import _request_path
    request = _fake_request('/iot/ui/project/demo', root_path='', forwarded_prefix='/iot')
    assert _request_path(request) == '/ui/project/demo'


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
# Telemetry cache-kind registry
# ---------------------------------------------------------------------------

def test_telemetry_cache_kind_disabled_by_default(project):
    with registering('ext1'):
        register_telemetry_cache_kind('epaper')
    # not enabled

    assert telemetry_cache_kind_enabled(project, 'epaper') is False


def test_telemetry_cache_kind_enabled_after_enabling(project):
    with registering('ext1'):
        register_telemetry_cache_kind('epaper')
    _enable(project, 'ext1')

    assert telemetry_cache_kind_enabled(project, 'epaper') is True


def test_telemetry_cache_kind_false_for_unregistered_kind(project):
    _enable(project, 'ext1')

    assert telemetry_cache_kind_enabled(project, 'unknown') is False


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

    assert mqtt_backend._extension_topic_handlers == [('ext1', 'status', handler, 0)]


def test_register_topic_handler_stores_qos():
    async def handler(project_name, topic, payload):
        pass

    with registering('ext1'):
        register_topic_handler('status', handler, qos=1)

    assert mqtt_backend._extension_topic_handlers == [('ext1', 'status', handler, 1)]


@pytest.mark.parametrize("suffix,qos", [
    ('', 0),           # empty suffix
    ('/status', 0),    # leading slash
    ('status', 3),     # invalid qos
    ('status', -1),
])
def test_register_topic_handler_invalid_args_raise(suffix, qos):
    async def handler(project_name, topic, payload):
        pass

    with registering('ext1'):
        with pytest.raises(ValueError):
            register_topic_handler(suffix, handler, qos=qos)

    assert mqtt_backend._extension_topic_handlers == []


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
