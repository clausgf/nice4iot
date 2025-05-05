import datetime
from pydantic import BaseModel, Field
from app.config import app_config
from app.core.telemetry.telemetry_util import BackendTypes

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


class Tag(BaseModel):
    name: str
    color: str = "blue"


class AuthToken(BaseModel):
    is_active: bool = True
    value: str
    created_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    expires_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    last_use_at: datetime.datetime | None = None


class Project(BaseModel):
    is_active: bool = True
    name: str
    description: str = ""
    created_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    updated_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    owner: str = ""
    is_autocreate_devices: bool = True
    is_provisioning_autoapproval: bool = True
    device_tokens_expire_in: datetime.timedelta = datetime.timedelta(days=7)
    telemetryBackend: BackendTypes = BackendTypes.PROMETHEUS
    tags: list[str] = []
    provisioning_tokens: list[AuthToken] = []


class Device(BaseModel):
    is_active: bool = True
    name: str
    description: str = ""
    location: str = ""
    created_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    updated_at: datetime.datetime = Field(default_factory=NOW_FACTORY)
    last_seen_at: datetime.datetime | None = None

    is_provisioning_approved: bool = False
    last_provisioning_request_at: datetime.datetime | None = None
    last_provisioned_at: datetime.datetime | None = None

    tags: list[str] = []
    tokens: list[AuthToken] = []
    project_name: str
