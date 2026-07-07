import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field
import niceview


class FileConfig(BaseModel):
    """Per-project file transfer configuration."""
    max_upload_size: int = Field(
        default=10485760,
        description="Maximum upload size in bytes for device file uploads via HTTP and MQTT. "
                    "Note: MQTT broker also has its own message size limit (Mosquitto default: 256 MB), "
                    "configured separately in mosquitto.conf.",
    )
    updated_at: Annotated[datetime.datetime | None, niceview.Field(editable=False)] = None

    # MQTT download (server → device) settings
    mqtt_check_interval_s: int = Field(
        default=60,
        title="File check interval (s)",
        description="How often nice4iot checks for file changes to notify devices via MQTT. "
                    "Set to match your expected update cadence. Files changed via the UI are published immediately.",
    )
    mqtt_qos: Annotated[
        Literal[0, 1, 2],
        niceview.Field(
            label="Download QoS",
            select_options={0: "QoS 0 – fire and forget", 1: "QoS 1 – at least once", 2: "QoS 2 – exactly once"},
        )
    ] = 1
    mqtt_retain: bool = Field(
        default=True,
        title="Retain download messages",
        description="Retained messages are stored by the broker and delivered immediately when a device "
                    "subscribes — useful if the device restarts while the server is running. "
                    "With QoS 1 and a persistent session on the device, retained messages are redundant; "
                    "disable retain to save broker storage.",
    )

    class Meta:
        description = "File transfer settings for this project."
