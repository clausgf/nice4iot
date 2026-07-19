# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **File API** — conditional caching via `If-Modified-Since` / `Last-Modified`
  on `GET` and `HEAD /api/file/{project}/{device}/{filename}`, alongside the
  existing `ETag` / `If-None-Match`. If a request sends both validators,
  `If-None-Match` wins (RFC 7232 §3.3).
- **Telemetry read** — the Data tab reads history from the configured
  Prometheus-compatible backend (Prometheus / VictoriaMetrics / Mimir) with a
  fallback to the local ring buffer; a source chip shows which is in use.

### Changed
- **Telemetry ingest** (`POST /api/telemetry/{project}/{device}/{kind}`) —
  nested JSON objects are flattened to underscore-joined metric names
  (`a.b` → `a_b`), and every metric name is sanitized to `[a-zA-Z0-9_]` for
  backend compatibility (`cpu.load-1m` → `cpu_load_1m`).
- **Project and device names** — must now be valid identifiers
  `[a-zA-Z_][a-zA-Z0-9_]*` (no `-`, `+`, or leading digit). Provisioning
  (`POST /api/provision`) and the file API reject non-conforming names. This
  guarantees valid Prometheus metric names `<project>_<field>`. **Upgrade:**
  rename any existing hyphenated project/device directories on disk.

### Internal
- Upgraded the `niceview` UI dependency (unified widget `options`, renamed
  modules); no change to nice4iot's own API.
- Alarm metric-rule editor: *Kind* / *Metric* comboboxes seeded from observed
  telemetry, with the *Metric* list filtered by the selected *Kind*; a
  not-yet-observed name can still be typed in.
