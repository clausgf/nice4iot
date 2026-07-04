from typing import Annotated
from pydantic import BaseModel, Field
import niceview


class InfluxLineConfig(BaseModel):
    """
    Pushes telemetry via InfluxDB Line Protocol over HTTP.
    Compatible with InfluxDB 1.x, InfluxDB 2.x, and VictoriaMetrics.
    """
    write_url: Annotated[str,
            Field(description=
                'Write endpoint URL.\n'
                'VictoriaMetrics: http://host:8428/write  — only this field needed, leave all others empty.\n'
                'InfluxDB 1.x: http://host:8086/write  — set database, optionally username/password.\n'
                'InfluxDB 2.x: http://host:8086/api/v2/write  — set org, bucket and token.')
        ] = "http://localhost:8086/write"
    database: Annotated[str,
            Field(description=
                'Database name (InfluxDB 1.x, sent as ?db=... query param). '
                'Leave empty for InfluxDB 2.x or VictoriaMetrics.')
        ] = ""
    org: Annotated[str,
            Field(description=
                'Organisation (InfluxDB 2.x only). '
                'Leave empty for InfluxDB 1.x or VictoriaMetrics.')
        ] = ""
    bucket: Annotated[str,
            Field(description=
                'Bucket (InfluxDB 2.x only, sent as ?bucket=... query param). '
                'Leave empty for InfluxDB 1.x or VictoriaMetrics.')
        ] = ""
    username: Annotated[str,
            Field(description=
                'Username for Basic Auth (InfluxDB 1.x). '
                'Leave empty for token auth, VictoriaMetrics, or no auth.')
        ] = ""
    password: Annotated[str,
            Field(description='Password for Basic Auth (InfluxDB 1.x).'),
            niceview.Field(password=True)
        ] = ""
    token: Annotated[str,
            Field(description=
                'Bearer token (InfluxDB 2.x). '
                'Leave empty for Basic Auth, VictoriaMetrics, or no auth.'),
            niceview.Field(password=True)
        ] = ""
    timeout: Annotated[int,
            Field(description='HTTP request timeout in seconds.')
        ] = 10
