"""Acceptance tests: end-to-end device lifecycle through the full API stack.

These tests verify complete user-visible workflows — provision, push telemetry,
upload/download files, log, re-provision after token expiry — rather than
individual units. They are intentionally kept separate from unit and API tests
so that regressions in cross-cutting behaviour are immediately visible.

Run only acceptance tests: pytest tests/test_acceptance.py -v
"""
import datetime
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import app.extensions as extensions
from app.extensions import mount_extension_router, registering
from tests.conftest import make_api_app, setup_project
from app.core.project.backend import project_adapter
from app.core.telemetry.backend import read_local_metrics


pytestmark = pytest.mark.acceptance


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Full device lifecycle
# ---------------------------------------------------------------------------

class TestDeviceLifecycle:
    """Provision → telemetry → file upload/download → log → re-provision."""

    @pytest.fixture
    def setup(self, client, projects_dir):
        project, prov_token = setup_project(
            "lifecycle_project",
            is_autocreate_devices=True,
            is_provisioning_autoapproval=True,
        )
        return {"project": project, "prov_token": prov_token, "device": "lifecycle_device"}

    def test_provision_creates_device_token(self, client, setup):
        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["tokenType"] == "bearer"
        assert len(body["accessToken"]) >= 16

    def test_telemetry_push_accepted(self, client, setup):
        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        device_token = resp.json()["accessToken"]

        resp = client.post(
            f"/api/telemetry/{setup['project'].name}/{setup['device']}/sensors",
            json={"temperature": 22.4, "humidity": 60.0},
            headers=auth_headers(device_token),
        )
        assert resp.status_code == 200

    def test_last_seen_updated_without_touching_device_json(self, client, setup, projects_dir):
        """last_seen_at is written to .last_seen; device.json mtime must not change."""
        from app.core.device.backend import get_device, DEVICE_FILE_NAME, get_device_path

        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        device_token = resp.json()["accessToken"]

        dev_path = get_device_path(setup["project"].name, setup["device"])
        json_mtime_before = (dev_path / DEVICE_FILE_NAME).stat().st_mtime

        client.post(
            f"/api/telemetry/{setup['project'].name}/{setup['device']}/sensors",
            json={"v": 1},
            headers=auth_headers(device_token),
        )

        assert (dev_path / DEVICE_FILE_NAME).stat().st_mtime == json_mtime_before
        d = get_device(setup["project"].name, setup["device"])
        assert d.last_seen_at is not None

    def test_telemetry_stored_locally(self, client, setup, projects_dir):
        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        device_token = resp.json()["accessToken"]
        client.post(
            f"/api/telemetry/{setup['project'].name}/{setup['device']}/sensors",
            json={"temperature": 22.4},
            headers=auth_headers(device_token),
        )
        records = read_local_metrics(setup["project"].name, setup["device"])
        assert len(records) == 1
        assert records[0]["kind"] == "sensors"
        assert records[0]["v"]["temperature"] == 22.4

    def test_file_upload_then_download(self, client, setup):
        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        device_token = resp.json()["accessToken"]
        headers = auth_headers(device_token)

        resp = client.put(
            f"/api/file/{setup['project'].name}/{setup['device']}/config.json",
            content=b'{"version": 1}',
            headers=headers,
        )
        assert resp.status_code == 200

        resp = client.get(
            f"/api/file/{setup['project'].name}/{setup['device']}/config.json",
            headers=headers,
        )
        assert resp.status_code == 200
        assert b'"version"' in resp.content

    def test_log_push_accepted(self, client, setup):
        resp = client.post("/api/provision", json={
            "projectName": setup["project"].name,
            "deviceName": setup["device"],
            "provisioningToken": setup["prov_token"],
        })
        device_token = resp.json()["accessToken"]
        resp = client.post(
            f"/api/log/{setup['project'].name}/{setup['device']}",
            content=b"boot ok",
            headers=auth_headers(device_token),
        )
        assert resp.status_code == 200

    def test_reprovision_yields_fresh_token(self, client, setup):
        """Calling provision twice gives a second distinct working token."""
        def provision():
            return client.post("/api/provision", json={
                "projectName": setup["project"].name,
                "deviceName": setup["device"],
                "provisioningToken": setup["prov_token"],
            }).json()["accessToken"]

        token1 = provision()
        token2 = provision()
        assert token1 != token2

        # Both tokens must work independently.
        for token in (token1, token2):
            resp = client.post(
                f"/api/telemetry/{setup['project'].name}/{setup['device']}/sensors",
                json={"v": 1},
                headers=auth_headers(token),
            )
            assert resp.status_code == 200

    def test_expired_token_rejected(self, client, projects_dir, setup):
        """A provisioned device token with past expiry is rejected with 401."""
        from app.core.token.backend import create_token, save_device_tokens
        project_name = setup["project"].name
        device_name = setup["device"]

        # Force-create device by provisioning once.
        client.post("/api/provision", json={
            "projectName": project_name,
            "deviceName": device_name,
            "provisioningToken": setup["prov_token"],
        })

        # Replace token list with a single already-expired token.
        expired = create_token(datetime.timedelta(seconds=-1), length=32)
        save_device_tokens(project_name, device_name, [expired])

        resp = client.post(
            f"/api/telemetry/{project_name}/{device_name}/sensors",
            json={"v": 1},
            headers=auth_headers(expired.value),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Project-level file fallback
# ---------------------------------------------------------------------------

class TestProjectFileFallback:
    """Project-level files are served when no device-specific file exists."""

    def test_project_file_served_as_fallback(self, client, projects_dir):
        project, prov_token = setup_project(
            "fallback_project",
            is_autocreate_devices=True,
            is_provisioning_autoapproval=True,
        )
        resp = client.post("/api/provision", json={
            "projectName": project.name,
            "deviceName": "dev1",
            "provisioningToken": prov_token,
        })
        token = resp.json()["accessToken"]
        headers = auth_headers(token)

        # Write to the project directory directly (no device-specific copy).
        (projects_dir / project.name / "shared.json").write_text('{"shared": true}')

        resp = client.get(f"/api/file/{project.name}/dev1/shared.json", headers=headers)
        assert resp.status_code == 200
        assert b'"shared"' in resp.content

    def test_device_file_overrides_project(self, client, projects_dir):
        project, prov_token = setup_project(
            "override_project",
            is_autocreate_devices=True,
            is_provisioning_autoapproval=True,
        )
        resp = client.post("/api/provision", json={
            "projectName": project.name,
            "deviceName": "dev1",
            "provisioningToken": prov_token,
        })
        token = resp.json()["accessToken"]
        headers = auth_headers(token)

        # Place both project and device files.
        (projects_dir / project.name / "cfg.json").write_text('{"scope": "project"}')
        (projects_dir / project.name / "dev1" / "cfg.json").write_text('{"scope": "device"}')

        resp = client.get(f"/api/file/{project.name}/dev1/cfg.json", headers=headers)
        assert resp.status_code == 200
        assert b'"device"' in resp.content


class TestExtensionDeviceAuthEndToEnd:
    """An extension REST endpoint mounted with require_device_auth=True is
    reachable end-to-end with a real device bearer token, and rejects every
    request that lacks a valid one — the same contract the built-in device
    endpoints follow (see docs/extensions.md)."""

    @pytest.fixture
    def secure_ext_client(self, provisioned):
        """Full API app plus a device-authenticated extension route.

        Uses the real provisioning/token store from the `provisioned` fixture,
        so device_auth validates against genuinely issued tokens.
        """
        router = APIRouter()

        @router.get("/{project_name}/{device_name}/secret")
        async def secret(project_name: str, device_name: str):
            return {"project": project_name, "device": device_name}

        app = make_api_app()
        try:
            with registering("secure_ext"):
                mount_extension_router(app, router, require_device_auth=True)
            # Enable the extension for the provisioned device's project.
            adapter = project_adapter(provisioned["project_name"])
            project = adapter.read()
            project.enabled_extensions.append("secure_ext")
            adapter.save(project)
            yield TestClient(app), provisioned
        finally:
            extensions._clear_registries()

    def _url(self, ctx: dict) -> str:
        return f"/api/ext/secure_ext/{ctx['project_name']}/{ctx['device_name']}/secret"

    def test_valid_device_token_accepted(self, secure_ext_client):
        client, ctx = secure_ext_client
        resp = client.get(self._url(ctx),
                          headers={"Authorization": f"Bearer {ctx['device_token']}"})
        assert resp.status_code == 200
        assert resp.json() == {"project": ctx["project_name"],
                               "device": ctx["device_name"]}

    def test_missing_token_rejected_401(self, secure_ext_client):
        client, ctx = secure_ext_client
        resp = client.get(self._url(ctx))
        assert resp.status_code == 401

    def test_invalid_token_rejected_401(self, secure_ext_client):
        client, ctx = secure_ext_client
        resp = client.get(self._url(ctx),
                          headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401

    def test_disabled_extension_still_404(self, secure_ext_client):
        """The enablement gate runs regardless of auth: a valid token on a
        disabled extension is 404, not 200."""
        client, ctx = secure_ext_client
        adapter = project_adapter(ctx["project_name"])
        project = adapter.read()
        project.enabled_extensions.remove("secure_ext")
        adapter.save(project)
        resp = client.get(self._url(ctx),
                          headers={"Authorization": f"Bearer {ctx['device_token']}"})
        assert resp.status_code == 404

    def test_route_without_device_name_raises_at_mount(self, projects_dir):
        """require_device_auth needs device_name in the path; a route missing it
        is a loud failure at mount time, not a silent open endpoint."""
        router = APIRouter()

        @router.get("/{project_name}/oops")
        async def oops(project_name: str):
            return {}

        app = make_api_app()
        try:
            with registering("bad_ext"):
                with pytest.raises(RuntimeError, match="device_name"):
                    mount_extension_router(app, router, require_device_auth=True)
        finally:
            extensions._clear_registries()
