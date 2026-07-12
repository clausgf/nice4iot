ROUTE_PROJECTS = '/'
ROUTE_PROJECT = '/{project_id}'
ROUTE_DEVICE = '/{project_id}/devices/{device_id}'


def projects_url() -> str:
    return '/'


def project_url(project_id: str, tab: str | None = None) -> str:
    url = f'/{project_id}'
    return f'{url}?tab={tab}' if tab else url


def device_url(project_id: str, device_id: str, tab: str | None = None) -> str:
    url = f'/{project_id}/devices/{device_id}'
    return f'{url}?tab={tab}' if tab else url


def project_extension_url(project_id: str, extension_name: str) -> str:
    """URL of an extension's standalone project page (see docs/extensions.md)."""
    return f'/{project_id}/ext/{extension_name}'
