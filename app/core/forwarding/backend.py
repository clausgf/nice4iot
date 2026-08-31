from pathlib import Path
from typing import Mapping

import httpx
import asyncio

from pydantic import TypeAdapter, ValidationError
from niceview.dataadapter import JsonListAdapter

from app.exceptions import NotFoundError
from app.paths import project_dir
from app.core.forwarding.models import ForwardingConfig
from app.util import logger

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
    try:
        forwardings = _adapter.validate_json(filename.read_text()) if filename.is_file() else []
    except (ValidationError, OSError) as e:
        logger.error(f"Failed to load forwarding config for {project_name!r}: {e}")
        forwardings = []
    forwarding = next((f for f in forwardings if f.name == forwarding_name), None)
    if not forwarding:
        raise NotFoundError(f"Forwarding {forwarding_name!r} not found in project {project_name!r}")
    return forwarding

###############################################################################

async def forward(forwarding: ForwardingConfig, remaining_url: str, data: bytes, headers: Mapping[str, str], query_params: Mapping[str, str], timeout: int, *, project_name: str) -> httpx.Response:
    """Forward a request to the configured upstream URL.

    Raises:
        TimeoutError: upstream did not respond within *timeout* seconds.
    """
    from app.health import set_health
    key = f'{project_name}:forwarding:{forwarding.name}'

    # Strip trailing slash from base; only append a separator when there is a suffix.
    # remaining_url must not contain '..' path segments (path traversal guard).
    base = forwarding.forward_url.rstrip('/')
    fwd_url = f"{base}/{remaining_url}" if remaining_url else base
    if query_params:
        fwd_url = fwd_url + f'?{query_params}'

    try:
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(timeout):
                match forwarding.forward_method:
                    case "GET":
                        response = await client.get(fwd_url, headers=headers)
                    case "POST":
                        response = await client.post(fwd_url, headers=headers, content=data)
                    case "PUT":
                        response = await client.put(fwd_url, headers=headers, content=data)
                    case "HEAD":
                        response = await client.head(fwd_url, headers=headers)
                    case "DELETE":
                        response = await client.request("DELETE", fwd_url, headers=headers, content=data)
    except TimeoutError:
        set_health(key, False, 'timed out')
        raise
    except httpx.HTTPError as e:
        set_health(key, False, str(e))
        raise

    # Non-2xx upstream responses are forwarded verbatim (see caller docstring);
    # that's not a forwarding failure, so any received response counts as healthy.
    set_health(key, True)
    return response
