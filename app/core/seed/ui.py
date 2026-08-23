"""Seed settings cards for the General tab — project-level bootstrap data
(WiFi, API URL, TLS trust) and the per-device WiFi override.

Rendered inside a shared ``config_expansion`` (the caller provides the foldable
header), so this matches the other configuration cards — form fields only, no
outer card/header of their own.
"""
from pathlib import Path

from nicegui import ui
from niceview import ConflictError, ModelForm, StorageError

from app.core.seed.backend import get_device_seed_override_adapter, get_seed_adapter
from app.core.seed.models import DeviceSeedOverride, SeedSettings


async def seed_settings_card(dir_path: Path) -> None:
    """Project-level Seed settings form: WiFi/API URL/TLS bootstrap data."""
    adapter = get_seed_adapter(dir_path)
    config = adapter.read()

    ui.markdown(SeedSettings.Meta.description).classes('text-caption q-ma-none')

    async def _save() -> None:
        try:
            adapter.save(config)
        except (ConflictError, StorageError) as e:
            ui.notify(str(e), color='negative')

    async def _set_visibility() -> None:
        form.widgets['ca_cert'].set_visibility(config.tls_mode == 'custom')

    async def _on_change(_e) -> None:
        await _save()
        await _set_visibility()

    # updated_at is the config's optimistic-lock timestamp (last save), not a
    # seed fact — excluded from the form to avoid confusion.
    form = ModelForm.from_item(config, exclude='updated_at', on_change=_on_change,
                               base_props='outlined dense hide-bottom-space',
                               default_classes='w-full', profile='settings')
    form.render()
    form.widgets['ca_cert'].set_visibility(config.tls_mode == 'custom')


async def device_seed_override_card(dir_path: Path) -> None:
    """Device-level Seed override form: this device's own WiFi credentials,
    shown and editable only while "Override project settings" is on."""
    adapter = get_device_seed_override_adapter(dir_path)
    config = adapter.read()

    ui.markdown(DeviceSeedOverride.Meta.description).classes('text-caption q-ma-none')

    async def _save() -> None:
        try:
            adapter.save(config)
        except (ConflictError, StorageError) as e:
            ui.notify(str(e), color='negative')

    async def _set_visibility() -> None:
        enabled = config.override_enabled
        for name in ('wifi_ssid', 'wifi_password'):
            form.widgets[name].set_visibility(enabled)
            form.widgets[name].set_enabled(enabled)

    async def _on_change(_e) -> None:
        await _save()
        await _set_visibility()

    form = ModelForm.from_item(config, exclude='updated_at', on_change=_on_change,
                               base_props='outlined dense hide-bottom-space',
                               default_classes='w-full', profile='settings')
    form.render()
    await _set_visibility()
