import datetime
from typing import Annotated, Literal, Protocol
from pydantic import BaseModel, Field
import niceview


class LoggingBackend(Protocol):
    async def write(self, device_name: str, logmsg: str) -> None: ...


class LokiConfig(BaseModel):
    """Pushes log messages to a Grafana Loki endpoint via the JSON push API."""
    is_active: Annotated[bool, Field(title='Active')] = False
    log_url: Annotated[str, 
            Field(description='Loki push API endpoint URL.')
        ] = "http://alloy:8082/loki/api/v1/push"
    username: Annotated[str, 
            Field(description='Username for Basic Auth (e.g. Grafana Cloud user ID). Leave empty to disable auth.')
        ] = ""
    password: Annotated[str, 
            Field(description='Password or API token for Basic Auth.'), 
            niceview.Field(password=True)
        ] = ""
    tenant_id: Annotated[str, 
            Field(description='Loki tenant ID sent as X-Scope-OrgID header. Leave empty for single-tenant setups.')
        ] = ""
    timeout: Annotated[int, 
            Field(description='HTTP request timeout in seconds.')
        ] = 10


class FileLogConfig(BaseModel):
    """Appends log messages to a per-project rotating log file."""
    is_active: Annotated[bool, 
            Field(title='Active')
        ] = False
    rotation_interval: Annotated[
            Literal['daily', 'weekly', 'monthly'],
            niceview.Field(options={'daily': 'Daily (00:00)', 'weekly': 'Weekly (Sun)', 'monthly': 'Monthly (01.)'})
        ] = 'daily'
    backup_count: Annotated[int, 
            Field(description='Number of backup files to keep.')
        ] = 7


class LoggingConfig(BaseModel):
    """Per-project logging configuration. Multiple backends can be active simultaneously."""
    updated_at: Annotated[
            datetime.datetime | None,
            Field(description='Timestamp of the last configuration change (UTC, set automatically).'),
            niceview.Field(editable=False),
        ] = None
    loki: LokiConfig = Field(default_factory=LokiConfig)
    file: FileLogConfig = Field(default_factory=FileLogConfig)

    class Meta:
        description = (
            "Configures where device log messages are stored. "
            "Multiple backends can be active at the same time."
        )
