import datetime,pytz,time,numbers
import httpx,asyncio
from pydantic import BaseModel
import snappy
from fastapi import HTTPException
from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.telemetry import TelemetryBackend
from app.core.telemetry.prometheus import prom_spec_pb2,types_pb2
from app.config import app_config
from app.util import logger

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

        device_label = types_pb2.Label(name='device', value=device_name)
        kind_label = types_pb2.Label(name='kind', value=kind)

        for k, v in values.items():
            if not isinstance(v, numbers.Number):
                logger.debug(f"Skipping non-numeric telemetry field '{k}' from {device_name}: {v!r}")
                continue

            # Fields ending in _total follow the Prometheus counter convention
            is_counter = k.endswith('_total')
            metric_type = (types_pb2.MetricMetadata.MetricType.COUNTER if is_counter
                           else types_pb2.MetricMetadata.MetricType.GAUGE)
            metric_name = f'{self.project_name}_{k}'

            metadata = types_pb2.MetricMetadata()
            metadata.type = metric_type
            metadata.metric_family_name = metric_name
            wr.metadata.append(metadata)

            # append to the timeseries
            ts = types_pb2.TimeSeries()

            name_label = types_pb2.Label(name="__name__", value=metric_name)
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

    async def read(self,metrics: str = ".*", device_name: str = ".*", kind: str = '.*', start: datetime.datetime | None = None, end: datetime.datetime | None = None, timeframe: datetime.timedelta | None = None,step : str = '15s'):
        """
        Read telemetry data from the Mimir backend.
        Constructs a query timeframe based on the passed parameters:
        If start and end are passed, those are used. If only start or end are passed it constructs a timeframe by respectively adding or subtracting the passed timeframe.
        If no timeframe is passed as a function argument it uses the default timeframe in the config.
        If both start and end are not passed, an instant query is constructed.
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
                if end > datetime.datetime.now(pytz.timezone(app_config.timezone)):
                    end = datetime.datetime.now(pytz.timezone(app_config.timezone))
        else:
            if end is not None:
                start = end - timeframe
            else:
                query_type = "query" # Do an instant query if no timeframe can be constructed
        if query_type == "query_range":
            if start > end or end > datetime.datetime.now(pytz.timezone(app_config.timezone)):
                raise HTTPException(status_code=400, detail="Invalid timeframe")
            start = start.isoformat() #start.strftime("%Y-%m-%dT%H:%M:%S%z")
            end = end.isoformat()#end.strftime("%Y-%m-%dT%H:%M:%S%z")
        logger.error(f'Timestamps:{start},{end}')
        #Construct the query
        #TODO enable more types of queries e.g. one metric for multiple devices
        query = f'{{__name__=~"{self.project_name}_{metrics}", device=~"{device_name}", kind=~"{kind}"}}&step={step}' #Get all metrics for specific device and kind
        if start and end:
            query = query + f'&start={start}&end={end}'
        query = query.replace('+','%2B')
        query_url = f'{self.config.pull_url}{query_type}?query={query}' 
        logger.error(f'Read query:{query_url}')
        async with httpx.AsyncClient() as client:
            #async with asyncio.Timeout(self.config.read_timeout):
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            r = await client.get(
                query_url,
                headers=headers)
        if r.status_code == 200:
            return r.json()["data"]["result"]
        return []
