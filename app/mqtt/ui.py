from nicegui import ui

import app.mqtt.backend as _mqtt_backend
from app.config import app_config


def MqttStatusCard() -> None:
    """Read-only global MQTT broker status.

    The broker connection is configured via environment variables (MQTT_ENABLED,
    MQTT_SERVER, …); see docs/configuration.md. This card only shows the live
    connection status — there is nothing to edit here.
    """
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
        with ui.row().classes('items-center gap-2 w-full'):
            if app_config.mqtt_enabled:
                ui.label(f'{app_config.mqtt_server}:{app_config.mqtt_port}').classes('text-body2')
            else:
                ui.label('Disabled (set MQTT_ENABLED to enable)').classes('text-body2 text-grey-7')
            ui.space()
            ui.chip(status).props(f'dense color={color} text-color=white')

    _status()
    ui.timer(5.0, _status.refresh)
    ui.label('Configured via environment variables (MQTT_*); see the docs.') \
        .classes('text-caption text-grey-7')
