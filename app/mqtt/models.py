import datetime
from typing import Annotated
from pydantic import BaseModel, Field
import niceview


class MqttGlobalConfig(BaseModel):
    """Global MQTT broker connection settings. All projects share one connection."""
    is_enabled: bool = Field(default=True, title="MQTT Broker enabled",
                             description="Master switch. When disabled, no MQTT connection is attempted.")
    server: str = Field(default="localhost", description="MQTT broker hostname or IP.")
    port: int = Field(default=1883, description="Broker port (default 1883, TLS typically 8883).")
    username: str = Field(default="", description="Login username. Leave empty for anonymous connections.")
    password: Annotated[str, niceview.Field(password=True)] = Field(default="", description="Login password.")
    client_id: str = Field(default="nice4iot", description="MQTT client ID. Must be unique per broker. Change if running multiple instances.")
    updated_at: Annotated[datetime.datetime | None, niceview.Field(editable=False)] = None

    class Meta:
        description = "MQTT broker connection settings shared by all projects."
