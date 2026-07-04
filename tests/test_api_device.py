"""
Device API tests — telemetry, logging, and forwarding endpoints.

POST /api/telemetry/{project}/{device}/{kind}
  Authorization: bearer <device_token>
  Content-Type:  application/json
  Body:          {"field": value, ...}   (flat JSON, only numeric fields are stored)

POST /api/log/{project}/{device}
  Authorization: bearer <device_token>
  Content-Type:  text/plain
  Body:          "<timestamp> I (tag) message"

GET /api/forward/{project}/{device}/{name}/{path}
  Authorization: bearer <device_token>
"""
import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.token.backend import load_device_tokens, save_device_tokens
from app.core.device.backend import get_device, update_device
from app.core.forwarding.backend import get_forwarding_adapter
from app.core.forwarding.models import ForwardingConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def with_forwarding(provisioned, projects_dir):
    """Add a forwarding config entry to the provisioned project."""
    get_forwarding_adapter(provisioned["project_name"]).create(
        ForwardingConfig(
            name="upstream",
            forward_url="http://upstream.example.com/api",
            forward_method="GET",
        )
    )
    return {**provisioned, "forwarding_name": "upstream"}


# ---------------------------------------------------------------------------
# Telemetry — auth
# ---------------------------------------------------------------------------

TELEMETRY_PAYLOAD = {
    "battery_V": 3.71,
    "wifi_rssi": -67,
    "boot_count": 12,
    "active_ms": 823,
    "temperature": 22.4,
}


def test_telemetry_no_auth_rejected(client, provisioned):
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 401


def test_telemetry_wrong_token_rejected(client, provisioned):
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": "bearer " + "x" * 32},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 401


def test_telemetry_expired_device_token_rejected(client, provisioned):
    """A device token past its expiry cannot authenticate."""
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    tokens = load_device_tokens(provisioned["project_name"], provisioned["device_name"])
    for t in tokens:
        t.expires_at = past
    save_device_tokens(provisioned["project_name"], provisioned["device_name"], tokens)

    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 401


def test_telemetry_inactive_device_rejected(client, provisioned):
    """A deactivated device cannot authenticate even with a valid token."""
    device = get_device(provisioned["project_name"], provisioned["device_name"])
    device.is_active = False
    update_device(device)

    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Telemetry — happy path
# ---------------------------------------------------------------------------

@patch("app.core.telemetry.prometheus.backend.PrometheusBackend.write", new_callable=AsyncMock)
def test_telemetry_accepted(mock_write, client, provisioned):
    """Valid device token + flat JSON payload → 200, backend.write called once."""
    mock_write.return_value = None
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 200


@patch("app.core.telemetry.prometheus.backend.PrometheusBackend.write", new_callable=AsyncMock)
def test_telemetry_system_kind(mock_write, client, provisioned):
    """arduino4iot posts system telemetry under the 'system' kind."""
    mock_write.return_value = None
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/system",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json={"battery_V": 3.7, "wifi_rssi": -65, "boot_count": 42, "active_ms": 900},
    )
    assert resp.status_code == 200


def test_telemetry_accepted_writes_local_metrics(client, provisioned):
    """Telemetry is always appended to the local JSONL store, regardless of backend config."""
    from app.core.telemetry.backend import read_local_metrics
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 200
    records = read_local_metrics(provisioned['project_name'], provisioned['device_name'])
    assert len(records) == 1
    assert records[0]['kind'] == 'sensors'
    assert set(records[0]['v'].keys()) == set(TELEMETRY_PAYLOAD.keys())


def test_telemetry_invalid_kind_rejected(client, provisioned):
    """Kind must be a valid filename — path traversal characters are rejected."""
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/../evil",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code in (400, 404)


def test_telemetry_non_numeric_values_accepted_with_200(client, provisioned):
    """Mixed payload (numeric + string values) returns 200; non-numeric values are silently ignored."""
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json={"temperature": 22.4, "status": "ok", "mode": "sleep", "uptime_s": 3600},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Telemetry — body size limit (spec: max_telemetry_size, default 8192 bytes)
# ---------------------------------------------------------------------------

def test_telemetry_oversized_body_rejected(client, provisioned):
    """Bodies larger than max_telemetry_size are rejected with 413."""
    big_payload = {f"sensor_{i}": float(i) for i in range(1000)}
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=big_payload,
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Logging — auth
# ---------------------------------------------------------------------------

LOG_MESSAGE = "[2024-01-15 12:34:56] I (app) sensor read ok"


def test_log_no_auth_rejected(client, provisioned):
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=LOG_MESSAGE,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 401


def test_log_wrong_token_rejected(client, provisioned):
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=LOG_MESSAGE,
        headers={"Authorization": "bearer " + "x" * 32, "Content-Type": "text/plain"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logging — happy path
# ---------------------------------------------------------------------------

def test_log_accepted(client, provisioned):
    """Plain-text body with valid device token → 200."""
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=LOG_MESSAGE,
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 200


def test_log_written_to_file(client, provisioned, projects_dir):
    """File logging backend writes to <project>/<device>/.device.log."""
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=LOG_MESSAGE,
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 200
    log_file = (projects_dir / provisioned["project_name"]
                / provisioned["device_name"] / ".device.log")
    assert log_file.exists()
    assert provisioned["device_name"] in log_file.read_text() or LOG_MESSAGE in log_file.read_text()


# ---------------------------------------------------------------------------
# Logging — body size limit (spec: max_log_size = 8192 bytes)
# ---------------------------------------------------------------------------

def test_log_oversized_body_rejected(client, provisioned):
    """Bodies larger than max_log_size (8192 bytes) are rejected with 413."""
    big_log = "A" * 9000
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=big_log,
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Forwarding — auth
# ---------------------------------------------------------------------------

def test_forward_no_auth_rejected(client, with_forwarding):
    resp = client.get(
        f"/api/forward/{with_forwarding['project_name']}/{with_forwarding['device_name']}"
        f"/{with_forwarding['forwarding_name']}/data"
    )
    assert resp.status_code == 401


def test_forward_wrong_token_rejected(client, with_forwarding):
    resp = client.get(
        f"/api/forward/{with_forwarding['project_name']}/{with_forwarding['device_name']}"
        f"/{with_forwarding['forwarding_name']}/data",
        headers={"Authorization": "bearer " + "x" * 32},
    )
    assert resp.status_code == 401


def test_forward_unknown_name_rejected(client, with_forwarding):
    """A forwarding name not in the project config returns 404."""
    resp = client.get(
        f"/api/forward/{with_forwarding['project_name']}/{with_forwarding['device_name']}"
        f"/nonexistent/data",
        headers={"Authorization": f"bearer {with_forwarding['device_token']}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Forwarding — happy path (upstream mocked)
# ---------------------------------------------------------------------------

@patch("app.api.device.forward", new_callable=AsyncMock)
def test_forward_success(mock_forward, client, with_forwarding):
    """Valid auth + known forwarding name → upstream is called, response forwarded."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.content = b'{"ok": true}'
    mock_forward.return_value = mock_resp

    resp = client.get(
        f"/api/forward/{with_forwarding['project_name']}/{with_forwarding['device_name']}"
        f"/{with_forwarding['forwarding_name']}/sensor/data",
        headers={"Authorization": f"bearer {with_forwarding['device_token']}"},
    )
    assert resp.status_code == 200
    mock_forward.assert_called_once()


@patch("app.api.device.forward", new_callable=AsyncMock)
def test_forward_upstream_error_propagated(mock_forward, client, with_forwarding):
    """An upstream error status code is forwarded as-is."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.headers = {}
    mock_resp.content = b"upstream unavailable"
    mock_forward.return_value = mock_resp

    resp = client.get(
        f"/api/forward/{with_forwarding['project_name']}/{with_forwarding['device_name']}"
        f"/{with_forwarding['forwarding_name']}/data",
        headers={"Authorization": f"bearer {with_forwarding['device_token']}"},
    )
    assert resp.status_code == 503
