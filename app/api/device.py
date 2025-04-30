from fastapi import APIRouter, HTTPException, Header, Request, Response, status
from fastapi.responses import JSONResponse
import os
import json
import numbers
from app.core.telemetry.prometheus.prometheus_telemetry import PrometheusBackend,PrometheusConfig
from app.core.project import get_project
from app.core.device import get_device

from app.util import logger, is_valid_filename


###############################################################################

router = APIRouter()

###############################################################################

@router.post('/telemetry/{project_name}/{device_name}/{kind}')
async def post_telemetry_with_names(project_name: str, device_name: str, kind: str, request: Request):
    """
    Post telemetry data to the time series database.
    """
    if not is_valid_filename(project_name) or not is_valid_filename(device_name) or not is_valid_filename(kind):
        raise HTTPException(status_code=400, detail='Invalid project, device, or kind')
    tel_backend = PrometheusBackend(project_name)
    get_project(project_name)
    get_device(device_name) # Both raise HTTPException if project or device does not exist.
    measurements = await request.json()
    #measurements = json.loads(request_json)
    for k,v in measurements.items(): #validate measurements before writing them
        if not (isinstance(k,str) and isinstance(v,numbers.Number)):
            return Response(status_code=400, detail='Not a valid measurement')
    await tel_backend.write(device_name,values=measurements,kind=kind)
    
    return Response(status_code=200)

# consumes = {MediaType.APPLICATION_JSON_VALUE})
# request body data

# ServiceUtils.checkAuthentication( projectName, deviceName );
# ServiceUtils.checkName( kind );

# // determine the device
# Device device = deviceService.findByProjectNameAndName(projectName, deviceName)
#         .orElseThrow(() -> new ResponseStatusException(
#                 HttpStatus.NOT_FOUND,
#                 "Device not found: projectName=" + projectName + " deviceName=" + deviceName));

# try {
#     timeseriesService.writeTelemetryJson(device, kind, data);
# } catch (JsonProcessingException e) {
#     throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
#             "Bad json body: " + e.getMessage());
# }
# return ResponseEntity.status(HttpStatus.OK).body("");

# ****************************************************************************

@router.post('/log/{project_name}/{device_name}')
async def post_log_with_names(project_name: str, device_name: str, request: Request):
    """
    Post log data to the time series database.
    """
    if not is_valid_filename(project_name) or not is_valid_filename(device_name):
        raise HTTPException(status_code=400, detail='Invalid project or device')
    get_project(project_name)
    get_device(device_name) # Both raise HTTPException if project or device does not exist.
    return Response(status_code=200)

#  consumes = "text/plain"
#  request body body

# ServiceUtils.checkAuthentication( projectName, deviceName );

# // determine the device
# Device device = deviceService.findByProjectNameAndName(projectName, deviceName)
#         .orElseThrow(() -> new ResponseStatusException(
#                 HttpStatus.NOT_FOUND,
#                 "Device not found: projectName=" + projectName + " deviceName=" + deviceName));

# timeseriesService.writeLog(device, body);
# return ResponseEntity.status(HttpStatus.OK).body("");

# ****************************************************************************

@router.get('/forward/{project_name}/{forwarding_name}')
async def get_forward_with_names(project_name: str, forwarding_name: str, request: Request):
    """
    Forward a GET request to another URL.
    """
    if not is_valid_filename(project_name) or not is_valid_filename(forwarding_name):
        raise HTTPException(status_code=400, detail='Invalid project or forwarding')
    return Response(status_code=200)

# @GetMapping(value = "/forward/{projectName}/{forwardingName}/**")
# headers, body, request

# ServiceUtils.checkAuthentication( projectName );
# ServiceUtils.checkName(forwardingName);

# Forwarding f = projectService.findForwardingByProjectNameAndForwardName(projectName, forwardingName)
#         .orElseThrow(() -> new ResponseStatusException(
#             HttpStatus.NOT_FOUND,
#             "Forwarding not found: projectName=" + projectName + " forwarding=" + forwardingName));
# if (!f.getEnableMethodGet()) {
#     throw new ResponseStatusException(
#             HttpStatus.FORBIDDEN,
#             "Method not enabled: projectName=" + projectName + " forwarding=" + forwardingName + " method=get");
# }

# String targetUrl = f.getForwardToUrl();
# if (f.getExtendUrl()) {
#     String path = apiConfiguration.getServletContextPath() + request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE).toString();
#     String remainingPath = new AntPathMatcher().extractPathWithinPattern(path, request.getRequestURI());
#     log.info("path={} remainingPath={}", path, remainingPath);
#     targetUrl = targetUrl + "/" + remainingPath;
# }
# log.info("Forwarding project={} forward={} url={}", projectName, forwardingName, targetUrl);

# try {
#     HttpEntity<Object> requestEntity = new HttpEntity<>(body, headers);
#     return restTemplate.exchange(
#             targetUrl,
#             HttpMethod.GET,
#             requestEntity,
#             String.class
#     );
# } catch (Exception e) {
#     log.info("Error forwarding request to url={}: {}", targetUrl, e.getMessage());
#     if (e instanceof HttpClientErrorException ex) {
#         return ResponseEntity
#                 .status(ex.getStatusCode())
#                 .headers(ex.getResponseHeaders())
#                 .body(ex.getResponseBodyAsString());
#     }
# }
# return ResponseEntity.status(HttpStatus.BAD_REQUEST).body("Unknown error forwarding the request (is the url valid?)");
