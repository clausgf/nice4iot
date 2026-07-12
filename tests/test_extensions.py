"""
Unit tests for the extension mechanism (see docs/extensions.md):
- app.extensions card/tab/event registries
- app.core.device.backend.create_device() firing the device-provisioned hook
- app.mqtt.backend topic-filter matching and mqtt_publish()
"""
import asyncio

import pytest

import app.extensions as extensions
import app.mqtt.backend as mqtt_backend
from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.project.backend import create_project
from app.extensions import (
    get_device_cards,
    get_device_tabs,
    get_project_cards,
    get_project_tabs,
    register_device_card,
    register_device_provisioned_callback,
    register_device_tab,
    register_project_card,
    register_project_tab,
)
from app.mqtt.backend import _topic_matches, mqtt_publish, register_topic_handler


@pytest.fixture(autouse=True)
def clear_extension_registries():
    yield
    extensions._clear_registries()
    mqtt_backend._extension_topic_handlers.clear()


@pytest.fixture
def project(projects_dir):
    create_project("proj")
    return "proj"


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def test_register_project_card_round_trip():
    fn = lambda project_name: None
    register_project_card('dashboard', fn)
    assert get_project_cards('dashboard') == [fn]
    assert get_project_cards('general') == []


def test_register_device_card_round_trip():
    fn = lambda project_name, device_name: None
    register_device_card('general', fn)
    assert get_device_cards('general') == [fn]
    assert get_device_cards('dashboard') == []


def test_get_project_cards_returns_a_copy():
    register_project_card('dashboard', lambda project_name: None)
    cards = get_project_cards('dashboard')
    cards.append(lambda project_name: None)
    assert len(get_project_cards('dashboard')) == 1


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def test_register_project_tab_round_trip():
    fn = lambda project_name: None
    register_project_tab('Extra', fn)
    assert get_project_tabs() == [('Extra', fn)]


def test_register_device_tab_round_trip():
    fn = lambda project_name, device_name: None
    register_device_tab('Extra', fn)
    assert get_device_tabs() == [('Extra', fn)]


# ---------------------------------------------------------------------------
# Device-provisioned event
# ---------------------------------------------------------------------------

def test_device_provisioned_callback_fires_on_create_device(project):
    received = []
    register_device_provisioned_callback(received.append)

    device = create_device(Device(name="dev1", project_name=project))

    assert len(received) == 1
    assert received[0].name == device.name
    assert received[0].project_name == project


def test_device_provisioned_callback_error_does_not_prevent_creation(project, caplog):
    def bad_callback(device):
        raise RuntimeError("boom")

    register_device_provisioned_callback(bad_callback)

    device = create_device(Device(name="dev1", project_name=project))

    assert device.name == "dev1"


def test_device_provisioned_callback_receives_multiple_registrations(project):
    calls = []
    register_device_provisioned_callback(lambda d: calls.append('first'))
    register_device_provisioned_callback(lambda d: calls.append('second'))

    create_device(Device(name="dev1", project_name=project))

    assert calls == ['first', 'second']


# ---------------------------------------------------------------------------
# MQTT topic matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("topic,topic_filter,expected", [
    ("foo/bar", "foo/bar", True),
    ("foo/bar", "foo/baz", False),
    ("foo/x/bar", "foo/+/bar", True),
    ("foo/x/y/bar", "foo/+/bar", False),
    ("foo", "foo/#", True),
    ("foo/x", "foo/#", True),
    ("foo/x/y", "foo/#", True),
    ("bar/x", "foo/#", False),
    ("foo/bar", "foo/bar/baz", False),
    ("foo/bar/baz", "foo/bar", False),
])
def test_topic_matches(topic, topic_filter, expected):
    assert _topic_matches(topic, topic_filter) is expected


# ---------------------------------------------------------------------------
# MQTT dispatch registration
# ---------------------------------------------------------------------------

def test_register_topic_handler_round_trip():
    async def handler(topic, payload):
        pass

    register_topic_handler('epaper/+/status', handler)
    assert mqtt_backend._extension_topic_handlers == [('epaper/+/status', handler)]


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
