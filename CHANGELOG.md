# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.11.0] - 2026-07-22

### Added

- Container `HEALTHCHECK` polling `/health`, so `docker ps` reports healthy/
  unhealthy and Compose can restart on failure or gate `depends_on`. Runs
  directly against the app (independent of the reverse proxy / `--root-path`).
- Heuristic OpenMetrics UNIT metadata for the Prometheus backend: a recognised
  unit suffix (`_celsius`, `_bytes`, `_seconds`, …) fills the metric's unit.
  Additive — backends that ignore it (e.g. VictoriaMetrics) are unaffected.
- Documented VictoriaLogs as a supported log backend via the Loki push API
  (`…/insert/loki/api/v1/push?_stream_fields=project,device`) — no code, the
  existing Loki backend already speaks it, mirroring VictoriaMetrics.

### Changed

- **InfluxDB line-protocol data model** now mirrors the Prometheus backend:
  measurement is `<project>`, `kind` is a **tag** (was part of the measurement),
  and the redundant `project` tag is gone —
  `weatherstation,device=…,kind=sensors temperature=22.4`. **Breaking** for
  existing InfluxDB dashboards/queries built on the old `…_<kind>` measurement.
- The browser tab title is now `nice4iot` (was the framework default `NiceGUI`).

### Fixed

- Switching from dark back to light mode required a page refresh; both toggles
  now drive a single `ui.dark_mode()` instance and apply immediately.

## [0.10.0] - 2026-07-22

### Added

- `CORS_ALLOW_ORIGINS` environment variable controls which browser origins may
  call the REST API (default `["*"]`). A wildcard origin no longer advertises
  credentials, per the CORS spec. See docs/configuration.md.
- `MQTT_ENABLED` / `MQTT_SERVER` / `MQTT_PORT` / `MQTT_USERNAME` /
  `MQTT_PASSWORD` / `MQTT_CLIENT_ID` environment variables configure the global
  MQTT broker connection (see Changed).
- `DEFAULT_TELEMETRY_*` and `DEFAULT_LOGGING_LOKI_*` environment variables seed a
  new project's telemetry and logging config at creation time (Prometheus and
  InfluxDB backends, and Loki), so projects sharing one backend need no manual
  per-project setup. All values stay editable per project; unset = model default.
- `DEVICE_TOKEN_EXPIRES_IN` seeds a new project's device-token lifetime, and the
  previously-unused `DEVICE_TOKEN_LENGTH` now seeds `Project.device_token_length`.
  See docs/configuration.md.
- `mount_extension_router()` gained a `require_device_auth` keyword: when set,
  every route on the extension router requires a valid device bearer token
  (validated by the shared `device_auth` dependency, 401 otherwise), the same
  contract as the built-in device endpoints. It requires each route to carry a
  `device_name` path parameter and fails loudly at mount time otherwise. The
  default is `False` (enablement-gate only, unchanged). See docs/extensions.md.

### Changed

- The global MQTT broker connection is now configured through the `MQTT_*`
  environment variables instead of the UI, and is **disabled by default**
  (previously enabled, connecting to `localhost:1883`). The `.mqtt.json` file
  and its UI editor are gone; the Projects page shows the connection status
  read-only. This keeps the broker password out of the data volume. Per-project
  MQTT enablement is unchanged.

### Removed

- The `app.mqtt.models.MqttGlobalConfig` model and the global MQTT settings UI
  card, superseded by the `MQTT_*` environment variables above.

### Fixed

- Corrected the `POST /api/provision` 400-response description in the OpenAPI
  docs: project and device names must match `[a-zA-Z_][a-zA-Z0-9_]*` (letters,
  digits and underscore, no leading digit), not the `-`/`+` the text previously
  claimed. Only the documentation was wrong; validation was already stricter.
- Corrected the `Project.is_active` / `Device.is_active` field descriptions:
  an inactive project or device is rejected with **403 only on
  `POST /api/provision`**. On the device data endpoints (telemetry, log, file,
  forward) all auth failures — including inactive/disabled — are normalised to
  **401**, so the earlier "403 on all API calls" wording was wrong. Behaviour is
  unchanged; only the docs were corrected.

_0.9.0 was the first release; pre-release history is in the git log._
