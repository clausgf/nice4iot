import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.provisioning import router as provisioning_router
from app.api.device import router as device_router
from app.api.file import router as file_router
from app.config import app_config
from app.core.token.backend import create_token, get_provisioning_token_adapter
from app.core.token.models import AuthToken
from app.core.project.models import Project
from app.core.project.backend import create_project, project_adapter
from app.core.device.backend import device_provision
from app.core.logging.backend import get_logging_adapter


@pytest.fixture(autouse=True)
def clear_file_log_handlers():
    """Reset FileLogBackend's class-level handler cache between tests.

    Handlers are keyed by (project_name, device_name). When tests use the same
    names with different tmp_path directories, the cached handler would point to
    a stale path from a previous test.
    """
    yield
    from app.core.logging.file.backend import FileLogBackend
    for handler, _ in FileLogBackend._handlers.values():
        handler.close()
    FileLogBackend._handlers.clear()


def make_api_app() -> FastAPI:
    """FastAPI app with only the device API routers — no NiceGUI."""
    app = FastAPI()
    app.include_router(provisioning_router, prefix="/api")
    app.include_router(device_router, prefix="/api")
    app.include_router(file_router, prefix="/api")
    return app


@pytest.fixture
def api_app():
    # Function-scoped so that per-test monkeypatching of app_config.projects_dir
    # is safe even if backends ever cache paths at construction time.
    return make_api_app()


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    """Isolated temporary projects directory, wired into app_config."""
    base_dir = tmp_path / "projects"
    base_dir.mkdir()
    monkeypatch.setattr(app_config, "projects_dir", base_dir)
    return base_dir


@pytest.fixture
def client(api_app, projects_dir):
    return TestClient(api_app)


# ---------------------------------------------------------------------------
# Reusable project/device building blocks
# ---------------------------------------------------------------------------

def make_provisioning_token(
    expires_in: datetime.timedelta = datetime.timedelta(days=7),
) -> tuple[AuthToken, str]:
    token = create_token(expires_in, length=64)
    return token, token.value


def setup_project(project_name: str, **project_attrs) -> tuple[Project, str]:
    """Create a project directory and return (project, provisioning_token_value).

    Optional keyword arguments override the default Project field values.
    A single provisioning token is created and stored in the project.
    """
    create_project(project_name)
    adapter = project_adapter(project_name)
    project = adapter.read()
    project.name = project_name
    for key, value in project_attrs.items():
        setattr(project, key, value)
    adapter.save(project)
    token, value = make_provisioning_token()
    get_provisioning_token_adapter(project_name).create(token)
    return project, value


@pytest.fixture
def project_autoapprove(projects_dir):
    """Project with autocreate=True and autoapproval=True, one valid provisioning token."""
    return setup_project(
        "myproject",
        is_autocreate_devices=True,
        is_provisioning_autoapproval=True,
    )


@pytest.fixture
def provisioned(project_autoapprove):
    """
    Provisioned device in the autoapprove project.
    File logging is activated. Telemetry is left unconfigured (write_telemetry
    is a no-op when no backend is configured).
    Returns a dict with all relevant names and tokens.
    """
    project, prov_token = project_autoapprove
    device_name = "e32-aabb1234"
    device_token = device_provision(project, device_name).value

    # Activate file logging so log-related tests can verify written content.
    log_config = get_logging_adapter(project.name).read()
    log_config.file.is_active = True
    get_logging_adapter(project.name).save(log_config)

    return {
        "project_name": project.name,
        "device_name": device_name,
        "provisioning_token": prov_token,
        "device_token": device_token,
    }
