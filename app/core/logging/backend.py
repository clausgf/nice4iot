from niceview.dataadapter import JsonAdapter

from app.paths import project_dir
from app.core.logging.models import LoggingBackend, LoggingConfig
from app.core.logging.loki.backend import LokiBackend
from app.core.logging.file.backend import FileLogBackend

LOG_FILE = '.logging.json'


def get_logging_adapter(project_name: str) -> JsonAdapter:
    """Get a JsonAdapter for the logging configuration of a project."""
    return JsonAdapter(LoggingConfig, project_dir(project_name) / LOG_FILE,
                       create_if_not_exist=True, lock_field='updated_at')


def _get_active_backends(project_name: str) -> list[LoggingBackend]:
    try:
        config = get_logging_adapter(project_name).read()
    except Exception as e:
        from app.util import logger
        logger.error(f"Failed to load logging config for {project_name!r}: {e}")
        return []
    backends: list[LoggingBackend] = []
    if config.loki.is_active:
        backends.append(LokiBackend(project_name, config.loki))
    if config.file.is_active:
        backends.append(FileLogBackend(project_name, config.file))
    return backends


async def write_log(project_name: str, device_name: str, logmsg: str) -> None:
    """Write a log message to all active backends for a project."""
    for backend in _get_active_backends(project_name):
        await backend.write(device_name, logmsg)
