# Core Concepts

The domain model: how state is stored, how devices authenticate, and how telemetry, alarms and health tracking work.

[← Documentation index](README.md) · [Project README](../README.md)

---

## Data Storage

All state is stored on the filesystem under `data/projects/` (configurable via `PROJECTS_DIR` env var):

```
data/projects/
└── <project_name>/
    ├── .project.json           # Project settings (autosave)
    ├── .provisioning.json      # Provisioning token list
    ├── .telemetry.json         # Telemetry backend config
    ├── .logging.json           # Logging backend config
    ├── .forwards.json          # Named HTTP forwarding rules
    ├── .firmware.json          # Firmware source (GitHub repo) for project-wide firmware.bin
    ├── .firmware.state.json    # Last firmware pull: tag, digest, pulled_at, etag
    ├── <shared_file>           # Project-wide fallback files served to devices
    └── <device_name>/
        ├── .device.json        # Device settings (autosave, optimistic-locked)
        ├── .firmware.json          # Optional per-device firmware source (overrides project)
        ├── .firmware.state.json    # Last firmware pull for this device
        ├── .runtime.json       # device-reported runtime state: last_seen_at (written on
        │                       # every API auth) + firmware_version/commit (reported via
        │                       # X-Firmware-* headers). Kept separate so device.json is only
        │                       # written on explicit user/provisioning actions (avoids lock conflict)
        ├── .tokens.json        # Device bearer token list (file-locked on write)
        ├── .device.log         # File logging backend output (rotated)
        ├── .device_metrics.jsonl  # Local telemetry ring buffer (max 2 000 lines)
        ├── .data_view.json     # Persisted Data-tab explorer config (window + traces)
        └── <device_file>       # Device-specific files (override project defaults)
```

Project and device names double as directory names and as the telemetry metric-name prefix, so they must be valid identifiers: `[a-zA-Z_][a-zA-Z0-9_]*` (letters, digits and underscore only, no leading digit, no `-`/`+`). This guarantees a valid Prometheus metric name `<project>_<field>` and needs no backend-specific escaping. Path traversal is prevented by resolving and checking all paths against their expected base directory.

> **Upgrading:** earlier versions allowed `-` and `+` in names. A project or device directory whose name violates the rule above is no longer listed or accessible — rename it on disk (e.g. `my-proj` → `my_proj`) before upgrading.

All writes use a write-to-temp-then-rename pattern to avoid partial writes.

## Two-Tier Token Model

1. **Provisioning tokens** — long-lived (default: 1 year), scoped to a project. Created in the UI and flashed into device firmware.
2. **Device tokens** — short-lived (default: 7 days), scoped to a device. Issued by `POST /api/provision` in exchange for a valid provisioning token.

On provisioning, the platform can optionally auto-create the device record (`is_autocreate_devices`) and auto-approve it (`is_provisioning_autoapproval`), or require explicit operator approval first.

Each device may hold at most **32 active tokens** simultaneously. When the cap is reached, the token with the oldest `last_use_at` is evicted before the new one is stored.

## Device Lifecycle

```
Provisioning request (provisioning token)
  → device created (if autocreate) or looked up
  → approval checked
  → device token issued (old expired tokens purged, cap enforced)
  → device uses device token for telemetry / log / file / forward endpoints
  → each authenticated request updates last_seen_at and token.last_use_at
```

## File Serving with Fallback

`GET /api/file/{project}/{device}/{filename}` looks for a device-specific file first, then falls back to a project-wide default. This lets you distribute common firmware / config to all devices while allowing per-device overrides. Conditional caching is fully supported via both `If-None-Match` (ETag) and `If-Modified-Since` (`Last-Modified`) — either results in `304 Not Modified` when unchanged; per RFC 7232 §3.3, `If-None-Match` takes precedence when a request sends both.

`PUT /api/file/{project}/{device}/{filename}` writes to the device-specific path atomically (via a temp file). The filename must contain only `[a-zA-Z0-9_\-.]` and must not contain `..`.

### Editing files in the UI

The **Files** tab (project and device) browses the same directories with a drill-down editor: JSON and recognised text files edit inline, images preview inline, other binaries download only. A flat JSON object also gets a **Form** view. Dropping a sibling `<name>.schema.json` (a small JSON-Schema subset) turns that into a proper form with typed widgets and validation — the device may upload the schema, but it stays inert until a user **approves** it (approval is bound to the schema's content hash, so a device changing it forces re-approval). See [File Editing & Forms](file-forms.md).

## Size Limits

| Resource | Limit | Config key |
|---|---|---|
| File upload | 10 MiB | `MAX_FILE_UPLOAD_SIZE` |
| Telemetry body | 8 KiB | `MAX_TELEMETRY_SIZE` |
| Log body | 8 KiB | `MAX_LOG_SIZE` |

Requests exceeding the limit are rejected with **413 Content Too Large**.

## Local Telemetry Store

Every call to `POST /api/telemetry` also appends a line to `<device>/.device_metrics.jsonl` (in addition to forwarding to any configured remote backend). The file is capped at 2 000 lines (oldest removed first). The **Device → Data** tab reads this file and renders an interactive Plotly chart with configurable time window and metric selector.

## UI Generation via niceview

Forms and tables are not coded by hand. [niceview](https://github.com/clausgf/niceview) inspects Pydantic models and generates NiceGUI widgets. Field metadata (labels, editability, widget type) is expressed via `niceview.Field(...)` annotations on the model. `ModelForm.from_adapter(..., autosave=True)` binds the form to a `JsonAdapter` and saves on every change, removing the need for explicit Save buttons.

## Lenient JSON loading

All config and data files (`.project.json`, `.device.json`, `.alarm_config.json`, `.tokens.json`, etc.) are read via `JsonAdapter` / `lenient_model_load` / `lenient_list_load` from [niceview](https://github.com/clausgf/niceview). The loaders tolerate hand-edited files:

| Situation | Behaviour |
|---|---|
| Malformed JSON | `log.error`, return model defaults |
| Unknown field | `log.error`, ignore the field |
| Bad field value | `log.error`, use model default for that field only |
| Missing required field (no default) | `log.error`, raise (last resort) |
| Bad item in a list | `log.error`, skip that item, keep the rest |

Exceptions are never raised for recoverable errors; each field is treated independently so a single corrupt value never blocks the rest of the document.

## Alarm System

Each project can define alarm rules that are evaluated whenever telemetry arrives or (for the built-in device-offline rule) by a background loop every 60 seconds.

**Metric rules** — configured under *Project → General → Alarms*. Each rule specifies a telemetry kind, metric name, comparison operator (`<`, `=`, `>`), and threshold. The *Kind* and *Metric* fields are comboboxes seeded from the names actually seen in the local telemetry store (the *Metric* list follows the selected *Kind*); a not-yet-observed name can still be typed in. When the condition is met the first time an `AlarmEvent` is created with `is_active=True`. When the condition clears the event is resolved (`is_active=False`). Condition re-fires re-open a resolved event rather than creating a duplicate.

**Device offline rule** — built-in rule that fires when a device's `last_seen_at` is older than the project's online threshold (configured under *Project → General*). Enabled/disabled under *Project → General → Alarms*.

**Acknowledgment** — operators acknowledge individual events or all events at once. An acknowledged and resolved event is automatically pruned from storage on the next save. The **Device → Alarms** tab shows all events for one device; the **Project Dashboard** alarm panel shows project-wide events.

**Device alarm badge** — the project Devices table shows an *Alarms* column with the count of active unacknowledged alarms per device.

Storage: `<project>/.alarm_config.json` (rules) and `<project>/.alarm_events.json` (events), both written atomically.

## System Health

The *Project Dashboard* includes a **System Health** card showing the last known status of each external backend. Services tracked:

| Indicator | Source |
|---|---|
| MQTT | `connection_status` from `app/mqtt/backend.py` |
| Telemetry | Last write attempt to the configured remote backend (Prometheus / InfluxDB) |
| Logging | Last write attempt to the configured log backend (Loki / file) |

External-call errors are caught and recorded via `app/health.py` (`set_health(key, ok, message)`) instead of propagating exceptions. The dashboard card shows a green check or red error icon with the last error message.
