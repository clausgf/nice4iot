import datetime
from enum import Enum



class TelemetryBackend:
    """
    Abstract base class for telemetry data handling.
    """
    def __init__(self, project_name: str):
        self.project_name = project_name

    def write(self, device_name: str, values: dict, kind: str = 'default', timestamp: datetime.datetime | None = None):
        """
        Write telemetry data to the backend.

        :param device_name: Name of the device.
        :param values: Dictionary of telemetry values.
        :param kind: Type of telemetry data.
        :param timestamp: Timestamp of the telemetry data point. Defaults to current time if not provided.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def read(self, device_name: str, kind: str = 'default', start: datetime.datetime | None = None, end: datetime.datetime | None = None):
        """
        Read telemetry data from the Mimir backend.

        :param device_name: Name of the device.
        :param kind: Type of telemetry data.
        :param start: Start time for the data range. Defaults to None.
        :param end: End time for the data range. Defaults to None.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class Influx2Backend(TelemetryBackend):
    pass


class SqlBackend(TelemetryBackend):
    pass


class TelemetryBackendTypes(Enum):
    PROMETHEUS = 1
    INFLUX2 = 2
    SQL = 3
