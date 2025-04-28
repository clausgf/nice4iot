import datetime
import json
import time
import httpx
from pydantic import BaseModel
import snappy

from app.core.telemetry.mimir import prom_spec_pb2, types_pb2


class PrometheusConfig(BaseModel):
    """
    Configuration model for Prometheus / Grafana Mimir backend.
    """
    url: str
    auth: dict = None
    project_name: str
    retention_policy: str = "default"
    write_timeout: int = 10
    read_timeout: int = 10


class PrometheusBackend:
    """
    Prometheus / Grafana Mimir backend for telemetry data bases on the Prometheus Remote Write Spec.
    """
    def __init__(self, project_name: str, config: dict):
        super().__init__(project_name)
        self.config = config
        self.client = None
        self.write_url = "http://localhost:8081/api/v1/metrics/write"

    async def write(self, device_name: str, values: dict, kind: str = 'default', timestamp: datetime.datetime | None = None):
        """
        Write telemetry data to the Mimir backend.

        :param device_name: Name of the device.
        :param values: Dictionary of telemetry values.
        :param kind: Type of telemetry data.
        :param timestamp: Timestamp of the telemetry data point. Defaults to current time if not provided.
        """
        wr = prom_spec_pb2.WriteRequest()

        metadata = types_pb2.MetricMetadata()
        metadata.type = types_pb2.MetricMetadata.MetricType.GAUGE  # 1
        metadata.metric_family_name = self.project_name
        #metadata.help = "4Iot telemetry data"
        #metadata.unit = "bytes"
        wr.metadata.append(metadata)

        device_label = types_pb2.Label(name='device', value=device_name)
        kind_label = types_pb2.Label(name='kind', value=kind)

        for k,v in values.items():
            # append to the timeseries
            ts = types_pb2.TimeSeries()

            name_label = types_pb2.Label(name="__name__", value=f'{self.project_name}_{k}')
            sample = types_pb2.Sample(timestamp=round(time.time() * 1000), value=v)

            ts.labels.append(name_label)
            ts.labels.append(device_label)
            ts.labels.append(kind_label)
            ts.samples.append(sample)

            wr.timeseries.append(ts)

        str_data = snappy.compress(wr.SerializeToString())
        headers = {
            "Content-Encoding": "snappy",
            "Content-Type": "application/x-protobuf",
            "User-Agent": "nice4iot",
            "X-Prometheus-Remote-Write-Version": "0.1.0"
        }
        async with httpx.AsyncClient() as client:
            r =  await client.post(self.write_url, data=str_data, headers=headers)
            print(r.status_code)
            print(r.content)

    async def read(self, device_name: str, kind: str = 'default', start: datetime.datetime | None = None, end: datetime.datetime | None = None):
        """
        Read telemetry data from the Mimir backend.

        :param device_name: Name of the device.
        :param kind: Type of telemetry data.
        :param start: Start time for the data range. Defaults to None.
        :param end: End time for the data range. Defaults to None.
        """
        # data = {
        #     "query": "testapi_test",
        #     "start": "2025-04-16T00:00:00%2B02:00",
        #     "end": "2025-04-16T13:30:00%2B02:00",
        #     "step": "15s"
        # }
        if start is not None:
            start = start.strftime("%Y-%m-%dT%H:%M:%S%z")
        data = json.dumps(data)
        async with httpx.AsyncClient() as client:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            r = await client.get(
                "http://localhost:9009/prometheus/api/v1/query_range?query=testapi_test&start=2025-04-16T00:00:00%2B02:00&end=2025-04-16T13:30:00%2B02:00&step=15s",
                headers=headers)
            
            #r = await client.post("http://localhost:9009/prometheus/api/v1/query_range",data=data,headers=headers)
            print(r.status_code)
            print(r.content)
