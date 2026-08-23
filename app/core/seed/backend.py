"""Persistence for Seed settings (project-level bootstrap data for arduino4iot
devices) and the per-device WiFi override. Config/state IO only — no network
or provisioning logic lives here yet; see app.api.provisioning for that flow.
"""
from pathlib import Path

from niceview.dataadapter import JsonAdapter

from app.core.seed.models import DeviceSeedOverride, SeedSettings

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
