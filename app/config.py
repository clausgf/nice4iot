import datetime
import logging
from pydantic import DirectoryPath
from pydantic_settings import BaseSettings

log = logging.getLogger('uvicorn')


class AppConfig(BaseSettings):
    projects_dir: DirectoryPath = "data/projects"
    provisioning_token_length: int = 64
    provisioning_token_expires_in: datetime.timedelta = datetime.timedelta(days=365)
    device_token_length: int = 32
    max_upload_size: int = 1048576  # 1 MB
    timezone: str = 'Europe/Berlin'
    nicegui_storage_secret: str = ""

app_config = AppConfig()


if not app_config.nicegui_storage_secret:
    log.warning("NICEGUI_STORAGE_SECRET is not set — user sessions will not persist across restarts")
