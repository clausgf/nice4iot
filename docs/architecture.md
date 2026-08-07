# Architecture

How nice4iot is put together, and why it is put together that way.

[← Documentation index](README.md) · [Project README](../README.md)

---

```
app/
├── main.py                 # FastAPI + NiceGUI entry point; lifespan starts MQTT + file watcher
├── config.py               # pydantic-settings (env vars / .env)
├── exceptions.py           # domain exceptions: NotFoundError, ForbiddenError, AuthError, …
├── paths.py                # project_dir(), device_dir() helpers
├── util.py                 # filename validation, render_datetime (configured timezone),
│                           # atomic_write, shadow_merge, …
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
    │   ├── data_ui.py      # Data tab (multi-trace Plotly time-series explorer)
    │   └── logs_ui.py      # Logs tab (live tail, archive download)
    ├── file/               # the file domain: transfer to devices + the admin editor
    │   ├── backend.py      # file state tracking (.mqtt_file_state.json), watcher loop
    │   ├── models.py       # FileConfig (max_upload_size, check_interval, QoS, retain)
    │   ├── ui.py           # FileConfigCard (project settings)
    │   ├── overlay.py      # device files layered over project files (FileCtx, entry, adapter)
    │   ├── form.py         # JSON form logic: inference, schema subset, approval, view plan
    │   ├── form_ui.py      # JSON Form tab: one FormField -> one widget
    │   ├── detail_ui.py    # Files tab, detail half (JSON/text editors, image preview)
    │   └── browser_ui.py   # Files tab, list half (rows, upload, new file, MQTT force-publish)
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

## Design Decisions

**Filesystem instead of a database.**
JSON files keep the deployment dependency-free, make backup trivial (`rsync`), and make state directly inspectable. The tradeoff is no transactions, no foreign keys, and no efficient querying.

**Synchronous file I/O inside an async application.**
Backend functions are synchronous. Callers at the API or UI boundary wrap
IO-heavy backend calls with `anyio.to_thread.run_sync` to avoid blocking the
event loop. The telemetry hot path (`_append_local_metrics`) is wrapped inside
`write_telemetry`. This is the project-wide rule; see CLAUDE.md for details.

**Device-supplied schemas are untrusted; forms are interpreted, not generated.**
The schema-driven file forms (see
[Core Concepts → Schema-driven JSON forms](concepts.md#schema-driven-json-forms))
accept a *minimal JSON-Schema subset*, not the full spec. The schema never
becomes a type: it is interpreted into a `FormField` whose `kind` is one of eight
literals we assign, and `app/core/file/form_ui.py` maps those to widgets. Only
then does niceview build the widget (`render_field()`, which needs no model) —
`pydantic.create_model` and `ModelForm` stay reserved for our own code-defined
models, because a model class is exactly what must not be built from device
input. A device-uploaded schema is inert until a user approves it, approval is
bound to its content hash, and schema text is never rendered as HTML/Markdown.
This keeps the untrusted-input path down to the schema parser plus one table,
and free of `$ref` (SSRF) and `pattern` (ReDoS) risk.

**The JSON form and the app's own forms share one widget layer.** Every form
backed by one of our Pydantic models goes through niceview's `ModelForm`; the
JSON form cannot, because its fields come from a schema rather than a class. Both
nonetheless render through the same `render_field()`/`field_value()` pair, so the
JSON form gets niceview's styling, validation layers and value conversions
without a model ever being generated — and stops being the one form in the app
that ages separately from the rest.

**Pluggable UI authentication, disabled by default.**
The REST API endpoints are protected by bearer tokens (a separate mechanism). The NiceGUI management UI has its own optional auth, selected via `AUTH_PROVIDER` (`none` by default) — see [Configuration → Authentication](configuration.md#authentication) and `app/auth/`.

**In-process caches with TTL and SIGUSR1 flush.**
`get_devices()` (called on every Project Dashboard load) and `_get_active_backend()` (called on every telemetry push) cache their results for 60 seconds. Structural changes via the UI invalidate the device list cache immediately. Out-of-band filesystem changes (editing files directly, external scripts) are reflected after the 60 s TTL. To force an immediate flush without restarting, send `SIGUSR1`:

```bash
kill -USR1 <pid>
```

**Telemetry data model — one shape across backends.**
A telemetry payload has four dimensions: **project**, **kind** (measurement
group), **device**, and the **field** names carrying the numeric values. Both
backends model them the same way, so the same reading looks structurally
identical whether it lands in a Prometheus- or an InfluxDB-compatible store:

| Dimension | Prometheus | InfluxDB |
|---|---|---|
| project | metric-name prefix (`weatherstation_…`) | measurement (`weatherstation`) |
| kind | label | tag |
| device | label | tag |
| field | metric-name suffix (`…_temperature`) | field key |
| value | sample | field value |

So `{"temperature": 22.4, "humidity": 60}` (kind `sensors`) becomes
`weatherstation_temperature{device="sensor_garden", kind="sensors"}` in Prometheus
and `weatherstation,device=sensor_garden,kind=sensors temperature=22.4,humidity=60`
in InfluxDB. `device` and `kind` are always *dimensions* (labels/tags); `field`
is always the measured quantity; a `_total` suffix marks a Prometheus counter.

**String fields are labels, carried by a synthetic info series.** A device may
also send *string* fields (`firmware_version`, `site`, …). Rather than attach
these as labels to every numeric series — which would rotate all of them on each
change — every write emits **one** synthetic `<project>_target_info{…} 1` series
(OpenMetrics `target_info` convention; an InfluxDB `<project>_target_info`
measurement; an `l{}` object in the local record) that carries all of that write's
labels. Numeric series stay clean and churn-free; a label is joined back at query
time with `* on(device) group_left(<label>) <project>_target_info`. Labels must be
low-cardinality and slowly changing (bounded name/value, ≤ 8 per write); a numeric
field named `target_info` is reserved and dropped. See
[Device API → String fields become labels](device-api.md#string-fields-become-labels).

**project is the namespace, not a label — a deliberate trade-off.** Idiomatic
Prometheus would make `project` a label (`iot_temperature{project="…"}`) to allow
cross-project aggregation. We instead bake it into the metric name / measurement:
in a shared VictoriaMetrics it namespaces each project cleanly and prevents
accidental cross-project name collisions. The cost is that aggregating *across*
projects needs a name matcher (`{__name__=~"..._temperature"}`) rather than a
`sum by`. For a device-management platform where projects are the primary tenancy
boundary, that isolation is worth more than easy cross-project rollups.
