import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.api.provisioning import router as provisioning_router
from app.api.device import router as device_router
from app.api.file import router as file_router
from app.config import app_config
from app.core.auth import generate_token
from app.core.models import AuthToken, Project
from app.core.project import create_project
from app.core.device import device_provision
from app.core.telemetry.telemetry import create_tel
from app.core.telemetry.models import TelemetryBackendTypes
from app.core.logging.logging import create_log, LoggingBackendTypes


@pytest.fixture(autouse=True)
def clear_file_log_handlers():
    """Reset FileLogBackend's class-level handler cache between tests.

    The handler cache is keyed by project name. When tests use the same project
    name with different tmp_path directories, the cached handler would point to
    a stale path from a previous test.
    """
    yield
    from app.core.logging.file.logging_file_backend import FileLogBackend
    for handler in FileLogBackend._handlers.values():
        handler.close()
    FileLogBackend._handlers.clear()


def make_api_app() -> FastAPI:
    """FastAPI app with only the device API routers — no NiceGUI."""
    app = FastAPI()
    app.include_router(provisioning_router, prefix="/api")
    app.include_router(device_router, prefix="/api")
    app.include_router(file_router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def api_app():
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

def make_provisioning_token(expires_in: datetime.timedelta = datetime.timedelta(days=7)) -> tuple[AuthToken, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    value = generate_token(64)
    token = AuthToken(value=value, created_at=now, expires_at=now + expires_in)
    return token, value


@pytest.fixture
def project_autoapprove(projects_dir):
    """Project with autocreate=True and autoapproval=True, one valid provisioning token."""
    project = Project(
        name="myproject",
        is_autocreate_devices=True,
        is_provisioning_autoapproval=True,
    )
    token, value = make_provisioning_token()
    project.provisioning_tokens.append(token)
    project = create_project(project)
    return project, value


@pytest.fixture
def provisioned(project_autoapprove):
    """
    Provisioned device in the autoapprove project.
    Telemetry (Prometheus, mocked) and logging (file) backends are configured.
    Returns a dict with all relevant names and tokens.
    """
    project, prov_token = project_autoapprove
    device_name = "e32-aabb1234"
    device_token = device_provision(project, device_name)
    create_tel(project.name, TelemetryBackendTypes.PROMETHEUS)
    create_log(project.name, LoggingBackendTypes.FILE)

    # Persist the file logging backend choice in the project record
    from app.core.project import update_project
    project.loggingBackend = LoggingBackendTypes.FILE
    update_project(project)

    return {
        "project_name": project.name,
        "device_name": device_name,
        "provisioning_token": prov_token,
        "device_token": device_token,
    }
