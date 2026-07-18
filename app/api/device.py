"""
Device Data API
===============

Endpoints used by provisioned devices to push telemetry, push log messages,
and proxy requests to upstream services (forwarding).

Authentication
--------------
Every endpoint requires a valid device bearer token obtained via ``POST /api/provision``.
Send it as::

    Authorization: Bearer <accessToken>

Authentication is handled by the ``device_auth`` dependency, which:

* Validates the ``Authorization`` header format.
* Looks up the project and device by the URL path parameters.
* Validates the token against the device's stored token list
  (checks: token value match, ``is_active=True``, not expired).
* Updates ``device.last_seen_at`` on every successful authentication.
* Raises **401** for any auth failure (missing header, wrong token, expired token,
  inactive/non-existent project or device). Auth errors are intentionally
  normalized to 401 — the device does not learn *why* authentication failed.
"""

import json
import anyio
from fastapi import APIRouter, HTTPException, Request, Response, status, Depends

from app.api.dependencies import DeviceAuthInfo, device_auth
from app.config import app_config
from app.core.telemetry.backend import write_telemetry
from app.core.logging.backend import write_log
from app.core.forwarding.backend import forward, get_forwarding
from app.exceptions import NotFoundError
from app.util import is_valid_filename

###############################################################################

router = APIRouter()

###############################################################################


@router.post(
    '/telemetry/{project_name}/{device_name}/{kind}',
    summary="Push telemetry measurements",
    response_description="Empty 200 on success",
    responses={
        200: {"description": "Measurements accepted and forwarded to the configured telemetry backend."},
        400: {
            "description": (
                "``kind`` contains invalid characters "
                "(must match ``[a-zA-Z0-9_+\\-]+``); "
                "**or** request body is not valid JSON."
            )
        },
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {"description": "Project or device not found."},
        413: {"description": "Payload exceeds ``app_config.max_telemetry_size`` (default: 8 KiB)."},
        502: {"description": "Telemetry backend unreachable or returned an error."},
    },
)
async def post_telemetry_with_names(
    project_name: str,
    device_name: str,
    kind: str,
    request: Request,
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Push a JSON object of numeric measurements to the telemetry backend.

    **Request body**

    A JSON object whose keys are metric names and values are numbers::

        Content-Type: application/json

        {
          "temperature": 22.4,
          "battery_V": 3.71,
          "wifi_rssi": -67,
          "boot_count": 12,
          "active_ms": 823
        }

    Nested objects are flattened into underscore-joined metric names
    (``{"env": {"temp": 22.4}}`` becomes ``env_temp``), so payloads may be
    hierarchical::

        {"env": {"temp": 22.4, "hum": 41}, "battery": {"V": 3.71}}

    Metric names are sanitized to the ``[a-zA-Z0-9_]`` character set common to
    all backends: any other character (dots, dashes, spaces, ...) is replaced
    with ``_`` (e.g. ``"cpu.load-1m"`` becomes ``cpu_load_1m``).

    Only numeric (float/int) leaf values are forwarded to the backend.
    Non-numeric fields (e.g. ``"status": "ok"``) are **silently ignored**;
    a warning is logged server-side. This allows mixed payloads without
    failing the entire measurement batch.

    The measurement **timestamp** is always the server arrival time (UTC).
    Devices cannot supply their own timestamp in the payload.

    **Path parameters**

    * ``project_name`` — project identifier (filesystem directory name).
    * ``device_name``  — device identifier within the project.
    * ``kind``         — measurement category label (e.g. ``sensors``, ``system``).
      Must be a valid filename (letters, digits, ``_``, ``-``, ``+``).
      Used as a tag/label in the telemetry backend.
      arduino4iot uses ``system`` for built-in metrics:
      ``battery_V``, ``wifi_rssi``, ``boot_count``, ``active_ms``.

    **Body size**

    Requests exceeding ``app_config.max_telemetry_size`` bytes are rejected
    with **413**. Intended default: **8 192 bytes**.

    **Backend**

    The telemetry backend and its connection settings are configured per project.
    Currently supported: Prometheus Remote Write (Protobuf + Snappy), InfluxDB line protocol.
    Metric names are derived from the JSON keys; the ``kind`` value is added as
    a label. Fields whose names end with ``_total`` are written as COUNTER type;
    all others as GAUGE.
    """
    if not is_valid_filename(kind):
        raise HTTPException(status_code=400, detail='Invalid kind in url')

    body = await request.body()
    if len(body) > app_config.max_telemetry_size:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail='Telemetry payload too large')
    try:
        measurements = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Request body is not valid JSON')
    await write_telemetry(project_name, device_name, values=measurements, kind=kind)
    return Response(status_code=200)


# ****************************************************************************


@router.post(
    '/log/{project_name}/{device_name}',
    summary="Push a plain-text log message",
    response_description="Empty 200 on success",
    responses={
        200: {"description": "Log message accepted and forwarded to the configured logging backend."},
        400: {"description": "Request body could not be decoded as UTF-8 text."},
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {"description": "Project or device not found."},
        413: {"description": "Payload exceeds ``app_config.max_log_size`` (default: 8 KiB)."},
        502: {"description": "Logging backend unreachable or returned an error."},
    },
)
async def post_log_with_names(
    project_name: str,
    device_name: str,
    request: Request,
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Push a plain-text log message to the configured logging backend.

    **Request body**

    Raw UTF-8 text — one or more log lines::

        Content-Type: text/plain

        [2024-01-15 12:34:56] I (app) sensor read ok
        [2024-01-15 12:34:57] W (net) wifi reconnecting

    The server does not impose a format on the log body; the entire body
    is forwarded verbatim to the backend together with the device name.
    The arduino4iot client sends ESP-IDF style log lines with the format
    ``[YYYY-MM-DD HH:MM:SS] <level> (<tag>) <message>``.

    **Path parameters**

    * ``project_name`` — project identifier.
    * ``device_name``  — device identifier; prepended to the log entry by the
      backend so that per-device log streams can be filtered.

    **Body size**

    Requests exceeding ``app_config.max_log_size`` bytes are rejected with
    **413**. Intended default: **8 192 bytes**.

    **Backend**

    Configured per project. Multiple backends can be active simultaneously:

    * **Loki** — pushes to Grafana Loki JSON push API. Timestamp is server
      arrival time (nanosecond Unix epoch). Device name is added as a label.
    * **File** — appends to ``<projects_dir>/<project>/<device>/.device.log``.
      Each entry is prefixed with the arrival timestamp and device name.
    """
    body = await request.body()
    if len(body) > app_config.max_log_size:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail='Log message too large')
    try:
        logmsg = body.decode()
    except Exception:
        raise HTTPException(status_code=400, detail='Request body is not valid UTF-8 text.')
    await write_log(project_name, device_name, logmsg)
    return Response(status_code=200)


# ****************************************************************************


@router.get(
    '/forward/{project_name}/{device_name}/{forwarding_name}/{remaining_url:path}',
    summary="Proxy a request to a configured upstream URL",
    response_description="Upstream response (status code, headers, and body forwarded verbatim)",
    responses={
        200: {"description": "Upstream responded with 200 (or another 2xx — forwarded verbatim)."},
        400: {
            "description": (
                "``forwarding_name`` contains invalid characters; "
                "**or** the forwarding config has no ``forward_url``."
            )
        },
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {
            "description": (
                "Project or device not found; "
                "**or** ``forwarding_name`` is not defined in the project's forwarding config."
            )
        },
        504: {"description": "Upstream request timed out (hard limit: 10 s)."},
    },
)
async def get_forward_with_names(
    project_name: str,
    device_name: str,
    forwarding_name: str,
    remaining_url: str,
    request: Request,
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Proxy the request to a configured upstream URL and return the upstream response.

    Forwarding configurations are defined per project in ``.forwards.json``
    (managed via the project settings UI or directly on the filesystem).
    Each entry maps a ``forwarding_name`` to a ``forward_url`` and an HTTP method.

    **URL construction**

    The upstream URL is assembled as::

        <forwarding.forward_url>/<remaining_url>?<query_params>

    A trailing slash on ``forward_url`` is removed before appending
    ``remaining_url`` to avoid double slashes.

    **Path parameters**

    * ``project_name``    — project identifier.
    * ``device_name``     — device identifier.
    * ``forwarding_name`` — name of a forwarding entry in the project config.
      Must be a valid filename (letters, digits, ``_``, ``-``, ``+``).
    * ``remaining_url``   — path suffix appended to ``forward_url`` (may be empty).

    **Request forwarding**

    All incoming request headers are forwarded **except**:

    * ``Authorization`` — stripped to prevent credential leakage to the upstream.
    * ``Content-Length`` — stripped; recalculated by the HTTP client library.

    Query parameters are forwarded unchanged.

    **HTTP method**

    The API endpoint itself is always ``GET`` (devices initiate a GET to nice4iot).
    The *upstream* request is sent with the method configured in the forwarding
    entry (``GET``, ``POST``, ``PUT``, ``HEAD``, or ``DELETE``). The request body
    (if any) is forwarded for ``POST``, ``PUT``, and ``DELETE``.

    **Timeout**

    Upstream requests time out after **10 seconds**. This also prevents infinite
    loops when a forwarding entry inadvertently points back at nice4iot itself.

    **Response**

    The upstream HTTP status code, headers, and body are forwarded verbatim.
    Non-2xx upstream responses are returned to the device as-is without
    raising a FastAPI exception.
    """
    if not is_valid_filename(forwarding_name):
        raise HTTPException(status_code=400, detail='Invalid forwarding_name in url')
    # Reject '..' segments in remaining_url to prevent upstream path traversal.
    if '..' in remaining_url.split('/'):
        raise HTTPException(status_code=400, detail='Path traversal not allowed in remaining_url')
    try:
        forwarding = await anyio.to_thread.run_sync(
            lambda: get_forwarding(project_name, forwarding_name)
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))

    headers = request.headers.mutablecopy()
    del headers["Authorization"]
    del headers["Content-Length"]
    data = await request.body()
    url_params = request.query_params
    try:
        forward_response = await forward(forwarding, remaining_url, data, headers, url_params, 10)
    except TimeoutError:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail='Upstream request timed out')

    return Response(
        status_code=forward_response.status_code,
        headers=forward_response.headers,
        content=forward_response.content,
    )
