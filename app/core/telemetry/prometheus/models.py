from typing import Annotated
from pydantic import BaseModel, Field
import niceview


class PrometheusConfig(BaseModel):
    """
    Pushes telemetry via Prometheus Remote Write (Protobuf + Snappy).
    Compatible with Grafana Mimir, VictoriaMetrics, Thanos, and Prometheus 2.x.
    """
    push_url: Annotated[str,
            Field(description=
                'Remote Write endpoint URL.\n'
                'Grafana Mimir: http://mimir:8080/api/v1/push\n'
                'VictoriaMetrics: http://victoriametrics:8428/api/v1/write\n'
                'Prometheus: http://prometheus:9090/api/v1/write')
        ] = "http://localhost:8081/api/v1/push"
    pull_url: Annotated[str,
            Field(description=
                'PromQL query API base URL (used for reading back data, e.g. on the Data tab).\n'
                'Grafana Mimir: http://mimir:9009/prometheus/api/v1/\n'
                'VictoriaMetrics: http://victoriametrics:8428/api/v1/\n'
                'Prometheus: http://prometheus:9090/api/v1/')
        ] = "http://localhost:9009/prometheus/api/v1/"
    username: Annotated[str,
            Field(description='Username for Basic Auth. Leave empty to disable auth.')
        ] = ""
    password: Annotated[str,
            Field(description='Password for Basic Auth.'),
            niceview.Field(password=True)
        ] = ""
    write_timeout: Annotated[int,
            Field(description='HTTP write timeout in seconds.')
        ] = 10
    read_timeout: Annotated[int,
            Field(description='HTTP read timeout in seconds.')
        ] = 10
