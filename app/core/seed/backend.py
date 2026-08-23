"""Persistence for Seed settings (project-level bootstrap data for arduino4iot
devices) and the per-device WiFi override, plus resolving the two into the
single "effective seed" a device actually needs — for the Web-Serial-Flash
NVS image and the AP+QR deep link (see app.core.seed.nvs / app.core.seed.ui).
"""
from dataclasses import dataclass
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.core.seed.models import DeviceSeedOverride, SeedSettings
from app.paths import device_dir, project_dir

SEED_CONFIG_FILE = '.seed.json'
SEED_OVERRIDE_FILE = '.seed_override.json'


def get_seed_adapter(dir_path: Path) -> JsonAdapter:
    """JsonAdapter for a project's Seed settings (for UI ModelForm binding)."""
    return JsonAdapter(SeedSettings, dir_path / SEED_CONFIG_FILE,
                       create_if_not_exist=True, lock_field='updated_at')


def get_device_seed_override_adapter(dir_path: Path) -> JsonAdapter:
    """JsonAdapter for a device's WiFi override of the project's Seed settings."""
    return JsonAdapter(DeviceSeedOverride, dir_path / SEED_OVERRIDE_FILE,
                       create_if_not_exist=True, lock_field='updated_at')


@dataclass
class EffectiveSeed:
    """The bootstrap values a specific device needs, after resolving the
    project's Seed settings against that device's WiFi override — plus the
    project name and a caller-chosen provisioning token, which aren't part of
    SeedSettings (they already live in the project name itself / the
    Provisioning token list)."""
    wifi_ssid: str
    wifi_password: str
    api_url: str
    tls_mode: str    # 'public' | 'custom' — see SeedSettings.tls_mode
    ca_cert: str
    project_name: str
    provisioning_token: str


def get_effective_seed(project_name: str, device_name: str, provisioning_token: str) -> EffectiveSeed:
    """Resolve a device's effective seed: its own WiFi override if enabled,
    else the project's, combined with the project's API URL/TLS trust."""
    project_seed = get_seed_adapter(project_dir(project_name)).read()
    override = get_device_seed_override_adapter(device_dir(project_name, device_name)).read()
    if override.override_enabled:
        wifi_ssid, wifi_password = override.wifi_ssid, override.wifi_password
    else:
        wifi_ssid, wifi_password = project_seed.wifi_ssid, project_seed.wifi_password
    return EffectiveSeed(
        wifi_ssid=wifi_ssid,
        wifi_password=wifi_password,
        api_url=project_seed.api_url,
        tls_mode=project_seed.tls_mode,
        ca_cert=project_seed.ca_cert,
        project_name=project_name,
        provisioning_token=provisioning_token,
    )
