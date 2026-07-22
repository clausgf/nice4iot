import datetime
import logging
from typing import List, Literal, Optional
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings

log = logging.getLogger('uvicorn')


class AppConfig(BaseSettings):
    projects_dir: DirectoryPath = "data/projects"
    provisioning_token_length: int = 64
    provisioning_token_expires_in: datetime.timedelta = datetime.timedelta(days=365)
    device_token_length: int = 32
    max_file_upload_size: int = 10 * 1024 * 1024  # 10 MiB
    max_telemetry_size: int = 8192                 # 8 KiB
    max_log_size: int = 8192                       # 8 KiB
    timezone: str = 'Europe/Berlin'
    nicegui_storage_secret: str = ""

    # CORS origins allowed to call the REST API from a browser. Devices are not
    # browsers, so this only matters for browser-based callers (a separate web
    # frontend, Swagger UI on another host). Default "*" is permissive; set a
    # JSON list to restrict, e.g. CORS_ALLOW_ORIGINS='["https://app.example.com"]'.
    cors_allow_origins: List[str] = ["*"]

    # Global MQTT broker connection, shared by all projects. Configured here
    # (environment) rather than in the UI so the password stays out of the data
    # volume. Disabled by default — no connection is attempted unless MQTT_ENABLED
    # is set. Per-project MQTT use is still toggled in the project settings.
    mqtt_enabled: bool = False
    mqtt_server: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = "nice4iot"

    # Defaults for NEW projects only. They seed a project's telemetry/logging
    # config at creation time; everything stays editable per project in the UI.
    # An unset (empty) value falls back to the model default, so leaving these
    # unset reproduces today's behaviour exactly. Handy when most projects share
    # one backend (e.g. a common VictoriaMetrics). Passwords/tokens belong in a
    # secret. See app.core.telemetry.backend.default_telemetry_config().
    default_telemetry_backend: Literal["none", "prometheus", "influxdb"] = "none"
    default_telemetry_prometheus_push_url: str = ""
    default_telemetry_prometheus_pull_url: str = ""
    default_telemetry_prometheus_username: str = ""
    default_telemetry_prometheus_password: str = ""
    default_telemetry_influxdb_write_url: str = ""
    default_telemetry_influxdb_database: str = ""
    default_telemetry_influxdb_org: str = ""
    default_telemetry_influxdb_bucket: str = ""
    default_telemetry_influxdb_username: str = ""
    default_telemetry_influxdb_password: str = ""
    default_telemetry_influxdb_token: str = ""
    default_logging_loki_enabled: bool = False
    default_logging_loki_url: str = ""
    default_logging_loki_username: str = ""
    default_logging_loki_password: str = ""
    default_logging_loki_tenant_id: str = ""

    # Per-project device-token defaults (also editable per project). device_token_length
    # was previously unused; it now seeds new projects' Project.device_token_length.
    device_token_expires_in: int = 7  # days

    # admin UI authentication (see app/auth/) — does not affect the
    # device REST API, which has its own separate bearer-token auth
    #   "none"     - no authentication (default)
    #   "proxy"    - identity forwarded by an authenticating reverse proxy
    #   "password" - built-in login page against an htpasswd file
    auth_provider: Literal["none", "proxy", "password"] = "none"
    auth_user_headers: List[str] = [
        "X-Forwarded-Preferred-Username",
        "X-Forwarded-User",
        "X-Forwarded-Email",
    ]
    auth_logout_url: Optional[str] = None
    auth_htpasswd_file: str = "data/htpasswd"

app_config = AppConfig()


if not app_config.nicegui_storage_secret:
    log.warning("NICEGUI_STORAGE_SECRET is not set — user sessions will not persist across restarts")
