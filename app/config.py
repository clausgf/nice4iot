from pydantic import DirectoryPath
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    projects_dir: DirectoryPath = "data/projects"
    provisioning_token_length: int = 64
    device_token_length: int = 32
    max_upload_size: int = 1048576  # 1 MB


app_config = AppConfig()
