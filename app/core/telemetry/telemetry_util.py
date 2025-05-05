from enum import Enum
from app.core.telemetry.prometheus.prometheus_telemetry import PrometheusBackend,PrometheusConfig
from app.core.telemetry.telemetry import Influx2Backend,SqlBackend

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