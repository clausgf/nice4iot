import typing
from pydantic import BaseModel, Field
from app.util import FILENAME_REGEX, URL_REGEX

class ForwardingConfig(BaseModel):
    """
    Defines a single forwarding rule for a project.

    A forwarding rule proxies incoming device requests to an upstream HTTP endpoint.
    Devices address a rule by its `name` in the URL; nice4iot then appends the
    remaining path and query parameters to `forward_url` and issues the request
    using `forward_method`.

    Example: a rule `{"name": "influx", "forward_url": "http://influx:8086/write", "forward_method": "POST"}`
    will forward `POST /forward/{project}/{device}/influx/db=mydb` to
    `http://influx:8086/write/db=mydb`.
    """
    name: str = Field(
        min_length=1,
        pattern=FILENAME_REGEX, 
        description='Unique name for the forwarding configuration. '
        'Only alphanumeric characters, underscores, and hyphens are allowed.')

    forward_method: typing.Literal["GET", "POST", "PUT", "HEAD", "DELETE"] = Field(
        default="GET",
        description='HTTP method to use for forwarding. '
        'The path and query parameters after the forwarding name '
        'in the original URL will be appended to the forward URL.')

    forward_url: str = Field(
        pattern=URL_REGEX,
        default='http://', 
        description='URL to forward to, e.g. http://example.com/api. '
        'The path and query parameters after the forwarding name '
        'in the original URL will be appended to this URL.')

    class Meta:
        description = (
            "Proxies device requests to an upstream endpoint. "
            "The remaining path and query parameters are appended to the forward URL.\n\n"
            "Example: `name=influx`, `forward_url=http://influx:8086/write`, `forward_method=POST` "
            "forwards `/forward/{prj}/{dev}/influx/db=mydb` → `http://influx:8086/write/db=mydb`."
        )
