from nicegui import ui
from niceview import ModelForm

import app.mqtt.backend as _mqtt_backend
from app.mqtt.models import MqttGlobalConfig


def MqttGlobalConfigCard() -> None:
    """Content for the global MQTT broker settings card (caller provides the card/header)."""
    adapter = _mqtt_backend.get_mqtt_adapter()

    @ui.refreshable
    def _status() -> None:
        # Read the live module attribute — a module-level import would bind the
        # initial string value and never see subsequent reassignments.
        status = _mqtt_backend.connection_status
        if status == 'connected':
            color = 'green'
        elif status == 'disabled':
            color = 'grey'
        elif status.startswith('error'):
            color = 'orange'
        else:
            color = 'grey'
        ui.chip(status).props(f'dense color={color} text-color=white')

    form = ModelForm.from_adapter(MqttGlobalConfig, adapter,
                                  include=['is_enabled', 'server', 'port', 'username', 'password', 'client_id'],
                                  autosave=True)
    form.render_field('is_enabled')
    _status()
    ui.timer(5.0, _status.refresh)
    for name in ['server', 'port', 'username', 'password', 'client_id']:
        form.render_field(name).props('outlined dense').classes('w-full')
