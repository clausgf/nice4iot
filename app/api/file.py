from email.utils import formatdate
import hashlib
from pathlib import Path
from typing import Any
import anyio
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
import os
import stat
import json

from app.api.dependencies import DeviceAuthInfo, device_auth
from app.core.device import get_file_path
from app.util import logger
from app.config import app_config


###############################################################################

router = APIRouter()

##############################################################################

# https://stackoverflow.com/questions/69588611/how-using-browser-cache-when-fetching-files-from-fastapi
async def get_headers(file_path: Path) -> dict[str, str]:
    try:
        #stat_info = await anyio.to_thread.run_sync(os.stat, file_path)
        stat_info = file_path.stat()
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File at path {file_path} does not exist.")

    mode = stat_info.st_mode
    if not stat.S_ISREG(mode):
        raise RuntimeError(f"File at path {file_path} is not a file.")

    last_modified = formatdate(stat_info.st_mtime, usegmt=True)
    etag_base = f"{stat_info.st_mtime}-{stat_info.st_size}"
    etag = hashlib.md5(etag_base.encode()).hexdigest()

    headers = {
        "Cache-Control": "no-cache",
        "Content-Location": str(file_path),
        "Date": last_modified,
        "ETag": etag,
    }
    return headers

##############################################################################

@router.head(
        '/file/{project_name}/{device_name}/{filename}',
        summary="Get headers for a resource from the file system, but not the resource itself; if the device specific resource is not available, return a project wide default",
        response_description="The requested resource",
        responses={
            status.HTTP_200_OK: { "description": "File found with modifications" },
            status.HTTP_304_NOT_MODIFIED: { "description": "File found but not modified" },
            status.HTTP_404_NOT_FOUND: { "description": "File not found", "detail": "str" },
            status.HTTP_400_BAD_REQUEST: { "description": "Bad request", "detail": "str", },
        },
)
async def head_resource(
    project_name: str, 
    device_name: str, 
    filename: str,
    if_none_match: str | None = Header(default=None),
    dev: DeviceAuthInfo = Depends(device_auth)
):
    file_path = get_file_path(project_name, device_name, filename)
    headers = await get_headers(file_path)
    file_etag = headers['ETag'] # await get_etag(file_path)

    if if_none_match == file_etag:
        # shall return these headers: Cache-Control, Content-Location, Date, ETag, Expires, and Vary
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    else:
        # return all the headers
        return Response(status_code=status.HTTP_200_OK, headers=headers)

##############################################################################

@router.get(
        '/file/{project_name}/{device_name}/{filename}',
        summary="Get a resource from the file system; if the device specific resource is not available, return a project wide default",
        response_description="The requested resource",
)
async def get_resource(
    project_name: str, 
    device_name: str, 
    filename: str,
    if_none_match: str | None = Header(default=None),
    dev: DeviceAuthInfo = Depends(device_auth)
):
    file_path = get_file_path(project_name, device_name, filename)
    headers = await get_headers(file_path)
    file_etag = headers['ETag'] # await get_etag(file_path)

    if if_none_match == file_etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    else:
        return FileResponse(file_path, headers=headers)

##############################################################################

@router.put(
        '/file/{project_name}/{device_name}/{filename}',
        summary="Put a resource to the file system",
)
async def put_resource(
    project_name: str, 
    device_name: str, 
    filename: str,
    request: Request,
    dev: DeviceAuthInfo = Depends(device_auth)
):
    file_path = get_file_path(project_name, device_name, filename, check_file_exists=False)
    # write incoming body to file
    with Path(file_path).open("wb") as f:
        length = 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > app_config.max_upload_size:
                f.write(chunk[:length - app_config.max_upload_size])
                logger.info(f"Upload to {file_path} too large, max size {app_config.max_upload_size} bytes")
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
            else:
                f.write(chunk)
    logger.debug(f"wrote {length} bytes to {file_path}")
