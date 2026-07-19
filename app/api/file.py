"""
Device File API
===============

Provides device-specific file storage with per-project fallback.
Primary use cases:

* **Config delivery** — serve per-device or project-wide configuration files
  to devices on demand (e.g. ``config.json``, ``ca.crt``).
* **OTA firmware updates** — serve firmware binaries (e.g. ``firmware.bin``).
* **Device uploads** — receive small files pushed by devices (e.g. diagnostic dumps).

File lookup for GET and HEAD
----------------------------
Files are looked up in two locations:

1. ``<projects_dir>/<project>/<device>/<filename>``  (device-specific)
2. ``<projects_dir>/<project>/<filename>``           (project-wide fallback)

The device-specific file takes priority. If neither exists, 404 is returned.

PUT always writes to the device-specific path.

Cache-validation (ETag / If-None-Match / Last-Modified / If-Modified-Since)
----------------------------------------------------------------------------
All responses include an ``ETag`` header (MD5 of ``mtime + file_size``) and a
``Last-Modified`` header (the file's mtime). Clients can use either validator:
send the cached ETag as ``If-None-Match``, or the cached ``Last-Modified``
value as ``If-Modified-Since``, on subsequent requests. When the file has not
changed, the server returns 304 and the client reuses its cached copy — this
minimises download traffic for firmware that has not changed.

Per RFC 7232 §3.3, if a request carries both headers, ``If-None-Match`` is
authoritative and ``If-Modified-Since`` is ignored.

Authentication
--------------
All endpoints require a valid device bearer token (see ``POST /api/provision``).
Send it as ``Authorization: Bearer <accessToken>``.
"""

from email.utils import formatdate, parsedate_to_datetime
import hashlib
from pathlib import Path
import anyio
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from fastapi.responses import FileResponse
import os
import stat

from app.api.dependencies import DeviceAuthInfo, device_auth
from app.core.device.backend import get_file_path
from app.core.file.backend import get_file_config
from app.exceptions import NotFoundError
from app.util import logger, is_valid_upload_filename

###############################################################################

router = APIRouter()

###############################################################################


async def get_headers(file_path: Path) -> dict[str, str]:
    """
    Compute and return caching headers for the given file path.

    Returns a dict with: ``Cache-Control``, ``Content-Location``,
    ``Last-Modified``, and ``ETag``. The ETag is an MD5 hex digest of
    ``"<mtime>-<size>"``. ``Last-Modified`` is the file's mtime (the actual
    ``Date`` response header — when the response was generated — is added
    automatically by the ASGI server and must not be set here).

    :raises HTTPException 404: File does not exist.
    :raises RuntimeError: Path exists but is not a regular file.
    """
    try:
        stat_info = await anyio.to_thread.run_sync(os.stat, file_path)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File not found: {file_path.name}")

    mode = stat_info.st_mode
    if not stat.S_ISREG(mode):
        raise RuntimeError(f"Path {file_path} is not a regular file.")

    last_modified = formatdate(stat_info.st_mtime, usegmt=True)
    etag_base = f"{stat_info.st_mtime}-{stat_info.st_size}"
    etag = hashlib.md5(etag_base.encode()).hexdigest()

    return {
        "Cache-Control": "no-cache",
        "Content-Location": str(file_path),
        "Last-Modified": last_modified,
        "ETag": etag,
    }


def _is_not_modified(headers: dict[str, str], if_none_match: str | None,
                      if_modified_since: str | None) -> bool:
    """
    Evaluate conditional-GET/HEAD headers against the file's current cache headers.

    Per RFC 7232 §3.3, ``If-Modified-Since`` is only evaluated when
    ``If-None-Match`` is absent from the request.
    """
    if if_none_match is not None:
        return if_none_match == headers["ETag"]
    if if_modified_since is not None:
        try:
            since = parsedate_to_datetime(if_modified_since)
            last_modified = parsedate_to_datetime(headers["Last-Modified"])
        except (TypeError, ValueError):
            return False
        return last_modified <= since
    return False


###############################################################################


@router.head(
    '/file/{project_name}/{device_name}/{filename}',
    summary="Check whether a file exists and retrieve its cache headers",
    response_description="Cache headers (ETag, Cache-Control, Date, Content-Location)",
    responses={
        200: {
            "description": (
                "File found. Response headers include ``ETag``, ``Cache-Control``, "
                "``Last-Modified``, and ``Content-Location``. No response body."
            )
        },
        304: {
            "description": (
                "File found but ``If-None-Match`` or ``If-Modified-Since`` indicates "
                "the client's cached copy is still valid. No response body."
            )
        },
        400: {"description": "Filename contains invalid characters or path traversal sequences."},
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {
            "description": (
                "Neither a device-specific nor a project-wide file with this name exists."
            )
        },
    },
)
async def head_resource(
    project_name: str,
    device_name: str,
    filename: str,
    if_none_match: str | None = Header(default=None),
    if_modified_since: str | None = Header(default=None),
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Return cache headers for a file without transferring its contents.

    Useful for checking whether a new firmware or config file is available
    before deciding to download it. The ETag/Last-Modified can be compared
    locally without issuing a full GET.

    **File lookup**: device-specific path first, project-wide fallback if not found.

    **If-None-Match** / **If-Modified-Since**: if the request includes
    ``If-None-Match: <etag>`` and the ETag matches the current file, or
    ``If-Modified-Since: <date>`` and the file has not changed since that
    date, responds with **304 Not Modified**. If both are present,
    ``If-None-Match`` alone decides (RFC 7232 §3.3).
    """
    if not is_valid_upload_filename(filename):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid filename: {filename!r}")
    try:
        file_path = get_file_path(project_name, device_name, filename)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    headers = await get_headers(file_path)

    if _is_not_modified(headers, if_none_match, if_modified_since):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(status_code=status.HTTP_200_OK, headers=headers)


###############################################################################


@router.get(
    '/file/{project_name}/{device_name}/{filename}',
    summary="Download a file (device-specific or project-wide fallback)",
    response_description="File contents with cache headers",
    responses={
        200: {
            "description": (
                "File contents. Response includes ``ETag``, ``Cache-Control``, "
                "``Last-Modified``, and ``Content-Location`` headers."
            )
        },
        304: {
            "description": (
                "``If-None-Match`` or ``If-Modified-Since`` indicates the file has not "
                "changed since the client last downloaded it. No response body."
            )
        },
        400: {"description": "Filename contains invalid characters or path traversal sequences."},
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {
            "description": (
                "Neither a device-specific nor a project-wide file with this name exists."
            )
        },
    },
)
async def get_resource(
    project_name: str,
    device_name: str,
    filename: str,
    if_none_match: str | None = Header(default=None),
    if_modified_since: str | None = Header(default=None),
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Download a file from device-specific storage or the project-wide fallback.

    **File lookup** (in order):

    1. ``<projects_dir>/<project>/<device>/<filename>`` — device-specific file.
    2. ``<projects_dir>/<project>/<filename>`` — project-wide default.

    If neither exists, returns **404**.

    **ETag / Last-Modified caching**

    The response always includes ``ETag`` and ``Last-Modified`` headers. On
    subsequent requests, send the received ETag as ``If-None-Match: <etag>``,
    or the received ``Last-Modified`` value as ``If-Modified-Since: <date>``;
    the server returns **304 Not Modified** without a body if the file has
    not changed. If both conditional headers are sent, ``If-None-Match``
    alone decides (RFC 7232 §3.3). This is the recommended pattern for
    firmware OTA: the device checks with HEAD or GET + a conditional header
    on every boot and skips the download when the file is unchanged.
    """
    if not is_valid_upload_filename(filename):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid filename: {filename!r}")
    try:
        file_path = get_file_path(project_name, device_name, filename)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    headers = await get_headers(file_path)

    if _is_not_modified(headers, if_none_match, if_modified_since):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return FileResponse(file_path, headers=headers)


###############################################################################


@router.put(
    '/file/{project_name}/{device_name}/{filename}',
    summary="Upload a file to device-specific storage",
    response_description="Empty 200 on success",
    responses={
        200: {"description": "File written successfully."},
        400: {"description": "Filename contains invalid characters or path traversal sequences."},
        401: {"description": "Missing, invalid, or expired bearer token."},
        404: {"description": "Project or device not found."},
        413: {
            "description": (
                "File exceeds ``app_config.max_file_upload_size`` (default: 10 MiB). "
                "No partial file is left on disk."
            )
        },
    },
)
async def put_resource(
    project_name: str,
    device_name: str,
    filename: str,
    request: Request,
    dev: DeviceAuthInfo = Depends(device_auth),
) -> Response:
    """
    Upload a file to the device-specific directory.

    The request body is written verbatim to::

        <projects_dir>/<project>/<device>/<filename>

    The file is created if it does not exist; overwritten if it does.
    Writing always goes to the **device-specific** path — there is no way
    for a device to write to the project-wide fallback path via this endpoint.

    **Filename validation**

    Only alphanumeric characters, ``.``, ``_``, and ``-`` are allowed.
    The filename must start with an alphanumeric character; ``..`` is forbidden.
    Invalid filenames are rejected with **400**.

    **Size limit**

    The upload is streamed and the size is checked chunk by chunk.
    If the total body length exceeds ``app_config.max_file_upload_size`` (default: 10 MiB),
    the temporary file is deleted and **413** is returned.
    No partial data is left on disk (atomic upload).

    **Content-Type**

    Not validated; the file is stored as raw bytes regardless of content type.
    """
    if not is_valid_upload_filename(filename):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid filename: {filename!r}")
    try:
        file_path = get_file_path(project_name, device_name, filename, check_file_exists=False)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ValueError as e:
        # Same mapping as GET/HEAD: an invalid name is a bad request, not a miss.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    file_config = await anyio.to_thread.run_sync(lambda: get_file_config(project_name))
    max_size = file_config.max_upload_size
    tmp_path = file_path.with_name(file_path.name + '.upload.tmp')

    # Collect the upload body into memory (bounded by max_size) before writing
    # to disk.  This keeps the async streaming loop on the event loop thread
    # while pushing the blocking write/rename to a worker thread.
    chunks: list[bytes] = []
    length = 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > max_size:
            logger.info(f"Upload to {file_path} too large ({length} bytes, limit {max_size})")
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="File too large")
        chunks.append(chunk)
    content = b''.join(chunks)

    def _write_atomic() -> None:
        tmp_path.write_bytes(content)
        tmp_path.rename(file_path)

    try:
        await anyio.to_thread.run_sync(_write_atomic)
    except Exception:
        await anyio.to_thread.run_sync(lambda: tmp_path.unlink(missing_ok=True))
        raise
    logger.debug(f"wrote {length} bytes to {file_path}")
    return Response(status_code=200)
