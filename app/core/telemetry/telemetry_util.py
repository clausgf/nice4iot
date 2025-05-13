import json,typing

from enum import Enum
from pydantic.tools import parse_obj_as

from app.core.telemetry.prometheus.prometheus_telemetry import PrometheusBackend,PrometheusConfig
from app.core.telemetry.telemetry import Influx2Backend,SqlBackend
from app.config import app_config

TEL_CONF_FILE_NAME = '.telemetry_config.json'

class TelemetryBackendTypes(Enum):
    PROMETHEUS = 1
    INFLUX2 = 2
    SQL = 3


def getTelBackendByEnum(type : TelemetryBackendTypes):
    match type:
        case TelemetryBackendTypes.PROMETHEUS :
            return PrometheusBackend
        case TelemetryBackendTypes.INFLUX2:
            return Influx2Backend
        case TelemetryBackendTypes.SQL:
            return SqlBackend
        
def getTelBackendConfigByEnum(type : TelemetryBackendTypes):
    match type:
        case TelemetryBackendTypes.PROMETHEUS :
            return PrometheusConfig
        
def create_tel(project_name: str, telemetry_backend: TelemetryBackendTypes):
    project_path = app_config.projects_dir / project_name
    tel_config_file = project_path / TEL_CONF_FILE_NAME
    temp_tel_conf_file = tel_config_file.with_suffix('.tmp')
    temp_tel_conf_file.write_text(getTelBackendConfigByEnum(telemetry_backend)().model_dump_json())
    temp_tel_conf_file.rename(tel_config_file)

def get_tel(project_name: str, telemetry_backend: TelemetryBackendTypes):
    project_path = app_config.projects_dir / project_name
    tel_conf_file_path = project_path / TEL_CONF_FILE_NAME
    with open(tel_conf_file_path) as f:
        tel_conf = parse_obj_as(getTelBackendConfigByEnum(telemetry_backend),json.loads(f.read()))
    return getTelBackendByEnum(telemetry_backend)(project_name,tel_conf)

def update_tel(project_name: str , telemetry_backend: TelemetryBackendTypes, config : dict[str,typing.Any]):
    tel_conf = get_tel(project_name,telemetry_backend).config
    for k,v in config.items():
        try:
            setattr(tel_conf,k,v)
        except AttributeError:
            pass
    project_path = app_config.projects_dir / project_name
    tel_config_file = project_path / TEL_CONF_FILE_NAME
    temp_tel_conf_file = tel_config_file.with_suffix('.tmp')
    temp_tel_conf_file.write_text(getTelBackendConfigByEnum(telemetry_backend)().model_dump_json())
    temp_tel_conf_file.rename(tel_config_file)