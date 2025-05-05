import datetime
import json
import time
import httpx
import asyncio
from pydantic import BaseModel
import snappy
from fastapi import HTTPException
from app.core.telemetry.telemetry import TelemetryBackend
from app.core.telemetry.prometheus import prom_spec_pb2,types_pb2

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


class PrometheusBackend(TelemetryBackend):
    """
    Prometheus / Grafana Mimir backend for telemetry data bases on the Prometheus Remote Write Spec.
    """
    def __init__(self, project_name: str, config: PrometheusConfig = PrometheusConfig()):
        super().__init__(project_name)
        self.config = config
        self.client = None

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
            async with asyncio.timeout(self.config.write_timeout):
                await client.post(self.config.push_url, data=str_data, headers=headers)

    async def read(self, device_name: str, kind: str = 'default', start: datetime.datetime | None = None, end: datetime.datetime | None = None, timeframe: datetime.timedelta | None = None):
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
        #Construct the query timeframe
        query_type = "query_range"
        if timeframe is None:
            timeframe = self.config.default_pull_timeframe
        if start is not None:
            if end is not None:
                pass
            else:
                end = start + timeframe
                if end > datetime.datetime.now():
                    end = datetime.datetime.now()
        else:
            if end is not None:
                start = end - timeframe
            else:
                query_type = "query" # Do an instant query if no timeframe can be constructed
        if query_type == "query_range":
            if start > end or end > datetime.date.now():
                raise HTTPException(status_code=400, detail="Invalid timeframe")
            start = start.strftime("%Y-%m-%dT%H:%M:%S%z")
            end = end.strftime("%Y-%m-%dT%H:%M:%S%z")
        #Construct the query
        #TODO enable more types of queries e.g. one metric for multiple devices
        query = f'{{__name__=~"{self.project_name}_.*", device={device_name}, kind={kind}}}' #Get all metrics for specific device and kind
        query_url = self.config.pull_url + '?' + query_type + "=" + query + "&start=" + start + "&end=" + end
        async with httpx.AsyncClient() as client:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            r = await client.get(
                query_url,
                headers=headers)
            
            #r = await client.post("http://localhost:9009/prometheus/api/v1/query_range",data=data,headers=headers)
            print(r.status_code)
            print(r.content)
