"""
Provisioning API tests — simulates the arduino4iot device provisioning flow.

POST /api/provision
  Body:     {"projectName": "...", "deviceName": "...", "provisioningToken": "..."}
  Response: {"tokenType": "bearer", "accessToken": "..."}
"""
import datetime
import pytest

from app.core.auth import generate_token
from app.core.models import AuthToken, Project
from app.core.project import create_project
from tests.conftest import make_provisioning_token


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_provision_new_device(client, project_autoapprove):
    """New device is auto-created and provisioned in one call."""
    project, prov_token = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["tokenType"] == "bearer"
    assert len(body["accessToken"]) >= 16


def test_provision_returns_usable_device_token(client, project_autoapprove):
    """The returned device token can immediately authenticate a telemetry request."""
    project, prov_token = project_autoapprove

    # Provision
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200
    device_token = resp.json()["accessToken"]

    # The health endpoint isn't auth-protected; use file endpoint to verify token
    # (actual telemetry would need a backend config)
    from app.core.project import get_project_path
    config_file = get_project_path(project.name) / "e32-aabb1234" / "test.txt"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("hello")

    resp2 = client.get(
        f"/api/file/{project.name}/e32-aabb1234/test.txt",
        headers={"Authorization": f"bearer {device_token}"},
    )
    assert resp2.status_code == 200


def test_provision_existing_device(client, provisioned):
    """Re-provisioning an existing approved device issues a fresh token."""
    resp = client.post("/api/provision", json={
        "projectName": provisioned["project_name"],
        "deviceName": provisioned["device_name"],
        "provisioningToken": provisioned["provisioning_token"],
    })
    assert resp.status_code == 200
    new_token = resp.json()["accessToken"]
    assert new_token != provisioned["device_token"]


def test_provision_purges_expired_tokens(client, project_autoapprove):
    """
    After several provisions the device token list must not grow unboundedly.
    Expired tokens are purged before each new one is appended.
    """
    from app.core.device import get_device, create_device
    from app.core.models import Device

    project, prov_token = project_autoapprove
    device_name = "e32-tokentest"

    # Provision three times
    for _ in range(3):
        resp = client.post("/api/provision", json={
            "projectName": project.name,
            "deviceName": device_name,
            "provisioningToken": prov_token,
        })
        assert resp.status_code == 200

    # Expire all existing tokens by re-reading the device and back-dating them
    device = get_device(project.name, device_name)
    from app.core.device import update_device
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    for t in device.tokens:
        t.expires_at = past
    update_device(device)

    # One more provision — expired tokens should be purged first
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": device_name,
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200

    device = get_device(project.name, device_name)
    assert len(device.tokens) == 1  # only the fresh token remains


# ---------------------------------------------------------------------------
# Auth failures
# ---------------------------------------------------------------------------

def test_provision_invalid_token_rejected(client, project_autoapprove):
    project, _ = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": "x" * 32,  # wrong but long enough to pass format check
    })
    assert resp.status_code == 401


def test_provision_short_token_rejected(client, project_autoapprove):
    project, _ = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": "tooshort",
    })
    assert resp.status_code == 401


def test_provision_expired_token_rejected(client, projects_dir):
    project = Project(name="proj_expired", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    token, value = make_provisioning_token(expires_in=datetime.timedelta(seconds=-1))
    project.provisioning_tokens.append(token)
    create_project(project)

    resp = client.post("/api/provision", json={
        "projectName": "proj_expired",
        "deviceName": "e32-aabb1234",
        "provisioningToken": value,
    })
    assert resp.status_code == 401


def test_provision_inactive_token_rejected(client, projects_dir):
    project = Project(name="proj_inactive_tok", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    token, value = make_provisioning_token()
    token.is_active = False
    project.provisioning_tokens.append(token)
    create_project(project)

    resp = client.post("/api/provision", json={
        "projectName": "proj_inactive_tok",
        "deviceName": "e32-aabb1234",
        "provisioningToken": value,
    })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Project / device state failures
# ---------------------------------------------------------------------------

def test_provision_nonexistent_project(client, projects_dir):
    resp = client.post("/api/provision", json={
        "projectName": "does_not_exist",
        "deviceName": "e32-aabb1234",
        "provisioningToken": "x" * 32,
    })
    assert resp.status_code == 404


def test_provision_inactive_project_rejected(client, projects_dir):
    project = Project(name="proj_inactive", is_active=False,
                      is_autocreate_devices=True, is_provisioning_autoapproval=True)
    token, value = make_provisioning_token()
    project.provisioning_tokens.append(token)
    create_project(project)

    resp = client.post("/api/provision", json={
        "projectName": "proj_inactive",
        "deviceName": "e32-aabb1234",
        "provisioningToken": value,
    })
    assert resp.status_code == 403


def test_provision_no_autocreate_rejected(client, projects_dir):
    project = Project(name="proj_no_autocreate", is_autocreate_devices=False,
                      is_provisioning_autoapproval=True)
    token, value = make_provisioning_token()
    project.provisioning_tokens.append(token)
    create_project(project)

    resp = client.post("/api/provision", json={
        "projectName": "proj_no_autocreate",
        "deviceName": "brand_new_device",
        "provisioningToken": value,
    })
    assert resp.status_code == 404


def test_provision_no_autoapproval_rejected(client, projects_dir):
    project = Project(name="proj_no_autoapproval", is_autocreate_devices=True,
                      is_provisioning_autoapproval=False)
    token, value = make_provisioning_token()
    project.provisioning_tokens.append(token)
    create_project(project)

    resp = client.post("/api/provision", json={
        "projectName": "proj_no_autoapproval",
        "deviceName": "brand_new_device",
        "provisioningToken": value,
    })
    assert resp.status_code == 403
