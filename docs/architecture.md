# Architecture

How nice4iot is put together, and why it is put together that way.

[← Documentation index](README.md) · [Project README](../README.md)

---

# Architecture

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

# Design Decisions

**Filesystem instead of a database.**
JSON files keep the deployment dependency-free, make backup trivial (`rsync`), and make state directly inspectable. The tradeoff is no transactions, no foreign keys, and no efficient querying.

**Synchronous file I/O inside an async application.**
Backend functions are synchronous. Callers at the API or UI boundary wrap
IO-heavy backend calls with `anyio.to_thread.run_sync` to avoid blocking the
event loop. The telemetry hot path (`_append_local_metrics`) is wrapped inside
`write_telemetry`. This is the project-wide rule; see CLAUDE.md for details.

**Pluggable UI authentication, disabled by default.**
The REST API endpoints are protected by bearer tokens (a separate mechanism). The NiceGUI management UI has its own optional auth, selected via `AUTH_PROVIDER` (`none` by default) — see [Configuration → Authentication](configuration.md#authentication) and `app/auth/`.

**In-process caches with TTL and SIGUSR1 flush.**
`get_devices()` (called on every Project Dashboard load) and `_get_active_backend()` (called on every telemetry push) cache their results for 60 seconds. Structural changes via the UI invalidate the device list cache immediately. Out-of-band filesystem changes (editing files directly, external scripts) are reflected after the 60 s TTL. To force an immediate flush without restarting, send `SIGUSR1`:

```bash
kill -USR1 <pid>
```
