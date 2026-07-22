"""New-project defaults seeded from DEFAULT_* / DEVICE_TOKEN_* env vars.

These verify that create_project() seeds a fresh project's telemetry, logging
and device-token settings from the environment, and that an unset env value
falls back to the model default (i.e. today's behaviour when nothing is set).
Everything stays editable per project afterwards — only the initial value is set.
"""
from app.config import app_config
from app.core.project.backend import create_project, project_adapter
from app.core.telemetry.backend import default_telemetry_config, get_telemetry_adapter
from app.core.logging.backend import default_logging_config, get_logging_adapter


def test_telemetry_factory_defaults_to_model_when_unset(projects_dir):
    """With no DEFAULT_TELEMETRY_* set, the factory equals a plain model config."""
    cfg = default_telemetry_config()
    assert cfg.backend == "none"
    assert cfg.prometheus.push_url == "http://localhost:8081/api/v1/push"
    assert cfg.influxdb.write_url == "http://localhost:8086/write"


def test_telemetry_factory_applies_env(projects_dir, monkeypatch):
    monkeypatch.setattr(app_config, "default_telemetry_backend", "prometheus")
    monkeypatch.setattr(app_config, "default_telemetry_prometheus_push_url", "http://vm:8428/api/v1/write")
    monkeypatch.setattr(app_config, "default_telemetry_prometheus_password", "secret")
    monkeypatch.setattr(app_config, "default_telemetry_influxdb_token", "tok")
    cfg = default_telemetry_config()
    assert cfg.backend == "prometheus"
    assert cfg.prometheus.push_url == "http://vm:8428/api/v1/write"
    assert cfg.prometheus.password == "secret"
    # untouched influx field keeps its model default; the set one is applied
    assert cfg.influxdb.write_url == "http://localhost:8086/write"
    assert cfg.influxdb.token == "tok"


def test_logging_factory_applies_env(projects_dir, monkeypatch):
    monkeypatch.setattr(app_config, "default_logging_loki_enabled", True)
    monkeypatch.setattr(app_config, "default_logging_loki_url", "http://loki:3100/loki/api/v1/push")
    cfg = default_logging_config()
    assert cfg.loki.is_active is True
    assert cfg.loki.log_url == "http://loki:3100/loki/api/v1/push"
    assert cfg.file.is_active is False  # local file backend has no env default


def test_create_project_seeds_from_env(projects_dir, monkeypatch):
    monkeypatch.setattr(app_config, "default_telemetry_backend", "prometheus")
    monkeypatch.setattr(app_config, "default_telemetry_prometheus_pull_url", "http://vm:8428/api/v1/")
    monkeypatch.setattr(app_config, "default_logging_loki_enabled", True)
    monkeypatch.setattr(app_config, "device_token_length", 48)
    monkeypatch.setattr(app_config, "device_token_expires_in", 30)

    create_project("weatherstation")

    project = project_adapter("weatherstation").read()
    assert project.device_token_length == 48
    assert project.device_tokens_expire_in == 30

    tel = get_telemetry_adapter("weatherstation").read()
    assert tel.backend == "prometheus"
    assert tel.prometheus.pull_url == "http://vm:8428/api/v1/"

    log = get_logging_adapter("weatherstation").read()
    assert log.loki.is_active is True


def test_create_project_without_env_matches_model_defaults(projects_dir):
    """Nothing set → the project keeps the plain model defaults (today's behaviour)."""
    create_project("plain")
    project = project_adapter("plain").read()
    assert project.device_token_length == 32
    assert project.device_tokens_expire_in == 7
    tel = get_telemetry_adapter("plain").read()
    assert tel.backend == "none"
