import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, status
from app.api.device import router
from app.config import app_config
from app.core.device import device_provision
from app.core.models import Project
from app.core.project import create_project
from app.core.forwarding.forwarding import update_forwadings, ForwardingModelList

# Create a TestClient for the router
client = TestClient(router)

@pytest.fixture
def setup_test_environment(tmp_path):
    """
    Set up a temporary test environment with a project and forwarding configuration.
    """
    # Create the base directory for projects
    base_dir = tmp_path / "projects"
    base_dir.mkdir()

    # Update the app config to use the temporary directory
    app_config.projects_dir = str(base_dir)

    # Create a project
    project_name = "test_project"
    project = Project(name=project_name, is_autocreate_devices=True, is_provisioning_autoapproval=True)
    project = create_project(project)

    device_name = "test_device"
    device_token = device_provision(project, device_name)

    # Add forwarding configuration
    forwardings = ForwardingModelList(forwards={
        "valid_forwarding": {
            "forward_url": "http://httpbin.org/anything",
            "forward_method": "GET"
        }
    })
    update_forwadings(project_name, forwardings)

    return {
        "base_dir": base_dir,
        "project_name": project_name,
        "device_name": device_name,
        "device_token": device_token,
        "forwarding_name": "valid_forwarding",
        "invalid_forwarding_name": "invalid_forwarding",
    }

def test_forward_no_auth_token(setup_test_environment):
    """
    Test the forward endpoint when no auth token is provided.
    """
    env = setup_test_environment

    # Make a HEAD request to the endpoint without an auth token
    with pytest.raises(HTTPException) as err:
        client.get(
            f"/forward/{env['project_name']}/{env['device_name']}/{env['forwarding_name']}/remaining/path"
        )

    # Assertions
    assert err.value.status_code == status.HTTP_401_UNAUTHORIZED

def test_forward_success(setup_test_environment):
    """
    Test the forward endpoint with a valid forwarding configuration.
    """
    env = setup_test_environment

    # Make a GET request to the /forward endpoint
    response = client.get(
        f"/forward/{env['project_name']}/{env['device_name']}/{env['forwarding_name']}/remaining/path",
        headers={"Authorization": f"Bearer {env['device_token']}"}
    )

    # Assertions
    assert response.status_code == 200
    assert response.json() is not None  # Assuming the forwarded response has a JSON body
