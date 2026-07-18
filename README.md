# nice4iot

An IoT device management platform written in Python. It provides a REST API for devices and a web-based management UI, both served from a single process.

---

## Features

- **Project & device management** — organise devices into projects, manage metadata and lifecycle via a web UI
- **Token-based provisioning** — devices self-register using a project-scoped provisioning token and receive a short-lived device token in return
- **Telemetry ingestion & charting** — devices push measurements; nice4iot forwards them to a time-series backend (Prometheus remote write or InfluxDB line protocol) and always stores the last 2 000 readings locally. The Data tab charts directly from the configured backend (long history) and falls back to the local ring buffer when none is set up. Recommended backend: [VictoriaMetrics](https://victoriametrics.com) via the Prometheus backend — `push_url: http://host:8428/api/v1/write`, `pull_url: http://host:8428/api/v1/`
- **Log ingestion** — devices push log lines; nice4iot forwards them to a log backend (Loki or local file); the UI shows a live tail of the file log
- **HTTP forwarding** — authenticated devices can proxy arbitrary requests through the platform to configured backend URLs
- **File serving & upload** — devices can fetch and upload files; device-specific files take precedence over project-wide defaults (ETag caching supported)
- **Auto-generated UI** — forms and tables are derived from Pydantic models via [niceview](https://github.com/clausgf/niceview), keeping model and UI in sync without boilerplate
- **Alarm system** — per-project alarm rules (metric thresholds + built-in device-offline rule); state-based with acknowledgment; alarm panels on project and device dashboards
- **System health** — project dashboard shows live green/red status for MQTT, telemetry, and logging backends; external-call errors are captured without raising exceptions
- **Extensions** — separately deployed packages can add their own REST endpoints, MQTT pub/sub, and UI cards/tabs, and get notified when a new device is provisioned; see [docs/extensions.md](docs/extensions.md)
- **Admin UI authentication** — optional, pluggable (`none`/`proxy`/`password`), disabled by default; see `app/auth/`

### Management UI tabs

| Page | Tabs |
|---|---|
| Projects list | — card grid |
| Project | Dashboard · General · Provisioning · Files · Devices |
| Device | Dashboard · General · Files · Data · Logs · Alarms |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com) |
| Web UI | [NiceGUI](https://nicegui.io) (Quasar/Vue under the hood) |
| Data modelling | [Pydantic v2](https://docs.pydantic.dev) |
| UI generation | [niceview](https://github.com/clausgf/niceview) (custom library) |
| Telemetry backends | [Prometheus](https://prometheus.io) remote write · [InfluxDB](https://influxdata.com) line protocol |
| Log backends | [Grafana Loki](https://grafana.com/oss/loki/) · rotating file |
| Persistence | Filesystem (JSON files + JSONL) |
| Package management | [uv](https://docs.astral.sh/uv/) |
| Runtime | [uvicorn](https://www.uvicorn.org) |
| Deployment | Docker / Docker Compose |

---

## Architecture

```
app/
├── main.py                 # FastAPI + NiceGUI entry point; lifespan starts MQTT + file watcher
├── config.py               # pydantic-settings (env vars / .env)
├── exceptions.py           # domain exceptions: NotFoundError, ForbiddenError, AuthError, …
├── paths.py                # project_dir(), device_dir() helpers
├── util.py                 # filename validation, render_datetime (configured timezone), …
├── frontend.py             # NiceGUI page, header, sub-page routing, user menu
├── api/
│   ├── provisioning.py     # POST /api/provision
│   ├── device.py           # POST /api/telemetry, /api/log, GET /api/forward
│   ├── file.py             # GET · PUT · HEAD /api/file
│   └── dependencies.py     # device_auth FastAPI dependency + domain_to_http()
├── mqtt/
│   ├── backend.py          # persistent MQTT client, topic routing, publish_file()
│   ├── models.py           # MqttGlobalConfig (server, port, credentials, client_id)
│   └── ui.py               # MqttGlobalConfigCard (live connection status)
└── core/
    ├── device/
    │   ├── backend.py      # Device CRUD, device_adapter(), last_seen helpers
    │   ├── models.py       # Device Pydantic model
    │   ├── ui.py           # device_subpage, Dashboard + General panel, DevicesTable
    │   ├── files_ui.py     # Files tab (browse, upload, download, edit, MQTT force-publish)
    │   ├── data_ui.py      # Data tab (multi-trace Plotly time-series explorer)
    │   └── logs_ui.py      # Logs tab (live tail, archive download)
    ├── file/
    │   ├── backend.py      # file state tracking (.mqtt_file_state.json), watcher loop
    │   ├── models.py       # FileConfig (max_upload_size, check_interval, QoS, retain)
    │   └── ui.py           # FileConfigCard (project settings)
    ├── project/
    │   ├── backend.py      # Project CRUD, project_adapter()
    │   ├── models.py       # Project Pydantic model
    │   └── ui.py           # all_projects_subpage, project_subpage, dashboard cards
    ├── token/
    │   ├── backend.py      # Token create / validate / persist / lock
    │   ├── models.py       # AuthToken Pydantic model
    │   └── ui.py           # TokenListCard
    ├── telemetry/
    │   ├── backend.py      # write_telemetry() + local JSONL store + read_local_metrics()
    │   ├── models.py       # TelemetryConfig
    │   ├── ui.py           # TelemetryCard (project settings)
    │   ├── prometheus/     # Prometheus remote write backend
    │   └── influxdb/       # InfluxDB line protocol backend
    ├── logging/
    │   ├── backend.py      # write_log()
    │   ├── models.py       # LoggingConfig
    │   ├── ui.py           # LoggingCard (project settings)
    │   ├── file/           # rotating file backend
    │   └── loki/           # Grafana Loki backend
    └── forwarding/
        ├── backend.py      # forward(), get_forwarding()
        ├── models.py       # ForwardingConfig
        └── ui.py           # ForwardingCard (project settings)

tests/
├── conftest.py                  # fixtures: projects_dir, client, provisioned, ...
├── test_acceptance.py           # end-to-end lifecycle (mark: acceptance)
├── test_api_device.py           # REST API for telemetry, log, forward
├── test_api_file.py             # REST file upload/download/head
├── test_api_provisioning.py     # provisioning flow, token lifecycle
├── test_auth.py                 # token generation, validation, purge (unit)
├── test_device_backend.py       # device_adapter, rename_device, file path fallback
└── test_telemetry_backend.py    # local JSONL store (_append_local_metrics, read_local_metrics)

tools/
└── device_client.py        # arduino4iot-compatible Python device simulator
```

FastAPI and NiceGUI share a single uvicorn process via `ui.run_with(app, ...)`. The REST API is reachable at `/api/*`; the NiceGUI UI occupies all other paths via `ui.sub_pages`.

---

## Core Concepts

### Data Storage

All state is stored on the filesystem under `data/projects/` (configurable via `PROJECTS_DIR` env var):

```
data/projects/
└── <project_name>/
    ├── .project.json           # Project settings (autosave)
    ├── .provisioning.json      # Provisioning token list
    ├── .telemetry.json         # Telemetry backend config
    ├── .logging.json           # Logging backend config
    ├── .forwards.json          # Named HTTP forwarding rules
    ├── <shared_file>           # Project-wide fallback files served to devices
    └── <device_name>/
        ├── .device.json        # Device settings (autosave, optimistic-locked)
        ├── .last_seen          # last_seen_at timestamp — written on every API auth,
        │                       # kept separate so device.json is only written on
        │                       # explicit user/provisioning actions (avoids lock conflict)
        ├── .tokens.json        # Device bearer token list (file-locked on write)
        ├── .device.log         # File logging backend output (rotated)
        ├── .device_metrics.jsonl  # Local telemetry ring buffer (max 2 000 lines)
        └── <device_file>       # Device-specific files (override project defaults)
```

Project and device names double as directory names; only `[a-zA-Z0-9_\-+]` are allowed. Path traversal is prevented by resolving and checking all paths against their expected base directory.

All writes use a write-to-temp-then-rename pattern to avoid partial writes.

### Two-Tier Token Model

1. **Provisioning tokens** — long-lived (default: 1 year), scoped to a project. Created in the UI and flashed into device firmware.
2. **Device tokens** — short-lived (default: 7 days), scoped to a device. Issued by `POST /api/provision` in exchange for a valid provisioning token.

On provisioning, the platform can optionally auto-create the device record (`is_autocreate_devices`) and auto-approve it (`is_provisioning_autoapproval`), or require explicit operator approval first.

Each device may hold at most **32 active tokens** simultaneously. When the cap is reached, the token with the oldest `last_use_at` is evicted before the new one is stored.

### Device Lifecycle

```
Provisioning request (provisioning token)
  → device created (if autocreate) or looked up
  → approval checked
  → device token issued (old expired tokens purged, cap enforced)
  → device uses device token for telemetry / log / file / forward endpoints
  → each authenticated request updates last_seen_at and token.last_use_at
```

### File Serving with Fallback

`GET /api/file/{project}/{device}/{filename}` looks for a device-specific file first, then falls back to a project-wide default. This lets you distribute common firmware / config to all devices while allowing per-device overrides. ETag-based caching (`If-None-Match` / `304 Not Modified`) is fully supported.

`PUT /api/file/{project}/{device}/{filename}` writes to the device-specific path atomically (via a temp file). The filename must contain only `[a-zA-Z0-9_\-.]` and must not contain `..`.

### Size Limits

| Resource | Limit | Config key |
|---|---|---|
| File upload | 10 MiB | `MAX_FILE_UPLOAD_SIZE` |
| Telemetry body | 8 KiB | `MAX_TELEMETRY_SIZE` |
| Log body | 8 KiB | `MAX_LOG_SIZE` |

Requests exceeding the limit are rejected with **413 Content Too Large**.

### Local Telemetry Store

Every call to `POST /api/telemetry` also appends a line to `<device>/.device_metrics.jsonl` (in addition to forwarding to any configured remote backend). The file is capped at 2 000 lines (oldest removed first). The **Device → Data** tab reads this file and renders an interactive Plotly chart with configurable time window and metric selector.

### UI Generation via niceview

Forms and tables are not coded by hand. [niceview](https://github.com/clausgf/niceview) inspects Pydantic models and generates NiceGUI widgets. Field metadata (labels, editability, widget type) is expressed via `niceview.Field(...)` annotations on the model. `ModelForm.from_adapter(..., autosave=True)` binds the form to a `JsonAdapter` and saves on every change, removing the need for explicit Save buttons.

### Lenient JSON loading

All config and data files (`.project.json`, `.device.json`, `.alarm_config.json`, `.tokens.json`, etc.) are read via `JsonAdapter` / `lenient_model_load` / `lenient_list_load` from [niceview](https://github.com/clausgf/niceview). The loaders tolerate hand-edited files:

| Situation | Behaviour |
|---|---|
| Malformed JSON | `log.error`, return model defaults |
| Unknown field | `log.error`, ignore the field |
| Bad field value | `log.error`, use model default for that field only |
| Missing required field (no default) | `log.error`, raise (last resort) |
| Bad item in a list | `log.error`, skip that item, keep the rest |

Exceptions are never raised for recoverable errors; each field is treated independently so a single corrupt value never blocks the rest of the document.

### Alarm System

Each project can define alarm rules that are evaluated whenever telemetry arrives or (for the built-in device-offline rule) by a background loop every 60 seconds.

**Metric rules** — configured under *Project → General → Alarms*. Each rule specifies a telemetry kind, metric name, comparison operator (`<`, `=`, `>`), and threshold. When the condition is met the first time an `AlarmEvent` is created with `is_active=True`. When the condition clears the event is resolved (`is_active=False`). Condition re-fires re-open a resolved event rather than creating a duplicate.

**Device offline rule** — built-in rule that fires when a device's `last_seen_at` is older than the project's online threshold (configured under *Project → General*). Enabled/disabled under *Project → General → Alarms*.

**Acknowledgment** — operators acknowledge individual events or all events at once. An acknowledged and resolved event is automatically pruned from storage on the next save. The **Device → Alarms** tab shows all events for one device; the **Project Dashboard** alarm panel shows project-wide events.

**Device alarm badge** — the project Devices table shows an *Alarms* column with the count of active unacknowledged alarms per device.

Storage: `<project>/.alarm_config.json` (rules) and `<project>/.alarm_events.json` (events), both written atomically.

### System Health

The *Project Dashboard* includes a **System Health** card showing the last known status of each external backend. Services tracked:

| Indicator | Source |
|---|---|
| MQTT | `connection_status` from `app/mqtt/backend.py` |
| Telemetry | Last write attempt to the configured remote backend (Prometheus / InfluxDB) |
| Logging | Last write attempt to the configured log backend (Loki / file) |

External-call errors are caught and recorded via `app/health.py` (`set_health(key, ok, message)`) instead of propagating exceptions. The dashboard card shows a green check or red error icon with the last error message.

---

## Device API Reference

All device endpoints require `Authorization: Bearer <device_token>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/provision` | Obtain a device token |
| `POST` | `/api/telemetry/{project}/{device}/{kind}` | Push numeric measurements (JSON) |
| `POST` | `/api/log/{project}/{device}` | Push log lines (plain text) |
| `GET` | `/api/file/{project}/{device}/{filename}` | Download a file |
| `HEAD` | `/api/file/{project}/{device}/{filename}` | Check file ETag (OTA) |
| `PUT` | `/api/file/{project}/{device}/{filename}` | Upload a file |
| `GET` | `/api/forward/{project}/{device}/{name}/{path}` | Proxy request to configured upstream |

Interactive API docs: `http://localhost:8000/docs`

---

## Device Client / Test Tool

`tools/device_client.py` is a Python simulation of an [arduino4iot](https://github.com/clausgf/arduino4iot) device. It implements the same HTTP flow as the C++ library and is useful for integration testing, demos, and load testing without needing real hardware.

```bash
# Full wake-up cycle (provision → config → OTA check → telemetry → log):
uv run python tools/device_client.py cycle \
    --url http://localhost:8000 \
    --project myproject \
    --device mydevice \
    --token <provisioning_token> \
    --sensors '{"temperature": 22.4, "humidity": 60}' \
    --log "Device started"

# Simulate periodic wake-ups every 30 s:
uv run python tools/device_client.py loop --interval 30 \
    --url http://localhost:8000 \
    --project myproject --device mydevice --token <token>

# Push telemetry only:
uv run python tools/device_client.py telemetry sensors \
    '{"temperature": 22.4}' ...

# Upload a config file:
uv run python tools/device_client.py upload myconfig.json ...
```

State (device token + ETag cache) is persisted in `.<device>.state.json` between invocations, mirroring NV-RAM on hardware.

---

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

### Setup

```bash
uv sync
```

Optional extensions are packaged as extras and are not installed by default.
To enable the [epaper-nice](https://gitlab.gwdg.de/epaper/epaper-nice)
extension (requires access to its repository):

```bash
uv sync --extra epaper
```

### Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs`

### Test

```bash
uv run pytest
```

### Configuration

Settings are read from environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `data/projects` | Root directory for all project and device data |
| `PROVISIONING_TOKEN_LENGTH` | `64` | Length of generated provisioning tokens |
| `PROVISIONING_TOKEN_EXPIRES_IN` | `365d` | Lifetime of provisioning tokens |
| `DEVICE_TOKEN_LENGTH` | `32` | Length of generated device tokens |
| `MAX_FILE_UPLOAD_SIZE` | `10485760` | Maximum file upload size in bytes (10 MiB) |
| `MAX_TELEMETRY_SIZE` | `8192` | Maximum telemetry body size in bytes (8 KiB) |
| `MAX_LOG_SIZE` | `8192` | Maximum log body size in bytes (8 KiB) |
| `TIMEZONE` | `Europe/Berlin` | Server timezone (for log timestamps) |
| `NICEGUI_STORAGE_SECRET` | `""` | Secret for NiceGUI session storage |
| `AUTH_PROVIDER` | `none` | Admin UI auth: `none`, `proxy` (reverse-proxy-forwarded identity), or `password` (built-in login, htpasswd) |
| `AUTH_USER_HEADERS` | see below | `proxy` provider: header names carrying the forwarded username, first non-empty wins |
| `AUTH_LOGOUT_URL` | `null` | `proxy` provider: logout link shown in the user menu (e.g. `/oauth2/sign_out`); unset hides it |
| `AUTH_HTPASSWD_FILE` | `data/htpasswd` | `password` provider: bcrypt htpasswd file, manage with `htpasswd -B` |

### Authentication

`AUTH_PROVIDER` selects how the UI authenticates users:

- `none` (default): no authentication (local development, or when
  access is already restricted at the network level).
- `proxy`: an authenticating reverse proxy in front of the app (e.g.
  Caddy with oauth2-proxy) handles the login; the app reads the
  forwarded identity from request headers.
  - `AUTH_USER_HEADERS`: JSON list of headers carrying the username
    (defaults match oauth2-proxy: `X-Forwarded-Preferred-Username`,
    `X-Forwarded-User`, `X-Forwarded-Email`); the first non-empty
    value is shown in the UI.
  - `AUTH_LOGOUT_URL`: logout link shown in the user menu, e.g.
    `/oauth2/sign_out`; unset hides the entry.
  - The headers are only trustworthy when the app is reachable
    exclusively through the proxy.
  - Deployment note (Caddy + oauth2-proxy): oauth2-proxy must be told
    to expose the identity (`--set-xauthrequest`, and/or
    `--pass-user-headers` when proxying through oauth2-proxy itself)
    and Caddy's `forward_auth` block must forward it to the app, e.g.

    ```
    forward_auth oauth2-proxy:4180 {
        uri /oauth2/auth
        copy_headers X-Auth-Request-Preferred-Username>X-Forwarded-Preferred-Username X-Auth-Request-User>X-Forwarded-User X-Auth-Request-Email>X-Forwarded-Email
    }
    ```

    Set `AUTH_LOGOUT_URL=/oauth2/sign_out` for a working logout entry.
    After deploying, check once which of the configured headers
    actually arrives and adjust `AUTH_USER_HEADERS` if needed.
- `password`: built-in login page. Users live in an htpasswd file with
  bcrypt hashes (`AUTH_HTPASSWD_FILE`, default `data/htpasswd`),
  maintained with the standard Apache tool:

  ```
  htpasswd -c -B data/htpasswd alice   # create file and first user
  htpasswd -B data/htpasswd bob        # add/update further users
  ```

  Only bcrypt entries (`-B`) are accepted; the file is re-read on each
  login attempt, so changes apply without a restart. Set a strong
  `NICEGUI_STORAGE_SECRET`, since it signs the session cookie.

---

## Deployment

```bash
docker compose up --build
```

Adjust `PUID`/`PGID` in `docker-compose.yml` to match your host user so volume-mounted files are owned correctly. The container expects external `loki` and `caddy_network` Docker networks to already exist.

---

## Design Decisions

**Filesystem instead of a database.**
JSON files keep the deployment dependency-free, make backup trivial (`rsync`), and make state directly inspectable. The tradeoff is no transactions, no foreign keys, and no efficient querying.

**Synchronous file I/O inside an async application.**
Backend functions are synchronous. Callers at the API or UI boundary wrap
IO-heavy backend calls with `anyio.to_thread.run_sync` to avoid blocking the
event loop. The telemetry hot path (`_append_local_metrics`) is wrapped inside
`write_telemetry`. This is the project-wide rule; see CLAUDE.md for details.

**Pluggable UI authentication, disabled by default.**
The REST API endpoints are protected by bearer tokens (a separate mechanism). The NiceGUI management UI has its own optional auth, selected via `AUTH_PROVIDER` (`none` by default) — see [Authentication](#authentication) above and `app/auth/`.

**In-process caches with TTL and SIGUSR1 flush.**
`get_devices()` (called on every Project Dashboard load) and `_get_active_backend()` (called on every telemetry push) cache their results for 60 seconds. Structural changes via the UI invalidate the device list cache immediately. Out-of-band filesystem changes (editing files directly, external scripts) are reflected after the 60 s TTL. To force an immediate flush without restarting, send `SIGUSR1`:

```bash
kill -USR1 <pid>
```

---

## MQTT Support

nice4iot maintains a **single persistent MQTT connection** shared across all projects. MQTT is enabled per-project via the `is_mqtt_enabled` flag.

### Topic structure

The topic base is configured per project (default: `/nice4iot/{project}/{device}`). Leading slashes and double slashes are normalised automatically. Substituting the project and device names gives topics like `nice4iot/myproject/sensor1/...`. The supported suffixes are:

| Suffix | Direction | Description |
|---|---|---|
| `telemetry/{kind}` | device → server | JSON payload with numeric measurements |
| `log` | device → server | UTF-8 plain-text log message |
| `upload/{filename}` | device → server | Raw file bytes |
| `download/{filename}` | server → device | File contents (published by nice4iot) |

`{base}/cmd/{name}` for server-to-device commands is planned but not yet implemented.

### File delivery

When a project has MQTT enabled, nice4iot publishes files to devices via the `download/{filename}` topic:

- **Periodic check** — every `mqtt_check_interval_s` seconds (default: 60 s) the watcher loop compares file mtimes against a per-device state file (`.mqtt_file_state.json`) and republishes any file that has changed.
- **Immediate publish** — files edited or uploaded via the UI are published immediately. The **Files** tab shows the last publication timestamp and offers a **force publish** button per file.
- **QoS and retain** — configurable per project. QoS 1 with a persistent device session is recommended. Retained messages allow devices that reconnect while the server is running to receive the latest file immediately.
- **Mosquitto message size** — the broker's own `message_size_limit` (mosquitto.conf) applies independently of nice4iot's `max_upload_size`. The Mosquitto default is 256 MB.

### Configuration

Global MQTT broker settings (server, port, credentials, client ID) are shared across all projects and can be changed in the **Projects** list page below the project grid. Per-project MQTT settings (topic base, QoS, retain, check interval) are in the project's **General** tab under _Files_.

### LoRaWAN / The Things Network

nice4iot's MQTT integration connects to an external MQTT broker using the server/port/credentials configured in the global MQTT settings. To receive TTN messages, point `server` at `<tenant>.cloud.thethings.network`. Note that TTN uses a different topic format and JSON payload structure — a payload adapter would be required to bridge TTN messages to nice4iot's expected format.

### Authentication TODO

MQTT authentication is currently managed by the broker. A future version will integrate with Mosquitto's Dynamic Security Plugin to provision per-device credentials automatically from the nice4iot UI.

---

## Open Questions / TODO

- **Forwarding security** — forwarding strips the `Authorization` header but forwards all other client headers verbatim; review whether this is appropriate for all backends.
- **Multi-user / RBAC** — all UI operators share the same access level.
- **Backup and restore** — no tooling or documentation for backup, restore, or migration of the `data/projects/` directory.
- **Pagination** — project and device lists load all items into memory; large deployments will need pagination.
- **Telemetry read from InfluxDB** — the Data tab reads from Prometheus-compatible backends (Prometheus, VictoriaMetrics, Mimir) with local fallback; a read path for the InfluxDB line-protocol backend (InfluxQL/Flux) is not implemented.
- **MQTT device commands** — `{base}/cmd/{name}` downlink topic for server-to-device commands is planned.
- **MQTT authentication** — currently managed by the broker. A future version will integrate with Mosquitto's Dynamic Security Plugin for per-device credential provisioning from the UI.
