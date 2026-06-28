import json
from enum import Enum
from pydantic import TypeAdapter

from app.core.logging.loki.logging_loki_backend import LokiBackend, LokiConfig
from app.core.logging.file.logging_file_backend import FileLogBackend, FileLogConfig
from app.config import app_config

LOG_CONF_FILE_NAME = '.logging_config.json'

class LoggingBackendTypes(Enum):
    LOKI = 1
    FILE = 2

def getLogBackendConfigByEnum(logBackend: LoggingBackendTypes):
    match logBackend:
        case LoggingBackendTypes.LOKI:
            return LokiConfig
        case LoggingBackendTypes.FILE:
            return FileLogConfig

def getLogBackendByEnum(logBackend: LoggingBackendTypes):
    match logBackend:
        case LoggingBackendTypes.LOKI:
            return LokiBackend
        case LoggingBackendTypes.FILE:
            return FileLogBackend
        
def create_log(project_name: str,logBackend: LoggingBackendTypes):
    project_path = app_config.projects_dir / project_name
    log_config_file = project_path / LOG_CONF_FILE_NAME
    temp_log_conf_file = log_config_file.with_suffix('.tmp')
    temp_log_conf_file.write_text(getLogBackendConfigByEnum(logBackend)().model_dump_json(indent=2))
    temp_log_conf_file.rename(log_config_file)

def get_log(project_name: str,logBackend: LoggingBackendTypes):
    project_path = app_config.projects_dir / project_name
    log_conf_file_path = project_path / LOG_CONF_FILE_NAME
    with open(log_conf_file_path) as f:
        log_conf = TypeAdapter(getLogBackendConfigByEnum(logBackend)).validate_python(json.loads(f.read()))
    return getLogBackendByEnum(logBackend)(project_name,log_conf)

