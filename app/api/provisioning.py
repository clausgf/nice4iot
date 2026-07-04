"""
Device Provisioning API
=======================

Implements the two-tier authentication flow used by IoT devices:

  1. The device sends a long-lived **provisioning token** (shared secret,
     configured in the project settings) together with its own name.
  2. The server validates the token, optionally creates the device record,
     checks approval status, and issues a short-lived **bearer token**.
  3. The device uses the bearer token for all subsequent API calls
     (telemetry, logging, file, forwarding) until it expires.

Provisioning is intentionally idempotent: re-provisioning a device that already
exists produces a fresh bearer token while leaving the device record intact.
Expired bearer tokens are purged from the device record on each provisioning call.

Error handling
--------------
All 4xx errors from the provisioning flow are surfaced as-is (not normalized to
401) so that the device firmware can distinguish between configuration problems
(403 / not approved, project inactive) and token problems (401).
"""

import anyio
from fastapi import APIRouter, Body
from pydantic import BaseModel

from app.core.device.backend import device_provision
from app.core.project.backend import get_auth_project

###############################################################################

router = APIRouter()

###############################################################################


class ProvisioningRequest(BaseModel):
    """Request body for the provisioning endpoint."""
    projectName: str
    """Name of the project the device belongs to."""
    deviceName: str
    """Unique name of the device within the project. Used as a filesystem key."""
    provisioningToken: str
    """Long-lived shared secret configured in the project's provisioning token list."""


class ProvisioningResponse(BaseModel):
    """Successful provisioning response containing the device bearer token."""
    tokenType: str
    """Always ``"bearer"``."""
    accessToken: str
    """Short-lived bearer token. Send as ``Authorization: Bearer <accessToken>``
    in subsequent API requests. Expires after the project-configured duration
    (default: 7 days). Re-provision to obtain a fresh token before expiry."""


@router.post(
    '/provision',
    summary="Provision a device and obtain a bearer token",
    response_model=ProvisioningResponse,
    response_description="Bearer token for subsequent device API calls",
    responses={
        200: {
            "description": "Provisioning successful. Returns a new bearer token.",
            "content": {
                "application/json": {
                    "example": {"tokenType": "bearer", "accessToken": "aBcD1234..."}
                }
            },
        },
        400: {
            "description": (
                "Invalid project or device name "
                "(must contain only letters, digits, ``_``, ``-``, ``+``)."
            )
        },
        401: {
            "description": (
                "Provisioning token missing, too short (< 16 chars), "
                "expired, inactive, or not found in the project's token list."
            )
        },
        403: {
            "description": (
                "Project is inactive; **or** device exists but is inactive; "
                "**or** device is not approved for provisioning "
                "(``is_provisioning_approved=False`` and "
                "``is_provisioning_autoapproval=False`` on the project)."
            )
        },
        404: {
            "description": (
                "Project not found; **or** device does not exist and "
                "``is_autocreate_devices=False`` on the project."
            )
        },
    },
)
async def provision(provisioning_request: ProvisioningRequest = Body(...)) -> ProvisioningResponse:
    """
    Provision a device and return a short-lived bearer token.

    **Flow**

    1. Look up the project by ``projectName`` and validate the ``provisioningToken``
       against the project's provisioning token list. The token's ``last_use_at``
       timestamp is updated on success.
    2. If the device named ``deviceName`` does not yet exist:
       - If ``project.is_autocreate_devices=True``: create the device automatically.
         The new device's ``is_provisioning_approved`` flag is set to the value of
         ``project.is_provisioning_autoapproval``.
       - Otherwise: return 404.
    3. Record ``last_provisioning_request_at`` on the device.
    4. Reject with 403 if the device is inactive or not approved for provisioning.
    5. Purge expired bearer tokens from the device record.
    6. Create a new bearer token with lifetime ``project.device_tokens_expire_in``
       (default: 7 days) and append it to the device record.
    7. Return the new bearer token.

    **Token re-use**

    Calling this endpoint again before the previous token expires creates an
    additional token; the old token remains valid until it naturally expires or
    is purged on the next provisioning call. There is no explicit token revocation.

    **Idempotency**

    Safe to call on every device reboot. Expired tokens are cleaned up
    automatically so the number of active tokens per device stays bounded.
    """
    project = await anyio.to_thread.run_sync(
        lambda: get_auth_project(provisioning_request.projectName, provisioning_request.provisioningToken)
    )
    token = await anyio.to_thread.run_sync(
        lambda: device_provision(project, provisioning_request.deviceName)
    )
    return ProvisioningResponse(tokenType='bearer', accessToken=token)
