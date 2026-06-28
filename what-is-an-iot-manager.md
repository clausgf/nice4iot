# What Is an IoT Manager?

An IoT manager (also called an IoT platform or IoT backend) is the server-side software that connects, organises, and monitors a fleet of embedded devices. It sits between the physical hardware and the applications that consume device data. Its job is to abstract away the operational complexity of running many devices in the field: authentication, connectivity, data ingestion, configuration delivery, firmware updates, and alerting — so that application developers can focus on business logic rather than infrastructure.

---

## Core Features

### 1. Protocol Support

Devices speak different languages. Constrained microcontrollers often use lightweight protocols such as **MQTT** (message queue, pub/sub, low overhead) or plain **HTTP/REST** (request/response, firewall-friendly). Industrial devices may use AMQP, CoAP, or proprietary protocols. A capable IoT manager either supports multiple protocols natively or provides a gateway layer that normalises them into a common internal representation.

### 2. Device Management

Device management is the operational backbone of any IoT platform. It encompasses:

- **Device registry** — a persistent store of every known device with its metadata (name, location, project, tags).
- **Onboarding / provisioning** — the controlled process by which a new device authenticates itself for the first time and receives credentials for ongoing operation.
- **Status tracking** — recording when a device was last seen, whether it is considered online or offline, and surfacing that state in the management UI.

### 3. Authentication and Authorisation

Securing device communication is non-trivial at scale. Approaches include:

- **TLS with client certificates** — strong but requires PKI infrastructure and certificate lifecycle management.
- **Bearer tokens / API keys** — simpler to implement; key rotation and expiry are handled in software.
- **User and role management (RBAC)** — controlling which human operators can view or modify which devices, projects, or configuration.

### 4. Data Ingestion and Time-Series Storage

The core data flow: devices send measurements → the platform validates, routes, and stores them → queries retrieve historical data for dashboards and analysis. A time-series database (e.g. Prometheus, InfluxDB, TimescaleDB) is purpose-built for this workload: high write throughput, efficient range queries, automatic downsampling and retention policies.

### 5. Data Visualisation

Raw time-series data becomes useful when rendered as charts. A built-in dashboard layer lets operators inspect trends, compare devices, and spot anomalies without leaving the platform. Most platforms integrate with Grafana or provide their own charting UI.

### 6. Data Validation and Schema

Devices may send malformed, out-of-range, or inconsistently unitised payloads. Schema enforcement (e.g. JSON Schema validation) and unit normalisation (°C vs °F, V vs mV) at ingestion time prevent corrupt data from reaching the database silently.

### 7. Logging

Device log output (debug messages, error reports, state transitions) needs to be collected, timestamped, and stored separately from telemetry. A dedicated log aggregation backend (e.g. Grafana Loki) provides full-text search and per-device log streams. Structured logging enables filtering by severity or tag.

### 8. Remote Configuration and OTA Updates

Devices need to receive updated configuration (API endpoints, sampling intervals, thresholds) and firmware without physical access. This requires:

- **Config delivery** — serving per-device or per-project configuration files, ideally with cache-friendly conditional HTTP (ETag / `If-None-Match`) to minimise unnecessary downloads.
- **OTA firmware updates** — hosting firmware binaries and signalling devices to download and apply them; integrity verification (hash/signature) is essential.

### 9. Alerting and Rule Engine

Reactive behaviour turns a passive data store into an operational tool. Threshold alerts fire when a measurement exceeds a limit; a rule engine can express more complex conditions ("if battery voltage < 3.3 V for more than 5 minutes, send a notification"). Notifications are delivered via email, webhook, or messaging platform.

### 10. Persistence Strategy: Store-and-Forward

Devices operating over unreliable networks (cellular, LoRa, intermittent Wi-Fi) may lose connectivity at any time. A robust persistence strategy includes client-side buffering (the device queues measurements locally) and server-side idempotency (re-delivered data does not create duplicates). The platform should accept out-of-order data with device-supplied timestamps rather than server arrival time.

### 11. Logging and Monitoring of the Platform Itself

The IoT manager is itself a service that needs observability: application logs, request latency, error rates, queue depths. This is distinct from device logging — it concerns the health of the platform infrastructure, not the devices it manages.

### 12. API for Third-Party Systems

Collected data is rarely consumed exclusively within the IoT platform. Export APIs (REST, GraphQL, or a Prometheus-compatible scrape endpoint) let external systems — BI tools, ERP systems, custom dashboards — pull data without direct database access.

### 13. Multi-Tenancy and Scalability

When a platform serves multiple customers, sites, or organisational units, strong isolation between tenants is required: data, credentials, and configuration must not bleed across boundaries. Horizontal scalability (multiple stateless backend instances behind a load balancer) ensures the platform grows with the device fleet.

### 14. Backup and Restore

Configuration data, device registries, and time-series data must be recoverable after hardware failure or accidental deletion. A clear backup strategy — including the time-series database, not just configuration files — and documented restore procedures are part of a production-ready platform.

### 15. Certificate Management

When TLS client certificates are used, the platform must handle the full certificate lifecycle: issuance (via an internal CA or ACME), distribution to devices, expiry monitoring, and revocation. This is often the most operationally demanding aspect of a certificate-based security model.

---

## Feature Status in nice4iot

nice4iot is a lightweight, self-hosted IoT manager designed for small-to-medium fleets. The table below maps each feature to its current implementation status.

| Feature | nice4iot implementation |
|---|---|
| **Protocol: HTTP** | ✅ REST API for telemetry, logging, file up/download, and provisioning |
| **Protocol: MQTT** | ❌ Not supported; HTTP only |
| **Device registry** | ✅ Per-device JSON files under `data/projects/{project}/{device}/` |
| **Onboarding / provisioning** | ✅ Two-tier token model: long-lived provisioning token → short-lived device bearer token |
| **Status tracking (online/offline, last-seen)** | ⚠️ `last_seen_at` stored per device; no active online/offline inference or UI indicator |
| **TLS client certificates** | ❌ Not implemented; bearer tokens only |
| **Bearer token / API key auth for devices** | ✅ `Authorization: bearer <token>` on all device endpoints |
| **User management for the UI** | ❌ No login; UI must be placed behind an authenticating reverse proxy |
| **RBAC** | ❌ Not implemented |
| **Time-series storage** | ✅ Via Prometheus Remote Write (Protobuf + Snappy); Prometheus or compatible backend required |
| **Log aggregation** | ✅ Grafana Loki (JSON push API) or rotating filesystem log files per project |
| **Data visualisation** | ⚠️ Plotly charts wired in project dashboard (WIP); no production-ready dashboard yet |
| **Data validation / JSON Schema** | ❌ Payloads accepted as-is; no schema enforcement at ingestion |
| **Unit normalisation** | ❌ Not implemented |
| **Remote config delivery** | ✅ `GET /api/file/{project}/{device}/{filename}` with ETag-based caching (304 support) |
| **OTA firmware updates** | ✅ Same file endpoint; device polls, server serves `firmware.bin` with ETag |
| **Alerting / threshold rules** | ❌ Not implemented; deferred to Grafana Alerting on the Prometheus side |
| **Rule engine** | ❌ Not implemented |
| **Store-and-forward (client-side buffering)** | ❌ Client responsibility (arduino4iot handles this); server offers no explicit support |
| **Idempotent / out-of-order ingest** | ❌ Prometheus Remote Write does not deduplicate; timestamps are device-supplied |
| **Platform self-monitoring** | ⚠️ Uvicorn logs available; no dedicated health dashboard or metrics endpoint |
| **REST API for third-party export** | ⚠️ Device API is REST; no dedicated data-export API (Prometheus scraping covers this) |
| **Multi-tenancy (project isolation)** | ✅ Project-level isolation for devices, tokens, config, and telemetry |
| **Horizontal scalability** | ❌ Single-process; filesystem state is not shared across instances |
| **Platform backup / restore** | ⚠️ Config: `rsync data/projects/` suffices; no tooling provided. TSDB backup: Prometheus responsibility |
| **Certificate management** | ❌ Not implemented |
