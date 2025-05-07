import json

from enum import Enum
from pydantic.tools import parse_obj_as

from app.core.telemetry.prometheus.prometheus_telemetry import PrometheusBackend,PrometheusConfig
from app.core.telemetry.telemetry import Influx2Backend,SqlBackend
from app.config import app_config

TEL_CONF_FILE_NAME = '.telemetry_config.json'

class BackendTypes(Enum):
    PROMETHEUS = 1
    INFLUX2 = 2
    SQL = 3


def getBackendByEnum(type : BackendTypes):
    match type:
        case BackendTypes.PROMETHEUS :
            return PrometheusBackend
        case BackendTypes.INFLUX2:
            return Influx2Backend
        case BackendTypes.SQL:
            return SqlBackend
        
def getBackendConfigByEnum(type : BackendTypes):
    match type:
        case BackendTypes.PROMETHEUS :
            return PrometheusConfig
        
def create_tel(project_name: str, telemetry_backend: BackendTypes):
        project_path = app_config.projects_dir / project_name
        tel_config_file = project_path / TEL_CONF_FILE_NAME
        temp_tel_conf_file = tel_config_file.with_suffix('.tmp')
        temp_tel_conf_file.write_text(getBackendConfigByEnum(telemetry_backend)().model_dump_json())
        temp_tel_conf_file.rename(tel_config_file)

def get_tel(project_name: str, telemetry_backend: BackendTypes):
    project_path = app_config.projects_dir / project_name
    tel_conf_file_path = project_path / TEL_CONF_FILE_NAME
    with open(tel_conf_file_path) as f:
        tel_conf = parse_obj_as(getBackendConfigByEnum(telemetry_backend),json.loads(f.read()))
    return getBackendByEnum(telemetry_backend)(project_name,tel_conf)