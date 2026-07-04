# nice4iot

An IoT device management platform written in Python. It provides a REST API for devices and a web-based management UI, both served from a single process.

---

## Features

- **Project & device management** — organise devices into projects, manage metadata and lifecycle via a web UI
- **Token-based provisioning** — devices self-register using a project-scoped provisioning token and receive a short-lived device token in return
- **Telemetry ingestion** — devices push measurements; nice4iot forwards them to a time-series backend (Prometheus)
- **Log ingestion** — devices push log lines; nice4iot forwards them to a log backend (Loki)
- **HTTP forwarding** — authenticated devices can proxy arbitrary GET/POST/PUT/HEAD/DELETE requests through the platform to configured backend URLs
- **File serving** — devices can fetch and upload files; device-specific files take precedence over project-wide defaults
- **Auto-generated UI** — forms and tables are derived from Pydantic models via [niceview](https://github.com/clausgf/niceview), keeping model and UI in sync without boilerplate

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | [FastAPI](https://fastapi.tiangolo.com) |
| Web UI | [NiceGUI](https://nicegui.io) (Quasar/Vue under the hood) |
| Data modelling | [Pydantic v2](https://docs.pydantic.dev) |
| UI generation | [niceview](https://github.com/clausgf/niceview) (custom library) |
| Telemetry backend | [Prometheus](https://prometheus.io) (remote write) |
| Log backend | [Loki](https://grafana.com/oss/loki/) (via Protobuf + Snappy) |
| Persistence | Filesystem (JSON files) |
| Package management | [uv](https://docs.astral.sh/uv/) |
| Runtime | [uvicorn](https://www.uvicorn.org) |
| Deployment | Docker / Docker Compose |

---

## Architecture

```
nice4iot/
├── app/
│   ├── main.py            # FastAPI app + NiceGUI integration entry point
│   ├── config.py          # Settings via pydantic-settings (env vars)
│   ├── api/               # FastAPI routers
│   │   ├── provisioning.py    # POST /api/provision
│   │   ├── device.py          # POST /api/telemetry, /api/log, /api/forward
│   │   ├── file.py            # GET/PUT/HEAD /api/file
│   │   └── dependencies.py    # Shared FastAPI dependency: device auth
│   ├── core/              # Business logic, no HTTP concerns
│   │   ├── models.py          # Pydantic models: Project, Device, AuthToken, Tag
│   │   ├── project.py         # Project CRUD + ProjectModelAdapter for UI
│   │   ├── device.py          # Device CRUD + provisioning logic
│   │   ├── auth.py            # Token generation and validation
│   │   ├── forwarding/        # HTTP proxy logic + ForwardingModel
│   │   ├── telemetry/         # Prometheus remote write backend
│   │   └── logging/           # Loki backend
│   └── ui/                # NiceGUI page definitions
│       ├── frontend.py        # Page layout, routing, sub-pages
│       ├── project.py         # Project list and detail pages
│       ├── device.py          # Device detail page (tabs: Dashboard, Settings, Data, Logs)
│       └── *_config_card.py   # UI cards for backend configuration
└── tests/
    ├── test_api_device.py
    ├── test_api_file.py
    └── test_api_provisioning.py
```

FastAPI and NiceGUI share a single uvicorn process via `ui.run_with(app, ...)`. The REST API is reachable at `/api/*`; the NiceGUI UI occupies `/` and handles all sub-paths via `ui.sub_pages`.

---

## Core Concepts

### Data Storage

All state is stored on the filesystem under `data/projects/` (configurable via `PROJECTS_DIR` env var):

```
data/projects/
└── <project_name>/
    ├── .project.json            # Project metadata + provisioning tokens
    ├── .telemetry_config.json   # Per-project telemetry backend config
    ├── .forwards.json           # Named HTTP forwarding rules
    ├── <shared_file>            # Project-wide default files served to devices
    └── <device_name>/
        ├── .device.json         # Device metadata + device tokens
        └── <device_file>        # Device-specific files (override project defaults)
```

Project and device names double as directory names and are therefore validated as safe filenames. Path traversal is explicitly prevented by resolving and checking all paths against their expected base directory.

Writes use a write-to-temp-then-rename pattern to avoid partial writes.

### Two-Tier Token Model

1. **Provisioning tokens** — long-lived, scoped to a project. An operator creates these manually in the UI and distributes them to device firmware at flash time.
2. **Device tokens** — short-lived (default: 7 days), scoped to a device. Issued by `POST /api/provision` in exchange for a valid provisioning token.

On provisioning, the platform can optionally auto-create the device record (`is_autocreate_devices`) and auto-approve it (`is_provisioning_autoapproval`), or require explicit operator approval first.

### Device Lifecycle

```
Provisioning request (provisioning token)
  → device created (if autocreate) or looked up
  → approval checked
  → device token issued
  → device uses device token for telemetry / log / file / forward endpoints
```

Every authenticated device request updates `last_seen_at` and `token.last_use_at`.

### File Serving with Fallback

`GET /api/file/{project}/{device}/{filename}` first looks for a device-specific file, then falls back to a project-wide default. This allows distributing common configuration to all devices while still permitting per-device overrides. ETag-based caching is supported.

### UI Generation via niceview

Forms and tables are not coded by hand. [niceview](https://github.com/clausgf/niceview) inspects a Pydantic model and generates matching NiceGUI widgets. Field metadata (labels, visibility, validation, table column config) is expressed via `niceview.Field(...)` annotations on the model.

The library provides three rendering components:

| Component | Renders as | Backend |
|---|---|---|
| `ModelGrid` | ag-Grid table, read-only or with inline editing (`ModelGridInlineEdit`) | `ui.aggrid` |
| `ModelList` | Quasar list with title/subtitle lines, suited for mobile/touch | `ui.list` / `ui.item` |
| `ModelForm` | Field-by-field form with validation feedback | various `ui.*` widgets |

`DrillDownWrapper` composes `ModelList` and `ModelForm` into a two-page mobile-friendly flow (list page → detail/edit page) and registers both as NiceGUI routes automatically. On desktop it renders the list and form side by side.

Data access is decoupled via adapters:

| Adapter | Source |
|---|---|
| `ListAdapter` | In-memory Python list (plain or `ObservableList` for auto-refresh) |
| `JsonListAdapter` | JSON file on disk |
| `CollectionAdapter` | Abstract base — implement `create / read / update / delete` for custom backends |

nice4iot uses a custom `ModelDataAdapter` / `ProjectModelAdapter` that bridges the adapter interface to the filesystem CRUD functions in `app/core/project.py`.

---

## Design Decisions and Accepted Technical Debt

**Filesystem instead of a database.**
Storing state as JSON files in directories keeps the deployment dependency-free (no database server), makes backup trivial (`rsync`), and makes state directly inspectable. The tradeoff is the absence of transactions, foreign-key constraints, and efficient querying. `SQLModel` is already a dependency (used transitively by niceview) but is not yet used for persistence.

**Synchronous file I/O inside an async application.**
All blocking file reads and writes are wrapped with `anyio.to_thread.run_sync` at the API handler level so they do not block the event loop. The `CollectionAdapter` protocol methods remain synchronous (imposed by niceview's structural typing), which is a reasonable tradeoff — they are called from async handlers and already run in a thread pool.

**No UI authentication.**
The REST API endpoints are protected by bearer tokens, but the NiceGUI management UI has no login. This is only safe when the UI is placed behind a reverse proxy with its own authentication (e.g., Caddy with forward auth) as implied by the `docker-compose.yml` network setup. This should be made explicit in deployment documentation or solved in the application.

**Telemetry config is re-read from disk on every request.**
`get_tel()` opens and parses `.telemetry_config.json` on each inbound telemetry write. A simple in-process cache (per-project, invalidated on config change) would remove the overhead.

---

## Open Questions / TODO

- **UI authentication** — implement a login screen or formally document the expectation that the UI is always behind an authenticating reverse proxy.
- **Dashboard tab** — the Project › Dashboard tab exists but shows placeholder content; real-time telemetry charts and alarms are not yet implemented.
- **Log viewer tab** — no log viewer in the UI; Loki query integration is missing.
- **Additional telemetry backends** — Influx2 and SQL stubs are commented out; only Prometheus is functional.
- **Forwarding security** — forwarding strips the `Authorization` header but forwards all other client headers verbatim; review whether this is appropriate for all backends.
- **Multi-user / RBAC** — there is no concept of users or roles; all UI operators share the same access level.
- **Backup and restore** — no tooling or documentation for backup, restore, or migration of the `data/projects/` directory.
- **Pagination** — project and device lists load all items into memory; large deployments will need pagination at the API and UI level.
- Creation dialogs for project and device are quite similay - generic dialog? interface?

---

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

### Setup

```bash
# Install dependencies
uv sync

# For local niceview development (use editable install instead of git source)
uv add --editable ../niceview
```

### Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs are available at `http://localhost:8000/docs`.

### Test

```bash
uv run pytest
```

### Configuration

All settings are read from environment variables (via pydantic-settings):

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `data/projects` | Root directory for project and device data |
| `PROVISIONING_TOKEN_LENGTH` | `64` | Length of generated provisioning tokens |
| `DEVICE_TOKEN_LENGTH` | `32` | Length of generated device tokens |
| `MAX_UPLOAD_SIZE` | `1048576` | Maximum file upload size in bytes (1 MB) |
| `TIMEZONE` | `Europe/Berlin` | Server timezone |

---

## Deployment

Build and run with Docker Compose:

```bash
docker compose up --build
```

Adjust `PUID`/`PGID` in `docker-compose.yml` to match your host user so volume-mounted files are owned correctly. The container expects external `loki` and `caddy_network` Docker networks to already exist.
