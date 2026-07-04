# nice4iot

An IoT device management platform written in Python. It provides a REST API for devices and a web-based management UI, both served from a single process.

---

## Features

- **Project & device management** — organise devices into projects, manage metadata and lifecycle via a web UI
- **Token-based provisioning** — devices self-register using a project-scoped provisioning token and receive a short-lived device token in return
- **Telemetry ingestion** — devices push measurements; nice4iot forwards them to a time-series backend (Prometheus remote write or InfluxDB line protocol) and always stores the last 2 000 readings locally for in-app charting
- **Log ingestion** — devices push log lines; nice4iot forwards them to a log backend (Loki or local file); the UI shows a live tail of the file log
- **HTTP forwarding** — authenticated devices can proxy arbitrary requests through the platform to configured backend URLs
- **File serving & upload** — devices can fetch and upload files; device-specific files take precedence over project-wide defaults (ETag caching supported)
- **Auto-generated UI** — forms and tables are derived from Pydantic models via [niceview](https://github.com/clausgf/niceview), keeping model and UI in sync without boilerplate

### Management UI tabs

| Page | Tabs |
|---|---|
| Projects list | — card grid |
| Project | Dashboard · General · Provisioning · Devices |
| Device | Dashboard · General · Files · Data · Logs |

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
├── main.py                 # FastAPI + NiceGUI entry point
├── config.py               # pydantic-settings (env vars / .env)
├── paths.py                # project_dir(), device_dir() helpers
├── util.py                 # filename validation, render_datetime, ...
├── api/
│   ├── provisioning.py     # POST /api/provision
│   ├── device.py           # POST /api/telemetry, /api/log, GET /api/forward
│   ├── file.py             # GET · PUT · HEAD /api/file
│   └── dependencies.py     # device_auth FastAPI dependency
├── core/
│   ├── device/
│   │   ├── backend.py      # Device CRUD, device_adapter(), rename_device()
│   │   ├── models.py       # Device Pydantic model
│   │   ├── ui.py           # Dashboard + General panel, DevicesTable
│   │   ├── files_ui.py     # Files tab (browse, upload, download, delete)
│   │   ├── data_ui.py      # Data tab (Plotly time-series explorer)
│   │   └── logs_ui.py      # Logs tab (live tail, archive download)
│   ├── project/
│   │   ├── backend.py      # Project CRUD, project_adapter()
│   │   ├── models.py       # Project Pydantic model
│   │   └── ui.py           # Project pages, dashboard cards
│   ├── token/
│   │   ├── backend.py      # Token create / validate / persist
│   │   ├── models.py       # AuthToken Pydantic model
│   │   └── ui.py           # TokenListCard
│   ├── telemetry/
│   │   ├── backend.py      # write_telemetry() + local JSONL store + read_local_metrics()
│   │   ├── models.py       # TelemetryConfig
│   │   ├── ui.py           # TelemetryCard (project settings)
│   │   ├── prometheus/     # Prometheus remote write backend
│   │   └── influxdb/       # InfluxDB line protocol backend
│   ├── logging/
│   │   ├── backend.py      # write_log()
│   │   ├── models.py       # LoggingConfig
│   │   ├── ui.py           # LoggingCard (project settings)
│   │   ├── file/           # rotating file backend
│   │   └── loki/           # Grafana Loki backend
│   └── forwarding/
│       ├── backend.py      # forward(), get_forwarding()
│       ├── models.py       # ForwardingConfig
│       └── ui.py           # ForwardingCard (project settings)
└── ui/
    ├── frontend.py         # NiceGUI page + sub-page routing
    ├── theme.py            # header / frame
    └── util.py             # build_dialog()

tests/
├── conftest.py             # fixtures: projects_dir, client, provisioned, ...
├── test_api_device.py
├── test_api_file.py
├── test_api_provisioning.py
├── test_auth.py
├── test_device_backend.py  # device_adapter, rename_device
└── test_telemetry_backend.py  # local JSONL store (_append_local_metrics, read_local_metrics)

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
        ├── .device.json        # Device settings (autosave)
        ├── .tokens.json        # Device bearer token list
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
All blocking file reads and writes at the API boundary are wrapped with `anyio.to_thread.run_sync`. UI code runs synchronously inside NiceGUI's event loop — this is fine because NiceGUI's own `run_sync_in_threadpool` is used internally.

**No UI authentication.**
The REST API endpoints are protected by bearer tokens, but the NiceGUI management UI has no login. This is only safe when the UI is placed behind an authenticating reverse proxy (e.g., Caddy with forward auth).

**Telemetry config is re-read from disk on every request.**
`_get_active_backend()` opens and parses the telemetry config JSON on each inbound telemetry write. A simple in-process cache would remove the overhead but is not needed at the current scale.

---

## Open Questions / TODO

- **UI authentication** — implement a login screen or document the expectation that the UI is always behind an authenticating reverse proxy.
- **Forwarding security** — forwarding strips the `Authorization` header but forwards all other client headers verbatim; review whether this is appropriate for all backends.
- **Multi-user / RBAC** — all UI operators share the same access level.
- **Backup and restore** — no tooling or documentation for backup, restore, or migration of the `data/projects/` directory.
- **Pagination** — project and device lists load all items into memory; large deployments will need pagination.
- **Telemetry read from remote** — the Data tab currently reads only the local JSONL store; reading from InfluxDB or Prometheus (for historical data) is not yet implemented.
