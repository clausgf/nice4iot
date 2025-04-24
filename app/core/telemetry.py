import datetime


def flatten_dict(d, parent_key: str = "", sep: str = "_"):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


class TelemetryBackend:
    """
    Abstract base class for telemetry data handling.
    """
    def __init__(self, project_name: str):
        self.project_name = project_name

    def write(self, values: dict, device_name: str, kind: str = 'default', timestamp: datetime.datetime | None = None):
        """
        Write telemetry data to the backend.

        :param values: Dictionary of telemetry values.
        :param device_name: Name of the device.
        :param kind: Type of telemetry data.
        :param timestamp: Timestamp of the telemetry data point. Defaults to current time if not provided.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class Influx2Backend(TelemetryBackend):
    """
    InfluxDB backend for telemetry data.
    """
    def __init__(self, project_name: str, config: dict):
        super().__init__(project_name)
        self.config = config
        self.client = None

    def write(self, values: dict, device_name: str, kind: str = 'default', timestamp: datetime.datetime | None = None):
        timestamp = timestamp or datetime.datetime.now(datetime.timezone.utc)
        payload = flatten_dict(payload)
    
    def read(self, device_name: str, kind: str = 'default', start: datetime.datetime | None = None, end: datetime.datetime | None = None):
        """
        Read telemetry data from the backend.

        :param device_name: Name of the device.
        :param kind: Type of telemetry data.
        :param start: Start time for the data range. Defaults to None.
        :param end: End time for the data range. Defaults to None.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class SqlBackend(TelemetryBackend):
    pass


class MimirBackend(TelemetryBackend):
    pass
