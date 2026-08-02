# Firmware from GitHub Releases

Status: the **firmware pull** from GitHub (most of this document) is **design,
not yet implemented**; the **[running-version reporting](#reporting-the-running-version)**
at the end is **implemented**. This documents a planned extension of the
**Files** panel — per project (and per device) a public GitHub repository can be
configured as a firmware source, and a release asset (default `firmware.bin`)
pulled into the file store, manually or on a schedule — plus the shipped
mechanism by which devices report the version they run.

[← Documentation index](README.md) · [Core Concepts](concepts.md) · [Architecture](architecture.md)

---

## Scope

The **Files** tabs (`app/core/device/files_ui.py`) gain a small **Firmware
source** card that lets an operator point a project or device at a public GitHub
repo and pull a release asset into the corresponding directory. The pulled file
is an ordinary file in the store from that point on.

**The device API does not change.** Devices keep fetching `firmware.bin` via
`GET /api/file/{project}/{device}/{filename}` with the existing device→project
fallback, ETag/`Last-Modified` caching, and (optionally) the MQTT file-delivery
push. This feature is purely the admin-side act of *getting* firmware from
GitHub *into* the store; it is deliberately decoupled from how a device consumes
it.

## Goals

- Configure a **public** GitHub repo per project, with an optional per-device
  override — same device-first-then-project fallback as the files themselves.
- Resolve a release (latest stable by default; a specific tag; optionally
  including prereleases) and download a named asset (`firmware.bin` by default).
- Write the asset **atomically** into the device or project directory, so the
  regular file-serving path picks it up unchanged.
- Trigger a pull **manually** from the UI **and** **automatically** on a
  configurable interval, with an optional MQTT publish on a new pull.
- Show current state: configured repo, latest available tag, currently-pulled
  tag/time.

## Configuration

A small `FirmwareSource` model, stored as a sidecar like the other backends
(`.telemetry.json`, `.logging.json`, `.forwards.json`):

```
project-dir/
  .firmware.json          ← project-wide firmware source
  firmware.bin            ← pulled asset (served to all devices by fallback)
device-dir/
  .firmware.json          ← optional per-device override
  firmware.bin            ← pulled asset (overrides the project default)
```

Resolution is **device dir first, then project dir** — identical to file
serving. A device override replaces the project config wholesale (it is not
merged).

`FirmwareSource` fields (all admin-set in the UI):

| Field | Default | Meaning |
|---|---|---|
| `repo` | `""` | `owner/name` only — **not** a URL (SSRF guard). Empty = disabled. |
| `asset_name` | `firmware.bin` | Release asset filename to download. |
| `dest_filename` | `firmware.bin` | Filename written into the store. |
| `channel` | `stable` | `stable` (latest non-prerelease) · `prerelease` (newest incl. prereleases) · `pinned`. |
| `pinned_tag` | `""` | Used when `channel == pinned`. |
| `auto_pull_enabled` | `false` | Enable the background auto-pull loop. |
| `auto_pull_interval_min` | `60` | Poll interval for auto-pull, in minutes. |
| `publish_on_pull` | `false` | MQTT force-publish `dest_filename` after a successful pull (project MQTT must be enabled). |

`repo` is validated against `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`; `asset_name`
and `dest_filename` go through the existing `is_valid_upload_filename` (no
traversal). `channel`/`pinned_tag` are the only knobs that decide *which*
release; everything else is fixed vocabulary.

## Release resolution

Against the public GitHub REST API (`https://api.github.com`), no credentials:

| `channel` | Request | Chosen release |
|---|---|---|
| `stable` | `GET /repos/{repo}/releases/latest` | The one GitHub marks *latest* (excludes prereleases and drafts). |
| `prerelease` | `GET /repos/{repo}/releases?per_page=…` | Newest by `published_at`, prereleases included, drafts excluded. |
| `pinned` | `GET /repos/{repo}/releases/tags/{pinned_tag}` | Exactly that tag. |

From the chosen release's `assets`, the one whose `name == asset_name` is
selected; if none matches, the pull fails with a clear message and **nothing is
written**.

**"Newer" is decided by tag string, not semver.** The store records the
pulled `tag_name`; a pull happens when the resolved release's `tag_name` differs
from the recorded one (for `pinned`, when the asset **digest** changes). No
version-range parsing — it keeps the logic auditable and avoids a semver
dependency. Semver-aware constraints are explicitly out of scope (see below).

## Pull mechanism

1. Resolve the release and asset (above).
2. Download the asset with `httpx` (async), following the redirect to GitHub's
   asset host, **streaming** into a temp file with a hard size cap.
3. If the asset JSON carries a `digest` (`sha256:…`), verify the streamed bytes
   against it; mismatch → discard, fail.
4. `temp → rename` atomically into the target directory (`dest_filename`), via
   the existing atomic-write path, off-loaded to a worker thread.
5. Record state in a `.firmware.state.json` sidecar next to the file:
   `{ "tag": …, "asset": …, "digest": …, "pulled_at": …, "etag": … }`.
6. If `publish_on_pull` and MQTT is enabled for the project, force-publish
   `dest_filename` (reuses the Files panel's existing MQTT publish).

The **manual** path is a *Pull now* button on the Firmware-source card that runs
steps 1–6 and refreshes the file list. The card also shows *latest available*
(a cheap `releases/latest` peek) next to *currently pulled*, so a newer release
is visible before pulling.

## Auto-pull

An opt-in background loop (in the spirit of the alarm-evaluation loop) iterates
projects and devices with `auto_pull_enabled`, respecting each
`auto_pull_interval_min`. Each check issues a **conditional** request (`ETag` /
`If-None-Match` from the stored state): a `304 Not Modified` costs nothing
against the rate limit and means "no change, do nothing". On a changed release
it runs the same pull steps 1–6, so a fleet can track a channel hands-off, with
`publish_on_pull` notifying devices over MQTT.

Rate limits: unauthenticated GitHub allows **60 requests/hour per IP**.
Conditional requests keep steady-state polling essentially free; a sane floor is
enforced on `auto_pull_interval_min`, and rate-limit headers are logged so a busy
instance is diagnosable.

## Security model

- **Public repos only, no credentials — by design.** nice4iot never sends an
  auth token to GitHub, so there is nothing to leak across the redirect to the
  asset host, and no secret is ever written to disk. Private repositories and
  token storage are **out of scope** (not a deferred "v2").
- **Admin provenance.** The source is configured by an authenticated operator in
  the UI — trusted, like a UI-created schema. A device can never set a firmware
  source; the sidecars are dotfiles and are never served to devices.
- **No SSRF.** Only `owner/repo` is accepted (regex-validated), never a URL.
  Requests are pinned to `api.github.com`; the asset download follows the
  redirect only to GitHub's own asset host, with a bounded redirect count.
- **Bounded download.** The asset is streamed with a hard size cap (separate
  from, and larger than, the 10 MiB UI-upload cap, since firmware images can be
  bigger); the cap aborts the stream mid-flight.
- **Integrity.** When GitHub provides the asset `digest`, the download is
  verified against its SHA-256 before the atomic rename; a mismatch writes
  nothing.
- **Opaque blob.** The asset is stored verbatim and never parsed or executed;
  filenames are validated (`is_valid_upload_filename`), no traversal.

## Async I/O

Network I/O uses `httpx.AsyncClient` (async), like the Loki/Influx/Prometheus/
forwarding backends. The disk write (temp write + rename) goes through the
existing atomic-write path off-loaded via `anyio.to_thread.run_sync`, per the
project's async-I/O rule. The auto-pull loop already runs in async context.

## Reporting the running version

**Status: implemented** (the *pull* side above is still design; this reporting
side ships now). Only the device knows which firmware it is actually running, so
it self-reports; the server never guesses.

- **Transport.** On any authenticated device API request — and at
  `POST /api/provision` — the device sends the running version in an
  `X-Firmware-Version` header (plus an optional `X-Firmware-Commit`). Reporting
  on every request keeps the value fresh; reporting at provisioning guarantees a
  known value at least at each token refresh even if the header is otherwise
  omitted. See [Device API → Reporting firmware version](device-api.md#reporting-firmware-version-optional).
- **Storage.** The value is captured server-side at the same point that updates
  `last_seen_at`, and written to a per-device `.runtime.json` sidecar — **not**
  `device.json`, which is managed by the UI's optimistic-locked autosave adapter
  and must not be rewritten on every request. `.runtime.json` holds
  `last_seen_at`, `firmware_version`, `firmware_commit`, `firmware_reported_at`;
  `get_device()` copies them onto the in-memory `Device`. (It supersedes the old
  bare-timestamp `.last_seen` file, still read as a migration fallback.)
- **UI.** Shown in the **Device → Dashboard** Status card and the
  **Project → Devices** table. Together with the *available* tag from a pull
  (`.firmware.state.json`), the UI can contrast **running vs. available** per
  device.
- **Trust.** The header is untrusted device input: it is *reported*, not
  verified; the string is whitespace-trimmed and length-capped (64 chars) and
  only ever displayed to the operator, never interpreted.
- **Deferred.** Inferring "downloaded but not yet booted" from the conditional
  `GET /api/file/.../firmware.bin` ETag (what the device last *fetched*, vs. what
  it *runs*) is a later addition; the self-report above is the ground truth for
  "running".

## Firmware-side (Arduino4iot) changes

What the device library needs so a device reports its version (implemented
server side) and consumes pulled firmware (the design above):

**Report the version (small, needed now):**

- In the HTTP client's shared request helper — the one place that sets the
  `Authorization: Bearer …` header for provisioning, telemetry, log, and file
  calls — also set `X-Firmware-Version` (and optionally `X-Firmware-Commit`) on
  every request. One line at the choke point; no per-call change.
- The value comes from a **compile-time macro** so it cannot drift from the
  actual build.

**Build requirement — bake the version in:**

- Inject the release tag at build time as a define, mirroring how nice4iot bakes
  `NICE4IOT_GIT_COMMIT` into its own image. GitHub Actions provides the tag as
  `${{ github.ref_name }}` on a `v*` tag build.
  - **PlatformIO:** an `extra_scripts` / `build_flags` entry, e.g.
    `-D FIRMWARE_VERSION='"${sysenv.FIRMWARE_VERSION}"'` (CI sets the env var
    from `github.ref_name`), and optionally
    `-D FIRMWARE_COMMIT='"'$(git rev-parse --short HEAD)'"'`.
  - **Arduino CLI:** `--build-property "build.extra_flags=-DFIRMWARE_VERSION=\"$TAG\""`.
- Provide a small fallback (`#ifndef FIRMWARE_VERSION #define FIRMWARE_VERSION "dev"`)
  so local (non-CI) builds still compile and report a sensible value.

**Consume pulled firmware (no new work):**

- The GitHub-pull feature only *populates* `firmware.bin` in the store; the
  device fetches it via the existing OTA path — `GET /api/file/{project}/{device}/firmware.bin`
  with `If-None-Match: <etag>`, flashing on `200` and skipping on `304`. No
  library change is required for the pull feature beyond the OTA logic Arduino4iot
  already has.

## Deferred / out of scope

Private repositories and token storage · non-GitHub sources (GitLab, Gitea,
self-hosted, plain URLs) · signature verification beyond the release asset's
SHA-256 digest (e.g. cosign / GPG / SBOM attestation) · semver-aware version
constraints (`>=1.2,<2`) and downgrade protection · delta/partial updates ·
rollback orchestration and staged rollouts · verifying that a device actually
applied the firmware (that stays the device's and the operator's concern).
