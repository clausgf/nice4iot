import datetime
from pydantic import BaseModel


class PrometheusConfig(BaseModel):
    """
    Configuration model for Prometheus / Grafana Mimir backend.
    """
    push_url: str = "http://localhost:8081/api/v1/metrics/write"
    pull_url : str = "http://localhost:9009/prometheus/api/v1/"
    default_pull_timeframe: datetime.timedelta = datetime.timedelta(hours=1)
    #auth: dict = None
    #project_name: str
    retention_policy: str = "default"
    write_timeout: int = 10
    read_timeout: int = 10


