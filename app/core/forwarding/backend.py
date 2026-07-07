from pathlib import Path

import httpx
import asyncio

from pydantic import TypeAdapter
from niceview.dataadapter import JsonListAdapter

from app.exceptions import NotFoundError
from app.paths import project_dir
from app.core.forwarding.models import ForwardingConfig

_adapter = TypeAdapter(list[ForwardingConfig])

###############################################################################

FORWARD_FILE_NAME = '.forwards.json'

###############################################################################

def get_forwardings_filename(project_name: str) -> Path:
    """Get the filename for the forwardings of a project."""
    return project_dir(project_name) / FORWARD_FILE_NAME


def get_forwarding_adapter(project_name: str) -> JsonListAdapter:
    """Get a JsonListAdapter for the forwardings of a project."""
    return JsonListAdapter(ForwardingConfig, get_forwardings_filename(project_name))


def get_forwarding(project_name: str, forwarding_name: str) -> ForwardingConfig:
    """Return the named forwarding config for a project.

    Raises:
        NotFoundError: forwarding_name is not defined in the project's forwarding list.
    """
    filename = get_forwardings_filename(project_name)
    forwardings = _adapter.validate_json(filename.read_text()) if filename.is_file() else []
    forwarding = next((f for f in forwardings if f.name == forwarding_name), None)
    if not forwarding:
        raise NotFoundError(f"Forwarding {forwarding_name!r} not found in project {project_name!r}")
    return forwarding

###############################################################################

async def forward(forwarding: ForwardingConfig, remaining_url: str, data: str, headers: dict, query_params: dict, timeout: int) -> httpx.Response:
    """Forward a request to the configured upstream URL.

    Raises:
        TimeoutError: upstream did not respond within *timeout* seconds.
    """
    fwd_url = forwarding.forward_url.rstrip('/') + '/' + remaining_url
    if query_params:
        fwd_url = fwd_url + f'?{query_params}'

    async with httpx.AsyncClient() as client:
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
