"""
Device API tests — telemetry and log endpoints as sent by arduino4iot.

POST /api/telemetry/{project}/{device}/{kind}
  Authorization: bearer <device_token>
  Content-Type:  application/json
  Body:          {"field": value, ...}   (flat JSON, arbitrary numeric fields)

POST /api/log/{project}/{device}
  Authorization: bearer <device_token>
  Content-Type:  text/plain
  Body:          "<timestamp> I (tag) message"
"""
import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Telemetry
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


@patch("app.core.telemetry.prometheus.prometheus_telemetry.PrometheusBackend.write", new_callable=AsyncMock)
def test_telemetry_accepted(mock_write, client, provisioned):
    """Valid device token + flat JSON payload → 200, backend.write called once."""
    mock_write.return_value = None
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/sensors",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code == 200
    mock_write.assert_called_once()


@patch("app.core.telemetry.prometheus.prometheus_telemetry.PrometheusBackend.write", new_callable=AsyncMock)
def test_telemetry_system_kind(mock_write, client, provisioned):
    """arduino4iot posts system telemetry under the 'system' kind."""
    mock_write.return_value = None
    system_payload = {
        "battery_V": 3.7,
        "wifi_rssi": -65,
        "boot_count": 42,
        "active_ms": 900,
        "lastSleep_s": 300,
        "firmware_version": "1.2.3",
    }
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/system",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=system_payload,
    )
    assert resp.status_code == 200


def test_telemetry_invalid_kind_rejected(client, provisioned):
    """Kind must be a valid filename — path traversal characters are rejected."""
    resp = client.post(
        f"/api/telemetry/{provisioned['project_name']}/{provisioned['device_name']}/../evil",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        json=TELEMETRY_PAYLOAD,
    )
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Logging
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
        headers={
            "Authorization": "bearer " + "x" * 32,
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 401


def test_log_accepted(client, provisioned):
    """Plain-text log message with valid device token is accepted."""
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
    """File logging backend appends the message to the project log file."""
    resp = client.post(
        f"/api/log/{provisioned['project_name']}/{provisioned['device_name']}",
        content=LOG_MESSAGE,
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 200

    log_file = projects_dir / provisioned["project_name"] / ".device.log"
    assert log_file.exists()
    assert provisioned["device_name"] in log_file.read_text()
