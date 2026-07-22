from niceview.dataadapter import JsonAdapter

from app.config import app_config
from app.paths import project_dir
from app.core.logging.models import LoggingBackend, LoggingConfig
from app.core.logging.loki.backend import LokiBackend
from app.core.logging.file.backend import FileLogBackend

LOG_FILE = '.logging.json'


def get_logging_adapter(project_name: str) -> JsonAdapter:
    """Get a JsonAdapter for the logging configuration of a project."""
    return JsonAdapter(LoggingConfig, project_dir(project_name) / LOG_FILE,
                              create_if_not_exist=True, lock_field='updated_at')


def default_logging_config() -> LoggingConfig:
    """Build a LoggingConfig seeded from the DEFAULT_LOGGING_LOKI_* env vars, for
    new projects. An unset (empty) env value keeps the model default. Editable
    per project afterwards. The file-log backend has no env defaults (local)."""
    c = app_config
    cfg = LoggingConfig()
    lk = cfg.loki
    lk.is_active = c.default_logging_loki_enabled
    lk.log_url = c.default_logging_loki_url or lk.log_url
    lk.username = c.default_logging_loki_username or lk.username
    lk.password = c.default_logging_loki_password or lk.password
    lk.tenant_id = c.default_logging_loki_tenant_id or lk.tenant_id
    return cfg


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
    from app.health import set_health
    for backend in _get_active_backends(project_name):
        try:
            await backend.write(device_name, logmsg)
            set_health(f'{project_name}:logging', True)
        except Exception as e:
            set_health(f'{project_name}:logging', False, str(e))
