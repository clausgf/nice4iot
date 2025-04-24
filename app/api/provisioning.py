from fastapi import APIRouter, Body, HTTPException, Header, Request, Response, status
from fastapi.responses import JSONResponse
import os
import json

from pydantic import BaseModel

from app.core.device import device_provision
from app.core.project import get_auth_project, get_project
from app.util import logger, is_valid_filename


###############################################################################

router = APIRouter()

###############################################################################

class ProvisioningRequest(BaseModel):
    projectName: str
    deviceName: str
    provisioningToken: str


class ProvisioningResponse(BaseModel):
    tokenType: str
    accessToken: str


@router.post(
    '/provision',
    summary="Provision (and optionally create) a device",
    response_description="Authentication token",
    responses={
        200: { "description": "Provisioning successful" },
        400: { "description": "Invalid project or device name" },
        401: { "description": "Missing or invalid or expired provisioning token" },
        403: { "description": "Project or device not active or provisioning not approved" },
        404: { "description": "Project or device not found" },
    },
)
async def provision(provisioning_request: ProvisioningRequest = Body(...)) -> ProvisioningResponse:
    project = get_auth_project(provisioning_request.projectName, provisioning_request.provisioningToken)
    token = device_provision(project, provisioning_request.deviceName)
    return ProvisioningResponse(tokenType='bearer', accessToken=token)
