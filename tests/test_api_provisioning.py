"""
Provisioning API tests — simulates the arduino4iot device provisioning flow.

POST /api/provision
  Body:     {"projectName": "...", "deviceName": "...", "provisioningToken": "..."}
  Response: {"tokenType": "bearer", "accessToken": "...", "expiresAt": "...", "expiresIn": ...}
"""
import datetime
import pytest

from app.core.token.backend import (
    create_token,
    get_provisioning_token_adapter,
    load_device_tokens,
    save_device_tokens,
)
from app.core.token.models import AuthToken
from app.core.device.backend import get_device, update_device
from tests.conftest import make_provisioning_token, setup_project


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


def test_provision_returns_usable_device_token(client, project_autoapprove, projects_dir):
    """The returned device token can immediately authenticate a file request."""
    from app.paths import project_dir
    project, prov_token = project_autoapprove

    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200
    device_token = resp.json()["accessToken"]

    config_file = project_dir(project.name) / "e32-aabb1234" / "test.txt"
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
    project, prov_token = project_autoapprove
    device_name = "e32-tokentest"

    for _ in range(3):
        resp = client.post("/api/provision", json={
            "projectName": project.name,
            "deviceName": device_name,
            "provisioningToken": prov_token,
        })
        assert resp.status_code == 200

    # Expire all existing tokens
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    tokens = load_device_tokens(project.name, device_name)
    for t in tokens:
        t.expires_at = past
    save_device_tokens(project.name, device_name, tokens)

    # One more provision — expired tokens should be purged first
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": device_name,
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200

    tokens = load_device_tokens(project.name, device_name)
    assert len(tokens) == 1  # only the fresh token remains


# ---------------------------------------------------------------------------
# Provisioning response fields (spec: expiresAt and expiresIn)
# ---------------------------------------------------------------------------

def test_provision_response_includes_expires_at(client, project_autoapprove):
    """Response must include expiresAt as an ISO 8601 timestamp."""
    project, prov_token = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-expiry",
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "expiresAt" in body
    # must be parseable as datetime
    datetime.datetime.fromisoformat(body["expiresAt"])


def test_provision_response_includes_expires_in(client, project_autoapprove):
    """Response must include expiresIn as a positive integer (seconds)."""
    project, prov_token = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-expiry2",
        "provisioningToken": prov_token,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "expiresIn" in body
    assert isinstance(body["expiresIn"], int)
    assert body["expiresIn"] > 0


# ---------------------------------------------------------------------------
# Token cap: max 32 active tokens per device (spec)
# ---------------------------------------------------------------------------

def test_provision_max_tokens_evicts_oldest(client, project_autoapprove):
    """When a device accumulates more than 32 tokens the one with the oldest
    last_use_at is evicted so the total stays at 32."""
    project, prov_token = project_autoapprove
    device_name = "e32-maxtoken"

    for _ in range(33):
        resp = client.post("/api/provision", json={
            "projectName": project.name,
            "deviceName": device_name,
            "provisioningToken": prov_token,
        })
        assert resp.status_code == 200

    tokens = load_device_tokens(project.name, device_name)
    assert len(tokens) <= 32


# ---------------------------------------------------------------------------
# Auth failures
# ---------------------------------------------------------------------------

def test_provision_invalid_token_rejected(client, project_autoapprove):
    project, _ = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32-aabb1234",
        "provisioningToken": "x" * 32,
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
    project, value = setup_project("proj_expired",
                                   is_autocreate_devices=True,
                                   is_provisioning_autoapproval=True)
    # Replace the valid token with an expired one
    adapter = get_provisioning_token_adapter("proj_expired")
    for key, _ in list(adapter.items()):
        adapter.delete(key)
    expired_token = create_token(datetime.timedelta(seconds=-1), length=64)
    adapter.create(expired_token)

    resp = client.post("/api/provision", json={
        "projectName": "proj_expired",
        "deviceName": "e32-aabb1234",
        "provisioningToken": expired_token.value,
    })
    assert resp.status_code == 401


def test_provision_inactive_token_rejected(client, projects_dir):
    project, _ = setup_project("proj_inactive_tok",
                                is_autocreate_devices=True,
                                is_provisioning_autoapproval=True)
    adapter = get_provisioning_token_adapter("proj_inactive_tok")
    for key, t in list(adapter.items()):
        t.is_active = False
        adapter.update(t)

    resp = client.post("/api/provision", json={
        "projectName": "proj_inactive_tok",
        "deviceName": "e32-aabb1234",
        "provisioningToken": _,
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
    project, value = setup_project("proj_inactive",
                                   is_active=False,
                                   is_autocreate_devices=True,
                                   is_provisioning_autoapproval=True)
    resp = client.post("/api/provision", json={
        "projectName": "proj_inactive",
        "deviceName": "e32-aabb1234",
        "provisioningToken": value,
    })
    assert resp.status_code == 403


def test_provision_no_autocreate_rejected(client, projects_dir):
    project, value = setup_project("proj_no_autocreate",
                                   is_autocreate_devices=False,
                                   is_provisioning_autoapproval=True)
    resp = client.post("/api/provision", json={
        "projectName": "proj_no_autocreate",
        "deviceName": "brand_new_device",
        "provisioningToken": value,
    })
    assert resp.status_code == 404


def test_provision_no_autoapproval_rejected(client, projects_dir):
    project, value = setup_project("proj_no_autoapproval",
                                   is_autocreate_devices=True,
                                   is_provisioning_autoapproval=False)
    resp = client.post("/api/provision", json={
        "projectName": "proj_no_autoapproval",
        "deviceName": "brand_new_device",
        "provisioningToken": value,
    })
    assert resp.status_code == 403
