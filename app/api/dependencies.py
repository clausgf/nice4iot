from typing import Any
from fastapi import HTTPException, status, Request
from pydantic import BaseModel

from app.core.device import get_auth_project_device
from app.core.models import Device, Project


class DeviceAuthInfo(BaseModel):
    """
    Class to hold device authentication information.
    """
    project_name: str
    project: Project
    device_name: str
    device: Device


async def device_auth(project_name: str, device_name: str, request: Request) -> DeviceAuthInfo:
    """
    Authenticate the device using the provided project name, device name and bearer token from the request header.

    :param project_name: The name of the project.
    :param device_name: The name of the device.
    :param request: The FastAPI request object.
    :return: The authenticated device object.
    """
    # Extract the bearer token from the request header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header[:7].lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authentication token.")

    # Extract the token value
    token_value = auth_header.split(" ")[1]
    try:
        # Validate the token and get the project + device objects
        project, device = get_auth_project_device(project_name, device_name, token_value)
    except HTTPException as e:
        if 400 <= e.status_code < 500:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Project, device or auth token.")
    
    return DeviceAuthInfo(project_name=project_name, project=project, device_name=device_name, device=device)
