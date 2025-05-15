import json,typing

from pydantic import BaseModel
from pydantic.tools import parse_obj_as

from app.core.telemetry.models import TelemetryBackend, TelemetryBackendTypes
from app.core.telemetry.prometheus.prometheus_telemetry import PrometheusBackend,PrometheusConfig
from app.config import app_config

TEL_CONF_FILE_NAME = '.telemetry_config.json'


def flatten_dict(d, parent_key: str = "", sep: str = "_"):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def getTelBackendByEnum(type : TelemetryBackendTypes) -> TelemetryBackend:
    match type:
        case TelemetryBackendTypes.PROMETHEUS :
            return PrometheusBackend
        # case TelemetryBackendTypes.INFLUX2:
        #     return Influx2Backend
        # case TelemetryBackendTypes.SQL:
        #     return SqlBackend


def getTelBackendConfigByEnum(type : TelemetryBackendTypes) -> BaseModel:
    match type:
        case TelemetryBackendTypes.PROMETHEUS :
            return PrometheusConfig


def create_tel(project_name: str, telemetry_backend: TelemetryBackendTypes):
    project_path = app_config.projects_dir / project_name
    tel_config_file = project_path / TEL_CONF_FILE_NAME
    temp_tel_conf_file = tel_config_file.with_suffix('.tmp')
    temp_tel_conf_file.write_text(getTelBackendConfigByEnum(telemetry_backend)().model_dump_json(indent=2))
    temp_tel_conf_file.rename(tel_config_file)


def get_tel(project_name: str, telemetry_backend: TelemetryBackendTypes) -> TelemetryBackend:
    project_path = app_config.projects_dir / project_name
    tel_conf_file_path = project_path / TEL_CONF_FILE_NAME
    with open(tel_conf_file_path) as f:
        tel_conf = getTelBackendConfigByEnum(telemetry_backend).model_validate_json(f.read())
    tel_backend_class = getTelBackendByEnum(telemetry_backend)
    return tel_backend_class(project_name, tel_conf)


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
    temp_tel_conf_file.write_text(getTelBackendConfigByEnum(telemetry_backend)().model_dump_json(indent=2))
    temp_tel_conf_file.rename(tel_config_file)

