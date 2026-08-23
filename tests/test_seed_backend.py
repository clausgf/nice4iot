"""Unit tests for app.core.seed — model defaults/validation and adapter IO."""
from pydantic import ValidationError
import pytest

from app.core.seed.backend import get_device_seed_override_adapter, get_seed_adapter
from app.core.seed.models import DeviceSeedOverride, SeedSettings


def test_seed_settings_defaults():
    src = SeedSettings()
    assert src.wifi_ssid == ''
    assert src.wifi_password == ''
    assert src.api_url == ''
    assert src.tls_mode == 'public'
    assert src.ca_cert == ''


def test_seed_settings_rejects_invalid_tls_mode():
    with pytest.raises(ValidationError):
        SeedSettings(tls_mode='invalid')


def test_device_seed_override_defaults():
    override = DeviceSeedOverride()
    assert override.override_enabled is False
    assert override.wifi_ssid == ''
    assert override.wifi_password == ''


def test_seed_adapter_roundtrip(tmp_path):
    adapter = get_seed_adapter(tmp_path)
    config = adapter.read()
    config.wifi_ssid = 'my-network'
    config.wifi_password = 'secret'
    config.api_url = 'https://iot.example.com'
    config.tls_mode = 'custom'
    config.ca_cert = '-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----'
    adapter.save(config)

    reloaded = get_seed_adapter(tmp_path).read()
    assert reloaded.wifi_ssid == 'my-network'
    assert reloaded.tls_mode == 'custom'
    assert reloaded.ca_cert.startswith('-----BEGIN CERTIFICATE-----')


def test_device_seed_override_adapter_roundtrip(tmp_path):
    adapter = get_device_seed_override_adapter(tmp_path)
    config = adapter.read()
    config.override_enabled = True
    config.wifi_ssid = 'device-network'
    config.wifi_password = 'device-secret'
    adapter.save(config)

    reloaded = get_device_seed_override_adapter(tmp_path).read()
    assert reloaded.override_enabled is True
    assert reloaded.wifi_ssid == 'device-network'
