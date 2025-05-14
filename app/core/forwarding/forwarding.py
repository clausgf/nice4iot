import json,httpx,asyncio

from fastapi import HTTPException, status

from app.util import logger
from app.core.project import get_project_path
from app.core.forwarding.models import ForwardingModelList


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

async def forward(project_name: str, forwarding_name: str, data: str, headers: dict, timeout: int):
    #project_forwards_path.write_text(ForwardingModelList().model_dump_json())
    forward_dict = get_forwadings(project_name)
    forwarding = forward_dict.forwards.get(forwarding_name)
    if not forwarding:
        raise HTTPException(status_code=404,details="Forwarding not found")
    async with httpx.AsyncClient() as client:
        # timeout also ends circular requests (when forwarding to the forwarding url)
        async with asyncio.timeout(timeout):
            match forwarding.forward_method:
                case "GET":
                    return await client.get(forwarding.forward_url,headers=headers)
                case "POST":
                    return await client.post(forwarding.forward_url,headers=headers,data=data)
                case "PUT":
                    return await client.put(forwarding.forward_url,headers=headers,data=data)
                case "HEAD":
                    return await client.head(forwarding.forward_url,headers=headers)
                case "DELETE":
                    return await client.delete(forwarding.forward_url,headers=headers,data=data)

