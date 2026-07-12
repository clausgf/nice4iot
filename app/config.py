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
