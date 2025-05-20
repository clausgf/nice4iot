from fastapi import APIRouter, HTTPException, Header, Request, Response, status, Depends
from fastapi.responses import JSONResponse

import numbers,json,httpx
from app.api.dependencies import DeviceAuthInfo,device_auth
from app.core.telemetry.telemetry import get_tel
from app.core.logging.logging import get_log
from app.core.project import get_project,get_project_path
from app.core.device import get_device
from app.core.forwarding.forwarding import forward, get_forwarding
from app.util import logger, is_valid_filename


###############################################################################

router = APIRouter()

###############################################################################
        
@router.post('/telemetry/{project_name}/{device_name}/{kind}')
async def post_telemetry_with_names(project_name: str, device_name: str, kind: str, request: Request, dev : DeviceAuthInfo = Depends(device_auth)):
    """
    Post telemetry data to the time series database.
    """
    if not is_valid_filename(kind):
        raise HTTPException(status_code=400, detail='Invalid kind in url')

    measurements = await request.json()
    #measurements = json.loads(request_json)
    tel_backend = get_tel(project_name, dev.project.telemetryBackend)
    await tel_backend.write(device_name, values=measurements, kind=kind)

    return Response(status_code=200)

# ****************************************************************************

@router.post('/log/{project_name}/{device_name}')
async def post_log_with_names(project_name: str, device_name: str, request: Request, dev : DeviceAuthInfo = Depends(device_auth)):
    """
    Post log data to the time series database.
    """
    log_backend = get_log(project_name, dev.project.loggingBackend)
    try:
        logmsg = (await request.body()).decode()
    except Exception as e:
        raise HTTPException(status_code=400, detail='Invalid logmsg')
    await log_backend.write(device_name, logmsg)
    return Response(status_code=200)

# ****************************************************************************

@router.get('/forward/{project_name}/{device_name}/{forwarding_name}/{remaining_url:path}')
async def get_forward_with_names(project_name: str, device_name: str, forwarding_name: str, remaining_url: str, request: Request, dev : DeviceAuthInfo = Depends(device_auth)):
    """
    Forward a GET request to another URL.
    """
    if not is_valid_filename(forwarding_name):
        raise HTTPException(status_code=400, detail='Invalid forwarding_name in url')
    forwarding = get_forwarding(project_name, forwarding_name)

    headers = request.headers.mutablecopy()
    del headers["Authorization"]   # Remove the Authorization header to avoid circular forwarding
    del headers["Content-Length"]
    data = await request.body()
    url_params = request.query_params
    forward_response = await forward(forwarding, remaining_url, data, headers,url_params, 10)

    return Response(status_code=forward_response.status_code, headers=forward_response.headers, content=forward_response.content)
