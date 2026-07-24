# The UI lives under this prefix; /api and framework assets (/_nicegui*) sit
# outside it. '/' redirects here (see app.main). Keeping every human-facing page
# under one prefix removes the top-level namespace collisions that a flat scheme
# had (a project could never be told apart from /about, /login, …).
UI_PREFIX = '/ui'

# Sub-page routes, RELATIVE to UI_PREFIX: ui.sub_pages is created with
# root_path=UI_PREFIX, which strips the prefix before matching these keys.
# The literal 'project' segment keeps project/device names from colliding with
# reserved pages (about, preferences) or with the 'ext' extension segment.
ROUTE_PROJECTS = '/'
ROUTE_ABOUT = '/about'
ROUTE_PREFERENCES = '/preferences'
ROUTE_PROJECT = '/project/{project_id}'
ROUTE_DEVICE = '/project/{project_id}/device/{device_id}'


def projects_url() -> str:
    return UI_PREFIX


def about_url() -> str:
    return f'{UI_PREFIX}/about'


def preferences_url() -> str:
    return f'{UI_PREFIX}/preferences'


def login_url() -> str:
    return f'{UI_PREFIX}/login'


def project_url(project_id: str, tab: str | None = None) -> str:
    url = f'{UI_PREFIX}/project/{project_id}'
    return f'{url}?tab={tab}' if tab else url


def device_url(project_id: str, device_id: str, tab: str | None = None) -> str:
    url = f'{UI_PREFIX}/project/{project_id}/device/{device_id}'
    return f'{url}?tab={tab}' if tab else url


def project_extension_url(project_id: str, extension_name: str) -> str:
    """URL of an extension's standalone project page (see docs/extensions.md)."""
    return f'{UI_PREFIX}/project/{project_id}/ext/{extension_name}'
