import logging
import logging.handlers
from pathlib import Path

from pydantic import BaseModel

from app.core.logging.models import LoggingBackend
from app.config import app_config


class FileLogConfig(BaseModel):
    backup_count: int = 7


class FileLogBackend(LoggingBackend):
    """
    Filesystem logging backend. Writes device log messages to a per-project
    rotating log file using daily rotation.

    File location: {projects_dir}/{project_name}/.device.log
    Rotated files: .device.log.YYYY-MM-DD (kept for backup_count days)
    """

    # Class-level handler cache: one handler per project, created on first write.
    _handlers: dict[str, logging.Handler] = {}

    def __init__(self, project_name: str, config: FileLogConfig = FileLogConfig()):
        super().__init__(project_name)
        self.config = config
        self._ensure_handler()

    def _ensure_handler(self) -> None:
        if self.project_name in self._handlers:
            return

        log_path = Path(app_config.projects_dir) / self.project_name / '.device.log'
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path,
            when='midnight',
            backupCount=self.config.backup_count,
            encoding='utf-8',
        )
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

        device_logger = logging.getLogger(f'device_log.{self.project_name}')
        device_logger.addHandler(handler)
        device_logger.setLevel(logging.DEBUG)
        device_logger.propagate = False  # keep device logs out of uvicorn output

        self._handlers[self.project_name] = handler

    async def write(self, device_name: str, logmsg: str) -> None:
        logger = logging.getLogger(f'device_log.{self.project_name}')
        logger.info('[%s] %s', device_name, logmsg)
