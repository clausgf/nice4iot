import datetime
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, status
from app.api.provisioning import router
from app.config import app_config
from app.core.auth import generate_token
from app.core.models import AuthToken, Project
from app.core.project import create_project

# Create a TestClient for the router
client = TestClient(router)

def add_provisioning_token(project: Project, expires_in: datetime.timedelta = datetime.timedelta(days=7)) -> str:
    """
    Add a provisioning token to the project and return the token value
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    value = generate_token(length=32)
    token = AuthToken(value=value, created_at=now, expires_at=now + expires_in)
    project.provisioning_tokens.append(token)
    return value

@pytest.fixture
def setup_test_environment(tmp_path):
    """
    Set up a temporary test environment with a project.
    """
    # Create the base directory for projects
    base_dir = tmp_path / "projects"
    base_dir.mkdir()

    # Update the app config to use the temporary directory
    app_config.projects_dir = str(base_dir)

    # Create a project
    project_name = "test_project_autocreate_autoapprove"
    project = Project(name=project_name, is_autocreate_devices=True, is_provisioning_autoapproval=True)
    provisioning_token = add_provisioning_token(project)
    project = create_project(project)

    return {
        "base_dir": base_dir,
        "project_name": project_name,
        "provisioning_token": provisioning_token,
    }

def test_provision_success(setup_test_environment):
    """
    Test the /provision endpoint with valid data.
    """
    env = setup_test_environment

    # Make a POST request to the /provision endpoint
    response = client.post(
        "/provision",
        json={
            "projectName": env["project_name"],
            "deviceName": "test_device",
            "provisioningToken": env["provisioning_token"],
        },
    )

    # Assertions
    assert response.status_code == 200
    assert response.json()["tokenType"] == "bearer"
    assert "accessToken" in response.json()

def test_provision_nonexistent_project(setup_test_environment):
    """
    Test the /provision endpoint with an invalid project name.
    """
    env = setup_test_environment

    # Make a POST request with an invalid project name
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": "invalid_project",
                "deviceName": "test_device",
                "provisioningToken": env["provisioning_token"],
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_404_NOT_FOUND

def test_provision_invalid_token(setup_test_environment):
    """
    Test the /provision endpoint with an invalid provisioning token.
    """
    env = setup_test_environment

    # Make a POST request with an invalid provisioning token
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": env["project_name"],
                "deviceName": "test_device",
                "provisioningToken": "invalid_token",
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_401_UNAUTHORIZED

def test_provision_inactive_token(setup_test_environment):
    """
    Test the /provision endpoint with an inactive provisioning token.
    """
    env = setup_test_environment

    # Create a project
    project_name = "test_project_inactive_token"
    project = Project(name=project_name, is_autocreate_devices=True, is_provisioning_autoapproval=True)
    provisioning_token = add_provisioning_token(project)
    project.provisioning_tokens[-1].is_active = False
    project = create_project(project)

    # Make a POST request to the /provision endpoint
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": project_name,
                "deviceName": "test_device",
                "provisioningToken": provisioning_token,
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_401_UNAUTHORIZED

def test_provision_inactive_project(setup_test_environment):
    """
    Test the /provision endpoint with an inactive project.
    """
    env = setup_test_environment

    # Create a project
    project_name = "test_project_inactive"
    project = Project(name=project_name, is_active=False, is_autocreate_devices=True, is_provisioning_autoapproval=True)
    provisioning_token = add_provisioning_token(project)
    project = create_project(project)

    # Make a POST request to the /provision endpoint
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": project_name,
                "deviceName": "test_device",
                "provisioningToken": provisioning_token,
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_403_FORBIDDEN

def test_provision_device_no_autocreate(setup_test_environment):
    """
    Test the /provision endpoint with new device but without autocreate.
    """
    env = setup_test_environment

    # Create a project
    project_name = "test_project_no_autocreate"
    project = Project(name=project_name, is_autocreate_devices=False, is_provisioning_autoapproval=True)
    provisioning_token = add_provisioning_token(project)
    project = create_project(project)

    # Make a POST request to the /provision endpoint
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": project_name,
                "deviceName": "test_device",
                "provisioningToken": provisioning_token,
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_404_NOT_FOUND

def test_provision_device_no_autoapprove(setup_test_environment):
    """
    Test the /provision endpoint with new device but without autoapprove.
    """
    env = setup_test_environment

    # Create a project
    project_name = "test_project_no_autoapprove"
    project = Project(name=project_name, is_autocreate_devices=True, is_provisioning_autoapproval=False)
    provisioning_token = add_provisioning_token(project)
    project = create_project(project)

    # Make a POST request to the /provision endpoint
    with pytest.raises(HTTPException) as err:
        response = client.post(
            "/provision",
            json={
                "projectName": project_name,
                "deviceName": "test_device",
                "provisioningToken": provisioning_token,
            },
        )

    # Assertions
    assert err.value.status_code == status.HTTP_403_FORBIDDEN
    