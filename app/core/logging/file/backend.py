import datetime
import glob
import logging
import logging.handlers
import os
from pathlib import Path

from app.core.logging.models import FileLogConfig
from app.config import app_config


class _MonthlyRotatingFileHandler(logging.handlers.BaseRotatingHandler):
    """Rotates on the 1st of each month. Keeps backup_count monthly files."""

    def __init__(self, filename: str, backup_count: int = 0, encoding: str = 'utf-8'):
        super().__init__(filename, mode='a', encoding=encoding, delay=False)
        self.backupCount = backup_count

    def shouldRollover(self, record) -> int:
        today = datetime.date.today()
        if today.day != 1:
            return 0
        if not os.path.exists(self.baseFilename):
            return 0
        mtime = datetime.date.fromtimestamp(os.path.getmtime(self.baseFilename))
        return 1 if mtime.month != today.month else 0

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        today = datetime.date.today()
        dfn = self.baseFilename + '.' + today.strftime('%Y-%m')
        if not os.path.exists(dfn):
            os.rename(self.baseFilename, dfn)
        if self.backupCount > 0:
            files = sorted(glob.glob(self.baseFilename + '.????-??'))
            while len(files) > self.backupCount:
                os.remove(files.pop(0))
        self.stream = self._open()


class FileLogBackend:
    """
    Filesystem logging backend. Writes device log messages to per-device
    rotating log files.

    File location: {projects_dir}/{project_name}/{device_name}/.device.log
    """

    _handlers: dict[tuple[str, str], tuple[logging.Handler, FileLogConfig]] = {}

    def __init__(self, project_name: str, config: FileLogConfig = FileLogConfig()):
        self.project_name = project_name
        self.config = config

    def _ensure_handler(self, device_name: str) -> None:
        key = (self.project_name, device_name)
        if key in self._handlers:
            _, cached_config = self._handlers[key]
            if cached_config == self.config:
                return
            old_handler, _ = self._handlers.pop(key)
            logger = logging.getLogger(f'device_log.{self.project_name}.{device_name}')
            logger.removeHandler(old_handler)
            old_handler.close()
        log_dir = Path(app_config.projects_dir) / self.project_name / device_name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / '.device.log'
        interval = self.config.rotation_interval
        if interval == 'monthly':
            handler: logging.Handler = _MonthlyRotatingFileHandler(
                filename=str(log_path),
                backup_count=self.config.backup_count,
            )
        else:
            handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_path,
                when='midnight' if interval == 'daily' else 'W6',
                backupCount=self.config.backup_count,
                encoding='utf-8',
            )
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        device_logger = logging.getLogger(f'device_log.{self.project_name}.{device_name}')
        device_logger.addHandler(handler)
        device_logger.setLevel(logging.DEBUG)
        device_logger.propagate = False
        self._handlers[key] = (handler, self.config)

    async def write(self, device_name: str, logmsg: str) -> None:
        self._ensure_handler(device_name)
        logging.getLogger(f'device_log.{self.project_name}.{device_name}').info('%s', logmsg)
