import anyio
from typing import Never
from fastapi import HTTPException, status, Request
from pydantic import BaseModel

from app.core.device.backend import get_auth_project_device
from app.core.device.models import Device
from app.core.project.models import Project
from app.exceptions import AlreadyExistsError, AuthError, ForbiddenError, Nice4IotError, NotFoundError


class DeviceAuthInfo(BaseModel):
    """
    Class to hold device authentication information.
    """
    project_name: str
    project: Project
    device_name: str
    device: Device


def domain_to_http(exc: Nice4IotError) -> Never:
    """Map a domain exception to an HTTPException and raise it.

    Provides a single place for the API layer to convert domain errors to HTTP
    status codes. Callers should use ``raise domain_to_http(exc)`` (the Never
    return type prevents dead-code warnings).
    """
    if isinstance(exc, NotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, AlreadyExistsError):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, AuthError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


async def device_auth(project_name: str, device_name: str, request: Request) -> DeviceAuthInfo:
    """
    Authenticate the device using the provided project name, device name and bearer token from the request header.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :param request: The FastAPI request object.
    :return: The authenticated device object.
    """
    scheme, _, token_value = (request.headers.get("Authorization") or '').partition(" ")
    token_value = token_value.strip()
    if scheme.lower() != "bearer" or not token_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authentication token.")
    try:
        project, device = await anyio.to_thread.run_sync(
            lambda: get_auth_project_device(project_name, device_name, token_value)
        )
    except Nice4IotError:
        # All auth errors are normalized to 401 — devices must not learn why auth failed.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid project, device or auth token.")

    return DeviceAuthInfo(project_name=project_name, project=project, device_name=device_name, device=device)
