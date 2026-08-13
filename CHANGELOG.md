# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.27.0] - 2026-08-13

### Changed

- **niceview 0.15.0 → 0.16.0**, which brings a shared "chrome" style for everything
  the wrappers draw around a form or list. Visible on the Files card without any
  change on our side: the title row's buttons are joined in a `ui.button_group` at
  the right edge, carry tooltips, no longer wrap, and lost the redundant `round` /
  `color=primary` props.
- **The Files card's description is the wrapper's, not ours.** `DrillDownWrapper`
  gained `description=`, so `_files_card` hands its markdown to the wrapper instead
  of rendering a `ui.markdown` of its own above it. The text therefore moves from
  *above* the title row to *below* it, matching `EditGridWrapper`/`EditFormWrapper`.
  niceview renders it unstyled, so the card still applies `text-caption q-ma-none`
  to the exposed `wrapper.description` — exposed elements survive list↔detail
  navigation, unlike anything in the body.

  Nothing else in the app drives niceview chrome: `DrillDownWrapper` is used only
  here, and no `ModelList`/`EditGridWrapper` at all, so `set_chrome_style()` is
  deliberately not called — an application-wide look is a decision for when there
  is more than one wrapper to keep consistent.

## [0.26.0] - 2026-08-13

### Changed

- **The Files card gets files in through one Add dialog** instead of a permanently
  visible footer. Add is now niceview's own title-row button (`add_button='New'`,
  driving `on_add`); its dialog offers both ways in — a drop zone first, since
  uploading is the common case, and a name field below that creates an empty JSON
  file and drills straight into its editor. The dialog stays open after an upload,
  so several files can be dropped in a row, and the name field now *gates*
  Create — an invalid name or one already taken in the write directory is rejected
  at the field, where the old flow only warned after the fact.

  Consequences: uploading is one click further away and is no longer possible
  while a file's detail view is open (the wrapper hides Add there). Everything
  the footer did is otherwise unchanged, including that uploads and new files
  always land in the write directory, never in the underlay.

  Delete deliberately stays a per-row action: the wrapper's delete button is
  detail-view only, cannot be made conditional per entry — inherited files have
  no own copy to delete — and its fixed confirmation text ("cannot be undone")
  would be wrong for an override, which is exactly reversible.
- **niceview 0.14.1 → 0.15.0**, which the above depends on: `on_add`/`on_back` now
  accept `async def` and are awaited, so the handler can open a dialog and act on
  the answer. Previously the coroutine was dropped unawaited — a button that did
  nothing, with a `RuntimeWarning` as the only trace. The release also rejects an
  *async* `render_detail`/`render_list_item`/`render_list_container` at
  construction time; ours are synchronous, so nothing changed there.

### Fixed

- `_make_upload_handler` no longer refreshes the file list itself; it reports
  success and the caller refreshes once the dialog is closed. Refreshing from
  inside the handler would delete the dialog mid-upload, since the Add dialog is
  built in the click context of the wrapper's title row and therefore lives in
  the same refreshable subtree as the list.

## [0.25.1] - 2026-08-12

### Fixed

- **nicepaper 0.15.0 → 0.15.1** (the optional `epaper` extra, which the released
  container image bakes in). Fixes the display presets shipped in 0.25.0: picking
  a panel from the **Display** list in the screen settings did nothing. The
  select's handler read `e.value` off the `GenericEventArguments` an `.on()`
  handler receives, which carries the payload in `.args` and has no `.value`; the
  resulting `AttributeError` was caught and logged server-side, so the browser
  showed no error and the fields below simply stayed as they were. No API or
  `app.extensions` contract change — the five `register_*()` calls are unchanged.

## [0.25.0] - 2026-08-12

### Added

- **`deploy/Caddyfile`** — a copy-ready example config for the reverse proxy the
  compose files assume. It carries the two listeners a display deployment needs:
  the normal HTTPS site for the admin UI and the whole API, plus a **plain-HTTP
  listener that serves only the epaper image endpoint, restricted to the display
  LAN**. E-paper firmware usually has no certificate store worth the name, so an
  HTTPS-only deployment can be unreachable for the very devices the images exist
  for; this implements the approach nicepaper's `SECURITY.md` describes, in the
  proxy rather than as a second listener inside the app. The matcher ANDs
  `remote_ip` with `path_regexp ^/api/ext/epaper/[^/]+/screens/[^/]+/image\.png$`
  — everything else on that port (the UI, the rest of `/api`, off-LAN requests)
  gets a flat `404`. Documented under *Serving display images over plain HTTP* in
  [deploy/README.md](deploy/README.md), including what it does **not** buy you:
  the images travel unencrypted and unauthenticated, and `remote_ip` is not
  authentication. `image.png` stays reachable over HTTPS as well — the screen
  editor loads its preview from its own origin. The compose files are unchanged
  apart from a comment pointing at the new file; the proxy stays external.

### Changed

- **nicepaper 0.14.0 → 0.15.0** (the optional `epaper` extra, which the released
  container image bakes in). Its five `register_*()` calls are unchanged, so the
  `app.extensions` contract was not touched, but three changes are visible to
  anyone already running screens:
  - **Existing text may move.** Every widget `alignment` now defaults to `lt`
    instead of `lb`. Screen files don't store the default, so a `Text`, `Date` or
    `HomeAssistant` widget without an explicit `alignment` renders vertically
    offset after the update. Set `"alignment": "lb"` to keep the old placement.
  - **The `?color_model=` query parameter on the image endpoint is gone** and is
    now ignored. `/api/ext/epaper/<project>/screens/<screen>/image.png` serves the
    image quantized to the palette configured *on the screen*, so a display needs
    no palette knowledge of its own. Displays that passed it must have the palette
    set on their screen instead. `?raw=true` (unquantized) and `?boxes=true`
    (widget outlines, `no-store`) are new; a display never needs either.
  - **`WidgetModel.show_bounding_box` was removed** — outlines are a preview-only
    view now. Existing screen files with the key load fine and drop it on save.

  Otherwise additive: display presets picked from a searchable panel catalog,
  per-screen palette and colors, global `latitude`/`longitude` as the default
  weather location, and a pixel ruler on the editor preview.

## [0.24.0] - 2026-08-07

### Changed

- **niceview 0.11.0 → 0.14.1.** What reaches the UI:
  - A model's `description` is now carried as `FieldInfo.description` and placed
    by `description_as`, which defaults to **tooltip** — where it also was before
    0.12.0. It no longer fills the placeholder, and it now works on widget types
    that have no hint slot, so the switches finally document themselves too.
  - A field without a default (`Device.name`, `Device.project_name`,
    `ForwardingConfig.name`) is marked `*` and rejects an empty value at the
    widget, before the model sees it.
  - `ModelForm(field_props=…)` is now `base_props`, `field_classes` is
    `default_classes`, and CSS classes no longer accumulate down the cascade —
    the most specific source replaces the rest. Both renames are used throughout.

  The `include=` lists in the device and project cards define field *order* as of
  0.13.0, but both cards place every field individually, so nothing moved. No use
  of `help_text`, `FieldInfo.format`, frozen models or `SecretStr`, so those
  breaking changes do not apply.
- **The JSON Form tab renders through niceview.** `app.core.file.form_ui` now
  builds its widgets with `niceview.render_field()` and reads them back with
  `field_value()`, replacing the hand-written eight-branch widget switch with one
  table from the schema subset's field kinds to `(widget_type, field_type)`. The
  untrusted schema still never becomes a Pydantic model — see
  `docs/architecture.md`. Consequences: all eight field kinds show their
  validation inline (textarea and switch previously could not), a schema's
  `description` becomes the widget's tooltip instead of a caption line below it,
  an integer field reads back as `int` rather than `float`, and the `*` marker
  for required fields comes from niceview instead of being appended by hand.
- **Form field styling is set per form, not per field.** `base_props` and
  `default_classes` replace 33 repetitions of `.props('outlined dense …')` across
  the device, project, token, forwarding, firmware, logging, telemetry and file
  cards, including three `for widget in form.widgets.values()` loops. One visible
  consequence — switches are now `dense` like every other widget, because
  form-wide props reach every widget type.
- **One width rule across the settings cards: inputs fill the column, switches
  keep their natural width.** Previously the file, logging and firmware cards
  stretched their switches to full width while the device and project cards did
  not. `default_classes='w-full'` now says the rule once per form, and the
  switches opt out with a class of their own — `'is_active:w-auto'` in a layout,
  `render_field('is_active', classes='w-auto')` otherwise. That works because
  classes replace rather than accumulate as of 0.14.0; a full-width switch would
  otherwise take a whole line of the wrapping flex row to itself. The device card
  additionally carries a `layout=`, which replaces its `include=` list and its
  hand-built switch row. The token and forwarding cards keep per-field
  `render_field()` calls with their own `grow` / `w-1/4`: their rows mix fields
  with a delete button, which the layout notation cannot express.
- **Three design papers retired.** `docs/file-forms.md`,
  `docs/firmware-releases.md` and `docs/niceview-field-rendering.md` documented
  features while they were being built and had outlived that role. What still
  carries weight moved: the JSON-Schema subset, the schema-approval workflow and
  the firmware-pull behaviour to `docs/concepts.md`; their trust boundaries to
  `SECURITY.md`; the "interpret, never generate" rationale to
  `docs/architecture.md`; the firmware build-flag guidance to
  `docs/device-api.md`. Scope statements, goals and delivery phases were dropped.
- **nicepaper 0.13.1 → 0.14.0** (the optional `epaper` extra, which the released
  container image bakes in). Adds a Home Assistant widget with local gauges and
  moves the extension to niceview 0.14.1, the version nice4iot now pins too. Its
  five `register_*()` calls are unchanged, so the `app.extensions` contract was
  not touched.

## [0.23.0] - 2026-08-05

### Changed

- **The file browser/editor moved into `app.core.file`,** which now holds the
  whole file domain — transfer to devices *and* the admin-facing editor — instead
  of having the UI half live under `app.core.device`. It was also split up:
  `app.core.device.files_ui` had grown to 652 lines mixing the list, the detail
  views, the form widgets and the file-type rules.

  | was | is |
  |---|---|
  | `app.core.device.files_ui` | `app.core.file.browser_ui` — list half: rows, upload, new file, panel entry points |
  | — | `app.core.file.detail_ui` — detail half: `file_detail()` plus the shared `save_text`/`maybe_publish`/`download_file` actions |
  | — | `app.core.file.form_ui` — the `FormField` → widget switch, via `render_form_fields()` (renders the fields, returns a validating collector) |
  | `app.core.device.file_form` | `app.core.file.form` |
  | `app.core.device.file_overlay` | `app.core.file.overlay` |

  `app.core.file.backend`, `models` and `ui` (the FileConfig card) are unchanged.
  No module is over ~310 lines and the dependency chain runs one way.
- **`OverlayDirectoryAdapter` resolves each entry itself.** It now yields
  `OverlayFileEntry` — niceview's `FileEntry` plus `read_path`, `save_path`,
  `inherited` and `overrides` — so the UI reads the device-over-project
  precedence off the item instead of re-deriving it at three call sites.
  `FileRef` and `resolve_ref()` are gone; `read()` follows the same precedence
  and therefore resolves inherited names too. `_Ctx` became the public
  `FileCtx` and moved to `app.core.file.overlay`.
- **`plan_json_view()`** in `app.core.file.form` decides which JSON editor
  a file gets — Form tab or not, which tab leads, schema approval pending — as a
  pure function returning a `JsonView`. The decision table in
  `docs/concepts.md` is now unit-tested directly instead of only through a
  rendered panel.
- **"New JSON" asks for a filename only.** It uses `niceview.util.input_dialog`,
  writes an empty object and drills straight into the file's editor, replacing
  the hand-built dialog with its own CodeMirror. When the new device file hides a
  project file of the same name, the confirmation says so.
- **Inline field validation.** Form widgets that support it (input, number,
  select, input_chips) show their validation message under the field instead of
  only as a notification on save. The save-time check stays authoritative.
- **`app.util.human_size(n)`** replaces the private formatter in the Files card.
- **CI actions updated** to the versions running on Node.js 24, which GitHub was
  already forcing them onto: `actions/checkout` v5 → v7,
  `astral-sh/setup-uv` v6 → v9.0.0, `actions/upload-artifact` v5 → v7. The docker
  actions in the release workflow were already current. Two things to know:
  setup-uv stopped publishing moving major tags in v8, so it has to be pinned to
  a full version and bumped by hand; and its v9 defaults `prune-cache` to
  `false`, so the Actions cache may grow.

## [0.22.0] - 2026-08-05

### Added

- **Unified device Files tab.** The device Files tab now shows one list — the
  device's own files layered over the project files it inherits, matching how
  `get_file_path()` and the MQTT publisher already resolve them. Inherited
  entries carry a `project` chip. The separate "Project Files" card on the device
  page is gone; project files are edited in the project's Files tab.
  Editing an inherited file is a **copy-on-write**: it saves a copy for that
  device and leaves the project file unchanged (the save button reads *Save as
  device file*). Uploads and "New JSON" always write to the device directory.
  Inherited entries have no delete button; deleting a device override brings the
  inherited file back. Force-publish over MQTT works for inherited files too.
  New module `app.core.device.file_overlay` (`FileRef`, `resolve_ref`,
  `OverlayDirectoryAdapter`); `_files_card` takes `underlay_dir` in place of
  `schema_fallback_dir`.

### Changed

- **`app.util.atomic_write(path, data, *, suffix='.tmp')`** replaces eleven
  hand-rolled temp-file-plus-rename implementations across `app/` (firmware,
  token, device, telemetry, file and alarm backends, the device upload API, the
  MQTT upload handler and the Files card). It takes `str` or `bytes`, removes the
  temp file before re-raising `OSError`, and keeps the distinct temp suffixes the
  upload/MQTT paths rely on to avoid colliding on one target.
- **`app.util.shadow_merge(own, under, key)`** holds the device-over-project
  precedence rule that the Files listing and `check_and_publish_project()` both
  need, so the two cannot drift apart.
- **UI polish.** Secondary text and icons use `text-grey-7` throughout (several
  places still had the lighter `text-grey-6`), cards and expansions are tighter,
  and the device Dashboard's provisioning card became a timeline card. The
  relative-age formatter moved from `app.core.device.ui` to
  `app.util.render_datetime_age`.
- **Dependencies.** `fastapi`, `pydantic` and `httpx` are now declared as runtime
  dependencies. All three are imported directly by `app/`; the first two were only
  reaching the install transitively via `nicegui`, and `httpx` was declared in the
  dev group only, so a plain install of the package could fail at import.
- **Files tab refactored.** The JSON form logic (field inference, the JSON-Schema
  subset, schema approval, validation, atomic write) moved out of
  `app.core.device.files_ui` into the new NiceGUI-free module
  `app.core.device.file_form`, where it is synchronous and directly testable.
  The moved helpers lost their leading underscore now that they are a
  cross-module API (`_FormField` → `FormField`, `_validate_field` →
  `validate_field`, …). No behaviour or UI change.

## [0.21.0] - 2026-08-04

### Added

- **Firmware and Forwarding health tracking.** `pull_firmware()` and `forward()`
  now record outcomes via `app.health.set_health()`. The project System Health
  card shows an aggregated Firmware row (only once a repo is configured for the
  project or one of its devices) and one row per forwarding rule that has been
  used at least once, alongside the existing MQTT/Telemetry/Logging rows.

### Changed

- `forward()` in `app.core.forwarding.backend` now requires a keyword-only
  `project_name` argument.

## [0.20.0] - 2026-08-04

### Added

- **Reported labels on the Device Dashboard.** The Status card shows the device's
  reported labels (e.g. `site`) as a compact key/value block (firmware stays in its
  own line).
- **Label change-markers in the Data tab.** A *Label markers* multiselect lists the
  reported label keys; selecting one overlays a vertical dotted marker on the chart
  at every point where that label's value changed (annotated `key: value`) — so a
  metric jump can be lined up with a firmware/config change. The selection is
  persisted with the rest of the explorer config (`.data_view.json`). Backed by
  `label_history()`.

## [0.19.0] - 2026-08-03

### Added

- **Data-tab explorer config is persisted per device.** The selected time window
  and traces (colour/kind/metric) are saved to `.data_view.json` and restored on
  the next visit.

### Changed

- **Removed the per-label chips from the Data tab** (0.18.1) — with many labels the
  row became cluttered. The reported labels are still available in the local store
  (`l{}` / `latest_labels()`); a better visualisation is under discussion.

## [0.18.1] - 2026-08-03

### Added

- **Reported labels shown in the Data tab.** The Telemetry Explorer displays the
  labels (`firmware_version`, `site`, …) reported for the selected time window as
  chips next to the source chip, read from the local store's `l{}` objects
  (`latest_labels()`) — so they are shown regardless of whether the chart data
  comes from the local buffer or a remote backend.

## [0.18.0] - 2026-08-03

### Added

- **String telemetry fields become labels via a synthetic info series.** A device
  may send string fields (e.g. `firmware_version`, `site`) alongside numeric
  measurements. Instead of tagging every numeric series (which would churn on each
  change), every write emits **one** `<project>_target_info{…} 1` series carrying
  all of that write's labels (OpenMetrics `target_info` convention) — an
  `<project>_target_info` measurement on InfluxDB, an `l{}` object in the local
  JSONL record. Query with `metric * on(device) group_left(firmware_version)
  <project>_target_info`. Guards: valid label names, values trimmed/capped at 64,
  ≤ 8 labels/write, `device`/`kind`/`__name__` protected, and a **numeric** field
  named `target_info` is dropped (reserved). `firmware_version`
  are labels **and** still update the reported-firmware runtime state. See
  [docs/device-api.md](docs/device-api.md#string-fields-become-labels).

## [0.17.0] - 2026-08-03

### Added

- **Firmware version in the telemetry body.** `POST /api/telemetry` now recognises
  the reserved string keys `firmware_version` as device
  metadata (removed before numeric processing) and routes them to the same runtime
  state as the `X-Firmware-*` headers — so a device may report its version in the
  telemetry body instead of via a header. Body wins if both are present.

## [0.16.1] - 2026-08-03

### Changed

- **Firmware source card moved to the General tab.** It is now a foldable
  configuration card (matching Forwarding/Telemetry/Logging/Files) instead of
  living on the Files tab, shows the resolved GitHub Releases URL as a link, and
  no longer renders the internal `updated_at` timestamp.

## [0.16.0] - 2026-08-03

### Added

- **Firmware pull from GitHub Releases.** The project/device **Files** tab gains a
  **Firmware source** card: point a project (or device) at a *public* GitHub repo
  and pull a release asset (default `firmware.bin`) into that directory —
  manually (*Pull now*) or automatically (opt-in per-source background loop with a
  configurable interval, 5-minute floor, conditional ETag polling). Channels:
  `stable` / `prerelease` / `pinned` tag. The download is streamed with a 64 MiB
  cap and, when GitHub supplies the asset `digest`, SHA-256-verified before an
  atomic write; state is recorded in `.firmware.state.json`. No credentials are
  ever sent (public repos only); `repo` is `owner/name` (no URLs → no SSRF).
  Optional MQTT force-publish on pull for device-level sources. The device API is
  unchanged — devices keep fetching the file via `GET /api/file`. See
  [docs/concepts.md](docs/concepts.md#firmware-distribution).

## [0.15.1] - 2026-08-03

### Added

- **Build identity on `/health`.** `GET /health` now returns `version`, `commit`,
  and `commit_date` alongside `status` — for deployment verification and
  monitoring. The About page also shows the commit date next to the commit, and
  the GHCR image bakes it in via `NICE4IOT_GIT_COMMIT_DATE`.

### Changed

- **Deploy:** the bundled (commented) Watchtower service now uses the maintained
  `ghcr.io/nicholas-fedor/watchtower` fork; the original `containrrr/watchtower`
  is unmaintained and a modern Docker daemon rejects its old client ("client
  version 1.25 is too old").

### Fixed

- **Telemetry read/write now follow HTTP redirects.** A Prometheus/VictoriaMetrics
  endpoint behind a proxy that 308-redirects (e.g. http→https or trailing-slash
  normalisation) caused reads to fall back to the local store and writes to be
  silently dropped (308 < 400 read as success). Both paths now use
  `follow_redirects=True` (307/308 preserve method and body).

## [0.15.0] - 2026-08-02

### Added

- **Device firmware-version reporting.** A device may report its running firmware
  via the optional `X-Firmware-Version` (and optional `X-Firmware-Commit`)
  request header on any authenticated device API call, and at `POST /api/provision`.
  The value is stored server-side in a per-device `.runtime.json` sidecar (next to
  `last_seen_at`, never in `device.json`) and shown in the **Device → Dashboard**
  Status card and the **Project → Devices** table. Headers are optional and
  backward-compatible; omitting them leaves the last reported value unchanged. See
  [docs/device-api.md](docs/device-api.md#reporting-firmware-version-optional).

### Changed

- Per-device `last_seen_at` now lives in `.runtime.json` (was the bare-timestamp
  `.last_seen` file), alongside the reported firmware fields. Existing `.last_seen`
  files are still read as a migration fallback.
- The device-log append hot path (`POST /api/log`) and the UI file-upload write are
  now off-loaded to a worker thread (`anyio.to_thread`), matching the telemetry hot
  path and `PUT /api/file`.
- Dependency lock: **niceview** pin moved to the relocated `0.10.0` tag (mypy typing
  fix in `DirectoryAdapter`).

### Fixed

- **UI file upload** was broken since the NiceGUI 3.x upgrade (`UploadEventArguments`
  no longer exposes `.name`/`.content`); it now uses `e.file.name` /
  `await e.file.read()`. Regression shipped in 0.14.0.

## [0.14.0] - 2026-08-01

### Added

- **File editing in the UI.** The project/device **Files** tab is now a file
  browser with a list ↔ detail **drill-down** (built on niceview's
  `DrillDownWrapper`): JSON and recognised text files open in an inline editor,
  images (png/jpg/gif/webp ≤ 2 MB) in an inline preview; SVG and other binaries
  stay download-only.
- **JSON forms.** A flat JSON object also offers a **Form** tab with widgets
  inferred from its values (raw stays default). With a sibling
  `<name>.schema.json` (a minimal JSON-Schema subset — types, `enum`→select,
  `date`, multiline, `minimum`/`maximum`, `maxLength`, `required`,
  `title`/`description`), the schema-driven form becomes the default. Saving
  **merges** into the file, preserving keys the schema/form does not cover.
- **Device-schema approval.** A schema uploaded by a device is inert until a user
  approves it; approval is bound to the schema's content hash, so a device
  changing the schema forces re-approval. Editing a schema in the UI approves it
  automatically (admin provenance). Untrusted schemas are rendered by a small
  dedicated interpreter — never `pydantic.create_model`/niceview, never as
  HTML/Markdown — and `$ref`/`pattern` are not honoured (no SSRF / ReDoS). See
  [docs/concepts.md](docs/concepts.md#schema-driven-json-forms).

### Changed

- Updated dependencies: **niceview 0.9.1 → 0.10.0** (fixes `ui.number` conversion
  so a cleared numeric field becomes `None` again — a stale model-validator error
  such as the epaper widget's "Set width and height together …" now clears; adds
  the `DirectoryAdapter` all-files mode the file browser builds on) and
  **nicepaper 0.13.0 → 0.13.1**.

## [0.13.1] - 2026-07-24

### Changed

- Refreshed all dependencies. Notably **niceview 0.9.0 → 0.9.1**, which fixes
  `ui.number` conversion so a cleared numeric field becomes `None` again — a
  stale model-validator error (e.g. the epaper widget's "Set width and height
  together …") now clears once both fields are emptied. Also **nicepaper
  0.12.0 → 0.13.0** (weather backoff/outage visibility, English defaults),
  **NiceGUI 3.14.0 → 3.15.0**, **FastAPI 0.139.2 → 0.140.0**, **ruff → 0.16.0**,
  and assorted patch bumps. The `/ui` routing was re-verified end to end against
  NiceGUI 3.15.0.
- `deploy/compose-ghcr.yml` now simply tracks `:latest` (the version-pinned
  example line was dropped to avoid per-release churn; pinning is still
  documented as an option).

## [0.13.0] - 2026-07-24

### Added

- **Preferences page** (user menu → Preferences, `/ui/preferences`): the global
  MQTT broker status and any extension-registered global cards now live here, so
  `/ui` is a clean list of projects only.
- The About page (`/ui/about`) lists nice4iot's own version and build commit
  first, before niceview and the epaper extension. The GHCR image bakes the
  release commit in via `NICE4IOT_GIT_COMMIT`; source/dev runs read it from git
  (with a `-dirty` marker for uncommitted changes).

### Changed

- **The UI now lives under `/ui`** (`/` redirects there); `/api/*` is unchanged.
  Projects are at `/ui/project/{project}`, devices at
  `/ui/project/{project}/device/{device}`, and About/login moved under `/ui`
  too. The literal `/ui/project/` prefix removes the top-level namespace
  collisions of the old flat scheme — a project can no longer be confused with a
  reserved page, so e.g. a project literally named `about` now works, and the
  0.12.0 `/sbom` → *Project "sbom" does not exist* bug is structurally gone.
  **Breaking** for UI bookmarks; **devices are unaffected** (`/api/*` unchanged).
  Reverse proxies now gate the human UI with a single prefix rule (`/ui/*`); see
  deploy/README.md.
- Renamed the user-menu entry "Software Bill of Materials" to **About**.

## [0.12.0] - 2026-07-24

### Added

- **Software Bill of Materials** page in the user menu (`/sbom`): lists every
  installed Python package and its version, with the niceview and epaper
  (nicepaper) versions highlighted at the top.
- **GHCR release pipeline** — `.github/workflows/release.yml` builds the image
  and pushes it to `ghcr.io/clausgf/nice4iot` (tags `<version>`, `<major.minor>`,
  `latest`, epaper included) on every `v*` git tag.
- **`deploy/compose-ghcr.yml`** — run the pre-built GHCR image (no source/build
  on the host); pull-based updates by default, with a commented-out Watchtower
  service for hands-off auto-updates.
- **`deploy/compose-develop.yml`** — local development: builds the image, mounts
  the host `app/` over it, and runs `uvicorn --reload` on `localhost:8080`.

### Changed

- Renamed `deploy/docker-compose.yml` to **`deploy/compose-build.yml`** (the
  build-from-source production variant) now that there are three compose files.

## [0.11.3] - 2026-07-23

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.11.0 to
  0.12.0: adds an Image widget. Pinned by commit in `uv.lock`; only affects
  images built with `--extra epaper`.
- On the device **General** tab, the Danger Zone card is now rendered last,
  after any extension-registered cards, matching the project page.

### Fixed

- The device Status card no longer shows two stacked separators when a device
  has neither a location nor a description: the separator above that block is
  now only drawn when the block has content.

## [0.11.2] - 2026-07-23

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.10.0 to
  0.11.0: WeatherChart axis titles and per-aspect font override. Pinned by commit
  in `uv.lock`; only affects images built with `--extra epaper`.

### Fixed

- On the device **General** tab, extension-registered cards (e.g. E-Paper) now
  use the same `subtitle1` header size as the built-in expansions on that tab.
  They were falling through to `config_expansion`'s `h6` default (correct on the
  project page, too large next to the device page's `subtitle1` headers).

## [0.11.1] - 2026-07-22

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.9.0 to
  0.10.0: WeatherNow wind-chart metric, localized text and configurable
  wind-speed unit, and schedule size validation/warnings. Pinned by commit in
  `uv.lock`; only affects images built with `--extra epaper`.

### Fixed

- The `/api/*` namespace now always answers with JSON. NiceGUI's `ui.run_with`
  mounts the UI as a catch-all at `/`, so any unmatched request under `/api/*` —
  an unknown path, or a wrong HTTP method on a known endpoint (e.g. `GET`ting the
  `POST`-only `/api/provision`) — fell through to the UI and returned an HTML
  page instead of a JSON error. A guard route registered after the API routers
  (which still win on an exact method+path match) now returns a JSON `404`.
  Correct device calls were unaffected; this only corrects the error responses.
  Regression-tested in `tests/test_api_namespace.py` — the existing suite missed
  it because its fixtures build a router-only app without NiceGUI mounted.

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
