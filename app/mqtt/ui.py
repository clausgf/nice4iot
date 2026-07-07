from nicegui import ui
from niceview.form import ModelForm

from app.mqtt.backend import get_mqtt_adapter, connection_status
from app.mqtt.models import MqttGlobalConfig


def MqttGlobalConfigCard() -> None:
    """Expandable card for global MQTT broker settings."""
    adapter = get_mqtt_adapter()

    @ui.refreshable
    def _status() -> None:
        status = connection_status
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
        form = ModelForm.from_adapter(MqttGlobalConfig, adapter, autosave=True)
        form.render()
        for w in form.widgets.values():
            w.props('outlined dense').classes('w-full')
