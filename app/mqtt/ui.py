from nicegui import ui
from niceview.form import ModelForm

import app.mqtt.backend as _mqtt_backend
from app.mqtt.models import MqttGlobalConfig


def MqttGlobalConfigCard() -> None:
    """Expandable card for global MQTT broker settings."""
    adapter = _mqtt_backend.get_mqtt_adapter()

    @ui.refreshable
    def _status() -> None:
        # Read the live module attribute — a module-level import would bind the
        # initial string value and never see subsequent reassignments.
        status = _mqtt_backend.connection_status
        if status == 'connected':
            color = 'green'
        elif status.startswith('error'):
            color = 'orange'
        else:
            color = 'grey'
        ui.chip(status).props(f'dense color={color} text-color=white')

    with ui.expansion('MQTT Broker').classes('w-full').props('dense header-class="text-h6 font-bold"'):
        _status()
        ui.timer(5.0, _status.refresh)
        form = ModelForm.from_adapter(MqttGlobalConfig, adapter,
                                      include=['server', 'port', 'username', 'password', 'client_id'],
                                      autosave=True)
        form.render()
        for w in form.widgets.values():
            w.props('outlined dense').classes('w-full')
