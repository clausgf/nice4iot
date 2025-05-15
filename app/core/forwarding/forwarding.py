import json,httpx,asyncio

from fastapi import HTTPException, status

from app.util import logger
from app.core.project import get_project_path
from app.core.forwarding.models import ForwardingModel, ForwardingModelList


###############################################################################

FORWARD_FILE_NAME = '.forwards.json'

###############################################################################

def get_forwadings(project_name : str) -> ForwardingModelList:
    """Get the forwardings for a project."""
    forwardings_filename = get_project_path(project_name) / FORWARD_FILE_NAME
    if forwardings_filename.is_file():
        with open(forwardings_filename, 'r') as f:
            forward_dict = ForwardingModelList.model_validate_json(f.read())
    else:
        # create a new (empty) forwardings object
        forward_dict = ForwardingModelList()
    return forward_dict


def get_forwarding(project_name: str, forwarding_name: str) -> ForwardingModel:
    """
    Get a specific forwarding by name.

    :param project_name: The name of the project.
    :param forwarding_name: The name of the forwarding.
    :return: The forwarding model.
    :raises HTTPException: If the project path is invalid (400 Bad Request).
    """
    forward_dict = get_forwadings(project_name)
    forwarding = forward_dict.forwards.get(forwarding_name)
    if not forwarding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forwarding not found")
    
    return forwarding


def update_forwadings(project_name: str, forwarding_model_list: ForwardingModelList) -> ForwardingModelList:
    """
    Update (save) the forwardings for a project.

    :param project_name: The name of the project.
    :param forwarding_model_list: The forwarding model list to save.
    :return: The saved forwarding model list.
    :raises HTTPException: If the project path is invalid (400 Bad Request).
    """
    forwardings_filename = get_project_path(project_name) / FORWARD_FILE_NAME
    try:
        temp_file = forwardings_filename.with_suffix('.tmp')
        temp_file.write_text(forwarding_model_list.model_dump_json())
        temp_file.rename(forwardings_filename)
    except Exception as e:
        logger.error(f"Error saving forwardings {forwardings_filename}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error saving forwardings: {str(e)}")
    return forwarding_model_list

###############################################################################

async def forward(forwarding: ForwardingModelList, remaining_url: str, data: str, headers: dict, timeout: int):
    """
    Forward a request to another URL.
    :param forwarding: The forwarding model.
    :param url_path: The URL path suffix to forward to.
    :param data: The data to send in the request.
    :param headers: The headers to send in the request.
    :param timeout: The timeout for the request.
    :return: The response from the forwarded request.
    :raises HTTPException: If the forwarding URL is invalid (400 Bad Request).
    """
    # rewrite the url_path to the forwarding url
    fwd_url_prefix = forwarding.forward_url
    if not fwd_url_prefix:
        raise HTTPException(status_code=400, detail='Invalid forwarding url')
    if fwd_url_prefix.endswith("/"):
        fwd_url_prefix = fwd_url_prefix[:-1]
    if remaining_url.startswith("/"):
        remaining_url = remaining_url[1:]
    fwd_url = fwd_url_prefix + "/" + remaining_url

    async with httpx.AsyncClient() as client:
        # timeout also ends circular requests (when forwarding to the forwarding url)
        async with asyncio.timeout(timeout):
            match forwarding.forward_method:
                case "GET":
                    return await client.get(fwd_url, headers=headers)
                case "POST":
                    return await client.post(fwd_url, headers=headers, data=data)
                case "PUT":
                    return await client.put(fwd_url, headers=headers, data=data)
                case "HEAD":
                    return await client.head(fwd_url, headers=headers)
                case "DELETE":
                    return await client.delete(fwd_url, headers=headers, data=data)
