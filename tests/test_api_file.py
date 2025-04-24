import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, status
from pathlib import Path
from app.api.file import router
from app.config import app_config
from app.core.device import create_device, device_provision, get_file_path
from app.core.models import Device, Project
from app.core.project import create_project, get_project_path

# Create a TestClient for the router
client = TestClient(router)

@pytest.fixture
def setup_test_environment(tmp_path: Path):
    """
    Set up a temporary test environment with a project, device, and file structure.
    """
    # Create the base directory for projects
    base_dir = tmp_path / "projects"
    base_dir.mkdir()

    # Update the app config to use the temporary directory
    app_config.projects_dir = str(base_dir)

    # Create a project and a device
    project_name = "test_project"
    project = Project(name=project_name, is_autocreate_devices=True, is_provisioning_autoapproval=True)
    project = create_project(project)

    device_name = "test_device"
    device_token = device_provision(project, device_name)

    # Create a file in the device directory
    filename_dev = "test_file_dev.txt"
    file_path_dev = get_file_path(project_name, device_name, filename_dev, check_file_exists=False)
    file_path_dev.write_text("This is a test file in the device directory.")

    # Create a file in the project directory
    filename_proj = "test_file_proj.txt"
    file_path_proj = get_project_path(project_name) / filename_proj
    file_path_proj.write_text("This is a test file in the project directory.")

    # Return the paths for use in the test
    return {
        "base_dir": base_dir,
        "project_name": project_name,
        "device_name": device_name,
        "device_token": device_token,
        "filename_dev": filename_dev,
        "filename_proj": filename_proj,
    }

def test_head_no_auth_token(setup_test_environment):
    """
    Test the head_resource endpoint when no auth token is provided.
    """
    env = setup_test_environment

    # Make a HEAD request to the endpoint without an auth token
    with pytest.raises(HTTPException) as err:
        client.head(
            f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}"
        )

    # Assertions
    assert err.value.status_code == status.HTTP_401_UNAUTHORIZED

def test_head_wrong_auth_token(setup_test_environment):
    """
    Test the head_resource endpoint when a wrong auth token is provided.
    """
    env = setup_test_environment

    # Make a HEAD request to the endpoint with a wrong auth token
    with pytest.raises(HTTPException) as err:
        client.head(
            f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
            headers={"Authorization": "Bearer wrong_token_which_is_long_enough"}
        )

    # Assertions
    assert err.value.status_code == status.HTTP_401_UNAUTHORIZED

def test_head_no_etag(setup_test_environment):
    """
    Test the head_resource endpoint when the file exists, no if-none-match given.
    """
    env = setup_test_environment

    # Make a HEAD request to the endpoint
    response = client.head(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}"}
    )

    # Assertions
    assert response.status_code == 200
    assert "etag" in response.headers

def test_head_file_modified(setup_test_environment):
    """
    Test the head_resource endpoint when the file exists and has been modified.
    """
    env = setup_test_environment

    # Make a HEAD request to the endpoint
    response = client.head(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}",
                 "If-None-Match": "different-etag"}
    )

    # Assertions
    assert response.status_code == 200
    assert "etag" in response.headers

def test_head_file_not_modified(setup_test_environment):
    """
    Test the head_resource endpoint when the file exists but has not been modified.
    """
    env = setup_test_environment

    # Get the ETag of the file
    response = client.head(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}"}
    )
    assert response.status_code == 200
    etag = response.headers.get("etag")
    assert etag is not None

    # Make another HEAD request with the same ETag
    response = client.head(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}",
                 "If-None-Match": etag}
    )

    # Assertions
    assert response.status_code == 304

def test_head_file_not_found(setup_test_environment):
    """
    Test the head_resource endpoint when the file does not exist.
    """
    env = setup_test_environment

    # # Make a HEAD request to a non-existent file
    # response = client.head(
    #     f"/file/{env['project_name']}/{env['device_name']}/nonexistent.txt",
    #     headers={"Authorization": f"Bearer {env['device_token']}"}
    # )

    # # Assertions
    # assert response.status_code == 404

    # TODO for some strange reason the above test fails (HTTPException not caught)
    # but this one works
    with pytest.raises(HTTPException) as err:
        client.head(
            f"/file/{env['project_name']}/{env['device_name']}/nonexistent.txt",
            headers={"Authorization": f"Bearer {env['device_token']}"}
        )
    assert err.value.status_code == 404

def test_get_file_modified(setup_test_environment):
    """
    Test the get_resource endpoint when the file exists and has been modified.
    """
    env = setup_test_environment

    # Make a GET request to the endpoint
    response = client.get(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}",
                 "If-None-Match": "different-etag"}
    )

    # Assertions
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.text == "This is a test file in the device directory."
    etag = response.headers.get("etag")
    assert etag is not None and len(etag) > 0

def test_put_new_file(setup_test_environment):
    """
    Test the put_resource endpoint to create a new file.
    """
    env = setup_test_environment

    # Create a new file content
    new_file_content = "This is a new test file content."

    # Make a PUT request to the endpoint
    response = client.put(
        f"/file/{env['project_name']}/{env['device_name']}/new_file.txt",
        headers={"Authorization": f"Bearer {env['device_token']}"},
        data=new_file_content
    )

    # Assertions
    assert response.status_code == 200

    # Verify the file content
    file_path = get_file_path(env['project_name'], env['device_name'], "new_file.txt")
    assert file_path.read_text() == new_file_content

def test_put_modify_file(setup_test_environment):
    """
    Test the put_resource endpoint to modify an existing file.
    """
    env = setup_test_environment

    # Create new content for the existing file
    new_file_content = "This is modified content."

    # Make a PUT request to the endpoint
    response = client.put(
        f"/file/{env['project_name']}/{env['device_name']}/{env['filename_dev']}",
        headers={"Authorization": f"Bearer {env['device_token']}"},
        data=new_file_content
    )

    # Assertions
    assert response.status_code == 200

    # Verify the file content
    file_path = get_file_path(env['project_name'], env['device_name'], env['filename_dev'])
    assert file_path.read_text() == new_file_content
