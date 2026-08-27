# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [0.37.0] - 2026-08-27

### Added

- **Firmware Download now supports GitLab, alongside GitHub** (`app/core/firmware/models.py`, new `app/core/firmware/github.py` + `gitlab.py`, `app/core/firmware/backend.py`, `app/core/firmware/ui.py`): `FirmwareSource` gained `host` (`github`/`gitlab`) and `host_url` (base URL of a self-hosted GitLab instance; empty = gitlab.com, ignored for GitHub). `repo` now also accepts GitLab's nested `group/subgroup/.../name` form, not just GitHub's flat `owner/name`. The GitHub-specific request/response handling (previously hardcoded throughout `backend.py`) is split into `github.py`, with a new `gitlab.py` implementing the equivalent against GitLab's REST API v4 — materially different in shape: no "latest release" endpoint (list + take newest), no draft/prerelease flag on a release (`stable`/`prerelease` channels both resolve to "newest" there), assets are `assets.links[]` (arbitrary URLs, not necessarily hosted on the GitLab instance — the download-host allowlist is the *configured* GitLab host, not GitHub's fixed asset-CDN list), and no asset digest in the API response (integrity verification is local-hash-only for a GitLab source). Public repositories only, matching GitHub's existing scope — no `PRIVATE-TOKEN`/auth support yet. `backend.py` itself is now a thin per-directory orchestrator that dispatches to whichever module `host` names.

### Fixed

- **The device-level Firmware Download card was missing from the device Settings → General tab** (`app/core/device/ui.py`): the backend has always supported a firmware source per device (independent of the project's, via the ordinary device→project file-serving fallback) — a 2026-08-05 refactor (commit `d472c1a`) silently dropped the card's import and call from `device_general_panel()`, unnoticed for 15+ releases since nothing rendered that panel in a test. Restored, with a regression test that fails without the fix. `docs/concepts.md`'s Firmware Distribution section also had two stale field names (`publish_on_pull` → `mqtt_publish_on_pull`, `auto_pull_interval_min` → `auto_pull_interval`) and a description of wildcard `asset_name` matching that was removed from the code on 2026-08-25 (commit `7500ed7`) but never removed from the docs — corrected alongside.

## [0.36.3] - 2026-08-27

### Changed

- `nicepaper` (optional `epaper` extra) bumped 0.26.7 → 0.26.8: `PanelTypeModel.gxepd2_class` renamed to `panel_id` (the panel's official manufacturer designation, e.g. `GDEH075Z9`, instead of a GxEPD2 Arduino-library class name) — no nice4iot changes needed.

## [0.36.2] - 2026-08-27

### Changed

- **`render_datetime_age()` handles future timestamps** (`app/util.py`): a datetime after "now" (e.g. a not-yet-expired provisioning token) used to render a broken negative age (`(-3d ago)`); it now renders `(in 3d)`. The inner helper is renamed `_ago` → `humanize_timedelta` to match (it no longer always means "ago").

## [0.36.1] - 2026-08-27

### Changed

- Dependencies bumped to their latest available versions (`uv lock --upgrade`), notably `nicepaper` 0.26.6 → 0.26.7 (Rooms search, Displays status/icon overhaul), `niceview` already at 0.26.5, and `plotly` 6.9.0 → 7.0.0 (a major version bump — verified live that device Data-tab charts still render correctly, since the test suite doesn't exercise plotly's JS rendering). No source changes.

## [0.36.0] - 2026-08-27

### Fixed

- **A device's provisioning approval depended on how it was created** (`app/core/device/backend.py`, `app/mqtt/backend.py`): `device_provision()` (HTTP autocreate) and MQTT autocreate both correctly set a new device's `is_provisioning_approved` from `project.is_provisioning_autoapproval` — but manual "New Device" (and any other direct `create_device()` caller) left it at the model default (`False`), regardless of the project's setting. `create_device()` now applies `project.is_provisioning_autoapproval` itself, unconditionally, so the rule lives in one place instead of every caller having to remember it; the two call sites that used to set it explicitly no longer need to.
- **A standalone extension page silently rendered the normal project UI instead, when nice4iot is served under a reverse-proxy sub-path** (`app/frontend.py`): `home_page()`'s own routing for `/ui/project/<id>/ext/<extension>` matched against `request.url.path` directly — but that's not root-path-aware (Starlette's `Request.url` just echoes `scope['path']` verbatim), so behind a proxy that forwards the mount prefix unstripped (e.g. `--root-path /iot`, Caddy's plain `reverse_proxy`) it came back as `/iot/ui/project/<id>/ext/<extension>`, which the pattern's `^/ui/...` anchor never matched — falling through to the normal project page with no error, no redirect. New `_request_path()` strips the ops-level prefix the same way NiceGUI's own `SubPagesRouter` already does (used by the rest of `ui.sub_pages` routing, which is why normal navigation was unaffected) — a no-op when unset or already stripped, so nothing changes for a root-mounted deployment. Verified with a live A/B test (same click, same setup, bug reproduces without the fix and is gone with it), not just read from source.

### Changed

- **Project sidebar groups Dashboard/Files/Devices under a "Project" heading, and each extension's project tabs under its own name** (`app/core/project/ui.py`, `app/extensions.py`): previously all of these sat flat at the top level, so a project with several extension tabs (or several enabled extensions) turned into a long undifferentiated list. `get_project_tabs()` now returns the owning extension's name alongside each tab (needed to group them; nothing else reads it), and `project_nav_items()` builds one `NavItem` group per extension, tabs in registration order — same one-level-of-nesting sidebar shape `Settings` already used. `device_subpage()`'s "Devices is the active row" lookup used to search only the top level; a new `find_nav_item()` helper searches one level into groups too, since "Devices" is now nested under "Project".
- **Project Devices table is now a searchable, auto-sized grid with a combined status/WiFi/battery icon column** (`app/core/device/ui.py`, `app/core/device/backend.py`, `app/core/device/models.py`): rebuilt on `niceview`'s `EditGridWrapper`/`ModelGrid` (ag-grid) instead of a plain `ui.table`, with `auto_size_columns=True` and a search box (`niceview` 0.26.4). The old "Active"/"Provisioning OK" columns are replaced by one "Status" column showing three icons — a status dot (green/orange/purple/grey for active+provisioned+online / active+provisioned+offline / active-pending-provisioning / inactive), WiFi, and battery — each with a tooltip, rendered as one raw-HTML cell (`niceview` 0.26.5's `ModelGrid(html_fields=...)`) so device health reads at a glance instead of spreading across three narrow columns. New "Board" column (from `DeviceRuntime.board`) sits after Firmware. Icon *names* were picked by rendering every candidate against the actual bundled font rather than guessed — several previously-used names (`signal_wifi_zero_bar`/`four_bar`, every word-form `battery_*_bar`) turned out not to exist as ligatures in the bundled font at all (invisible), and the ones that did render came from inconsistent glyph designs that visibly shifted position between rows; WiFi is now a 3-state (off/weak/good) icon and battery uses the numeric `battery_N_bar` names, both confirmed to render with consistent alignment. Clicking a row navigates to that device's page (previously double-click; switched because ag-grid's native `rowDoubleClicked` event carries a circular object graph that fails NiceGUI's generic event-arg serialization — row selection, resolved via `ModelGrid.on_select()`, doesn't have that problem). New `app.core.device.backend.project_device_rows()`/`device_status_key()` assemble the grid's rows; the per-device file reads this adds are wrapped in `anyio.to_thread.run_sync` at the call site (`project_devices_panel`), per the Async IO rule.
- **Settings sidebar dropped its separate "Files" row** (`app/core/project/ui.py`): the standalone `Settings → Files` page (`file_config_card`) is now a `config_expansion` section on the `Settings → General` page instead, placed right after the General card and before Extensions — one less sidebar entry, and file settings sit next to the other small per-project toggles.

## [0.35.2] - 2026-08-26

### Fixed

- **The active sidebar row was never highlighted** (`app/ui.py`): `_current_path()` prepended `UI_PREFIX` ('/ui') to `sub_pages_router.current_path`, but that value is already `/ui`-prefixed in production — nice4iot mounts NiceGUI at the ASGI root (`ui.run_with()`'s default `mount_path='/'`), so `/ui` is just a matched `@ui.page` route, not a submount, and nothing strips it. The doubled prefix (`/ui/ui/...`) never matched any `NavItem.url`, so `render_sidebar()`'s active-row lookup silently always came up empty. Confirmed against a live request (`sub_pages_router.current_path` really does carry the full `/ui/...` path) before fixing; two `tests/test_navigation_ui.py` tests had encoded the old (wrong) assumption and are corrected alongside.

### Changed

- `nicepaper` (optional `epaper` extra) bumped v0.26.5 → v0.26.6: fixes NaN/inf telemetry values crashing the Displays list, adds WiFi/battery tooltips, and enlarges the room-notes font — no nice4iot changes needed.

## [0.35.1] - 2026-08-26

### Added

- **`DeviceRuntime` gained `battery_voltage`/`rssi`/`firmware_id`/`board` properties** (`app/core/device/models.py`): plain read-only accessors over the existing `system_metrics`/`system_labels` snapshot (`battery_V`, `wifi_rssi`, `firmware_id`, `board`) — `None`/`''` when the last system push didn't report that key. Derived, not pydantic fields — never persisted into `.runtime.json`. `firmware_version` already exists as its own dedicated, more authoritative field on both `Device` and `DeviceRuntime` (also fed by the `X-Firmware-Version` header, not just telemetry), so it wasn't duplicated here.
- **`Device` gained an `active_alarms` property**: a live count of that device's active, unacknowledged alarms (`app.core.alarm.backend.get_alarm_count()` under the hood). Lives on `Device`, not `DeviceRuntime` — it needs `project_name`/`name` to query the alarm backend, which only `Device` carries; also a plain property, not persisted.

### Changed

- `nicepaper` (optional `epaper` extra) bumped v0.26.3 → v0.26.5: Displays now show real firmware version/RSSI/battery/alarm-count data via the `DeviceRuntime`/`Device` properties added above (`display/backend.py`), Rooms' Displays tab shows firmware version per row, organizer names are edited directly instead of via a dialog, a mislabeled ACeP panel-type preset is fixed, plus organizer-extraction logging — no further nice4iot changes needed.

## [0.35.0] - 2026-08-26

### Fixed

- **Alarms kept appearing for already-deleted devices** (`app/core/alarm/backend.py`, `app/core/device/backend.py`): alarm events are keyed by device name in a project-wide file, not stored inside the device's own directory, so `delete_device()` removing that directory never touched them — an active/unacknowledged event just stayed forever. `delete_device()` now clears a device's alarm events and `rename_device()` re-keys them to the new name; a new `prune_alarms_for_deleted_devices()`, run once per project alongside the existing background alarm checks (`app/main.py`), also sweeps up anything already orphaned (or orphaned by a device directory removed outside the UI).
- **A device's batched multi-line log write landed as one log entry** (`app/core/logging/backend.py`): `write_log()` passed the whole request body straight to each backend, so several `\n`-separated ESP-IDF log lines sent in one call (both the HTTP `/api/log/...` and MQTT `log` topic go through this same function) became a single Loki entry under one timestamp, or one embedded-newline line in the file log. `write_log()` now splits on `\n` and writes each backend one call per line; blank lines (after stripping) are dropped instead of written.

### Changed

- **Project and device dashboard card grids** (`app/core/project/ui.py`, `app/core/device/ui.py`) now pick up their second/third column at the `md`/`xl` Tailwind breakpoints instead of `sm`/`lg`, so cards stay readable longer on medium-width windows before splitting into columns.
- `nicepaper` (optional `epaper` extra) bumped v0.26.1 → v0.26.3: fixes the Simplified UI's page content shrink-wrapping instead of filling the page width, and gives the Rooms project-tab grid a focused, auto-sized column set — no nice4iot API changes needed.

## [0.34.0] - 2026-08-25

### Fixed

- **Project sidebar content was shrink-wrapped instead of full-width** (`app/core/project/ui.py`): `ui.sub_pages` is itself a flex column with `align-items: flex-start` (same as `ui.row`/`ui.column`), so it shrink-wraps to its content's width unless given `w-full` explicitly — the nested `ui.sub_pages` project_subpage constructs was missing it, so every route rendered through it (Dashboard, Settings, Files, Devices, every extension tab) was affected, including extension UI (e.g. nicepaper's tabs).
- **Extension 'general' cards lost their `config_expansion` chrome** under the new Settings routing (see below) — they'd briefly reused the plain, chrome-less extension-*tab* route instead of the one that wraps them in the same foldable card the old General tab gave them.
- **AP+QR "Print" produced a blank page** (`app/core/seed/action_dialogs.py`): the previous `@media print { body * { visibility: hidden } ... }` approach printed the dialog in place, but Quasar's `QDialog` renders its content `position: fixed`, and `position: fixed` content is well known to not print reliably (often clipped to nothing) — no CSS trick from inside the dialog's own DOM subtree fixes that. Print now opens a small, plain popup window with just the title/QR/URL and prints that instead, sidestepping the dialog entirely.
- **Device Data tab: explorer fields (Time, Show-on-dashboard, each trace's Color/Kind/Metric) had gone full-width** (`app/core/device/data_ui.py`): `app/main.py` sets niceview's app-wide `default_classes='w-full'`, which `render_field()` falls back to for any `Field` with no `classes=` of its own — the affected fields built one without, then chained `.classes('shrink'/'grow')` afterward, which only *adds* to the leftover `w-full` instead of replacing it. `classes=` now goes into the `Field(...)` call itself for every one of them.

### Changed

- **Project-level Firmware Seed card no longer offers "AP based Setup"**: that shortcut (create a device, then show the AP+QR dialog) belongs on the Devices tab, not buried in Settings → Firmware → Firmware Seed. `seed_settings_card()` lost its `project_name` keyword accordingly. The device-level Firmware Seed card is unaffected — it still offers "AP based Setup" for the device it's already on.

- **General tab reorganized into a "Settings" sidebar group** (`app/core/project/ui.py`, `app/core/device/ui.py`, `app/ui.py`): the project sidebar's flat "General" row is now a trailing two-level "Settings" group (`NavItem` gained `children`; a group renders as a non-clickable header with its children indented below, same as nicepaper's own sidebar groups) — General/Extensions/Danger Zone combined under "General", Telemetry/Logging under "Telemetry", Firmware Seed/Firmware Download under "Firmware" (each combo is multiple `config_expansion(..., value=True)` blocks stacked on one page, now expanded by default since there are only one or a few per page); Provisioning, Forwarding, Files and Alarms stay standalone. Every child is its own bookmarkable route (`.../project/<id>/settings/<slug>`); extension-registered 'general' cards (`register_project_card`) get their own route each at `.../settings/tab/<slug>`. `project_general_panel()` is gone, replaced by `SETTINGS_SECTIONS` + `_settings_section_renderers()`; `project_nav_items()` gained an optional `general_card_defs` parameter.
- `nicepaper` (optional `epaper` extra) bumped v0.23.0 → v0.26.1: Displays list drill-down chevron, palette-restricted booking-system category colors (with a plain-black fallback instead of a nearest-color guess on panels that can't show one exactly), Display Detail live/last-delivered preview, and optional `WeatherChart` metrics — all internal to nicepaper, no further nice4iot changes needed.

## [0.33.0] - 2026-08-25

### Added

- **Routing control for extension UI** (`app/extensions.py`, `app/frontend.py`, docs/extensions.md): extension tabs and cards (`register_project_tab`/`register_device_tab`/`register_project_card`/`register_device_card`) may now declare a trailing parameter annotated `PageArguments`; nice4iot passes it in (see `call_with_page_args()`), letting the extension open its own nested `ui.sub_pages(...)` for deep-linkable sub-views without any root_path bookkeeping — it's rendered inside nice4iot's own `ui.sub_pages` already. Existing `render_fn`s without that parameter are unaffected. Standalone extension pages (`register_project_page`) now also route every sub-path under `/ext/<extension_name>/...` to `render_fn`, not just the bare URL, so a kiosk-style extension page can build its own `ui.sub_pages(routes, root_path=project_extension_url(...))` for deep links outside the app chrome.

- **Firmware Seed cards get an "AP based Setup" shortcut** (`app/core/seed/ui.py`): the project-level Firmware Seed card now has an "AP based Setup" button (QR icon) that creates a device and opens the same AP+Form-Setup QR dialog the project's Devices tab opens after creating one that way. `seed_settings_card()` gained a required `project_name` keyword argument for this.

### Changed

- **Project page navigation moved to a sidebar** (`app/frontend.py`, `app/core/project/ui.py`, `app/core/device/ui.py`, `app/ui.py`, `app/routes.py`): the project page's Dashboard/General/Files/Devices tab strip is now a left `ui.left_drawer` sidebar (collapses to a hamburger menu below the 1024px breakpoint — the header's old SVG logo is gone, the hamburger sits in its place), each row a real, bookmarkable URL (`.../project/<id>/general` etc.) instead of `?tab=<label>`. Extension project tabs (`register_project_tab`) appear as additional sidebar rows at `.../tab/<slug>`, now with an optional `icon=` (Material icon name, default `'extension'`) — see docs/extensions.md. The device page is unchanged: it still shows the same sidebar (with "Devices" highlighted, since drilling into one device doesn't grow a third sidebar level) but keeps its own horizontal tab strip and `?tab=<label>` addressing in the content area. The Projects list, Preferences and About pages hide the sidebar/hamburger entirely (there's no project context for them to navigate). `project_url(project_id, tab=...)` now takes a raw path segment (e.g. `'general'`, `'devices'`, `'tab/<slug>'`) instead of a display label; `device_url(..., tab=...)` is unchanged. The app-level `ui.sub_pages` in `home_page()` now sets `show_404=False` — required for a project sub-route to resolve on a direct/cold load rather than 404ing (project_subpage's async body can't outrun nicegui's single-tick check for whether a nested `ui.sub_pages` exists yet); the trade-off is that a genuinely unmatched top-level URL now renders blank instead of a "404" label, both at HTTP 200.
- The breadcrumb row in the header stays as-is (kept on request — not replaced by the sidebar for now).
- `project_dashboard_panel`, `project_general_panel`, `device_dashboard_panel`, `device_general_panel` (`app/core/project/ui.py`, `app/core/device/ui.py`) now take an additional `args: PageArguments` parameter, threaded from `project_subpage`/`device_subpage` — internal signature change to support the extension-routing capability above, not called directly by extensions.
- `register_project_tab`/`register_device_tab` (`app/extensions.py`) gained an optional `icon=` keyword (default `'extension'`); `get_project_tabs`/`get_device_tabs` now return `(label, icon, render_fn)` triples instead of `(label, render_fn)` pairs.
- Device Firmware Seed card's AP+Form-Setup button relabeled "AP based Setup" (was "AP + Form Setup") to match the new project-level button; the Devices tab's own "AP + Form Setup" button (which creates a new device before showing the dialog) keeps its existing label.
- `nicepaper` (optional `epaper` extra) bumped v0.19.0 → v0.23.0: adopts the sidebar `icon=` on its four project tabs (Rooms/Screens/Schedules/Booking systems), makes its simplified UI fully deep-linkable via the new standalone-page subtree routing, and adds compact color/font widget-editor controls plus a configurable chart line style — all internal to nicepaper, no further nice4iot changes needed.

## [0.32.0] - 2026-08-25

### Added

- **Telemetry Explorer supports a list of plots** (`app/core/device/data_ui.py`): the Data tab's "Add plot" button now works — each device can have any number of plot cards, each with its own title, time window, traces and "Show on dashboard" flag. Persisted as a JSON array in `.data_view.json` (was a single object; see `read_data_views`/`save_data_views`, replacing `read_data_view`/`save_data_view`). `DataView` gained `title` and `show_on_dashboard` fields. The per-trace Color/Kind/Metric selectors are now built with niceview's `Field`/`render_field()` (falling back to a plain `ui.select` when a Kind/Metric has no options yet — niceview treats an empty option list as undefined, which is a real transient state here). The plot title is now used as the chart's own title, not just an input.
- **Device Dashboard shows "Show on dashboard" plots** (`app/core/device/ui.py`, `app/core/device/data_ui.py:dashboard_plot_card`): every plot with that flag set renders as a small, read-only chart card (tight margins, no controls) alongside the Status/Timeline cards.

### Changed

- **Data tab UI overhaul** (`app/core/device/data_ui.py`): Replaced expansion panel with a card-based layout. Added plot title input, "Show on dashboard" toggle, and "Remove plot" button (now wired up — see Added). Changed auto-refresh from checkbox to switch.
- **Logs tab refactor** (`app/core/device/logs_ui.py`): Converted to class-based `_LogViewer`. Added color-coded log levels (Error/Warning/Info/Debug/Verbose). Switched to `ui.log` component for better streaming performance. Implemented position-based incremental refresh that handles log rotation. Added search filter and changed auto-refresh to switch.
- **Firmware source simplified** (`app/core/firmware/backend.py`, `app/core/firmware/models.py`, `app/core/firmware/ui.py`): Removed wildcard asset name support (`*`/`?`). Now downloads exactly one named asset per release. Removed `asset_is_wildcard` property, multi-asset state tracking, and combined digest logic. `FirmwareState` now tracks a single `asset` and `dest_filename` is always visible/used.
- **Project/Device settings reorganization** (`app/core/project/ui.py`, `app/core/device/ui.py`): Renamed "Seed" section to "Firmware Seed". Added separate "Firmware Download" section for the firmware pull configuration. Moved Seed override to device general panel under "Firmware Seed".

### Fixed

- **Device Files JSON detail: Form/Raw tabs now share live edits** (`app/core/file/detail_ui.py`): switching tabs used to show only the on-disk content, discarding whatever was typed in the other tab. Both tabs now read from and write to one in-memory object that's updated on every tab switch (in either direction); nothing is written to disk until Save is clicked.
- **README**: Clarified that InfluxDB line-protocol backend is write-only; Data tab uses Prometheus-compatible backends with local file fallback.

## [0.31.0] - 2026-08-23

### Added

- **Two new ways to seed a device, alongside the existing "New Device"
  record-only flow** — all three start from the same device record. On the
  project's Devices tab: "Flash Device" and "AP + Form Setup" buttons above
  the table prompt for a device name, create it, then open the matching
  dialog. On an existing device's own Seed card: the same two actions,
  targeting that device.
  - **Web-Serial-Flash** (`app.core.seed.action_dialogs.web_serial_flash_dialog`):
    flashes esp32paper's pre-merged full-flash image for the chosen board
    (`merged-<board>.bin`: bootloader + partition table + boot_app0 + app,
    already merged by esp32paper's own CI at the real offsets its build
    used — works on a blank board) plus a freshly generated NVS seed image,
    over a USB-serial connection from the browser — via a vendored
    [ESP Web Tools](https://github.com/esphome/esp-web-tools)
    `<esp-web-install-button>` (`app/static/esp-web-tools/`, no CDN). The NVS
    offset/size are parsed from that same build's own published
    `partitions-<board>.csv` (new `app.core.seed.partition_table`), not
    hardcoded — `app.core.seed.boards`' board registry only holds each
    board's chip family and release-asset naming convention now, on purpose.
    New `app.core.seed.nvs` (NVS partition image generation, shelling out to
    the new `esp-idf-nvs-partition-gen` dependency rather than reimplementing
    ESP-IDF's binary format) and `app.core.seed.manifest` (the ESP Web Tools
    manifest, with both parts embedded as `data:` URIs — no new authenticated
    file-serving endpoint needed).
  - **AP + Form Setup** (`app.core.seed.action_dialogs.ap_qr_dialog`): shows
    a printable QR code (new `qrcode` dependency) and deep-link URL for
    arduino4iot's own SoftAP + captive-portal setup form — that form runs
    entirely on the device; nice4iot only displays the code.
  - Both resolve the device's *effective* seed — project Seed settings with
    that device's WiFi override applied — against an operator-picked
    provisioning token: new `app.core.seed.backend.get_effective_seed`.
  - `app.core.device.ui.prompt_create_device` factored out of the existing
    "New Device" flow so all three entry points share it.
- **Firmware source `asset_name` wildcard now downloads every matching
  release asset, not just one.** A wildcard previously required an
  unambiguous single match, erroring otherwise; it now pulls all of them,
  each written under its own GitHub asset name (there's no single rename
  target for more than one file — `dest_filename` still applies only to a
  plain, non-wildcard match). This is what a project needs to mirror a
  release shipping several board-specific files side by side, e.g. for
  Web-Serial-Flash above. `FirmwareState` gained `assets: list[str]`
  (`asset` keeps the first/primary name for simple display); the up-to-date
  check is tag-based across the whole match set (still digest-based for the
  `pinned` channel, now over a combined digest of every matched asset).

## [0.30.6] - 2026-08-23

### Added

- **New "Seed" project settings section** (`app/core/seed`): the bootstrap
  data an arduino4iot device needs before it can call `/provision` and that
  nice4iot doesn't otherwise track — WiFi SSID/password, the server's public
  API URL (nice4iot has no `base_url` config and normally sits behind a
  reverse proxy, so this can't be derived automatically), and a TLS mode
  ("Public CA" / "Self-hosted / self-signed") that reveals a CA certificate
  field only when self-hosted/self-signed is selected. Combine with the
  project name and a provisioning token (existing Provisioning section) to
  seed a device. Stored as `.seed.json` in the project directory.
- **New "Seed" device settings section** with an "Override project settings"
  switch: off by default (WiFi SSID/password fields hidden), on reveals and
  enables the device's own WiFi SSID/password, overriding the project's Seed
  settings for that one device. Stored as `.seed_override.json` in the device
  directory. API URL/TLS stay project-only — they don't vary per device.

## [0.30.5] - 2026-08-23

### Added

- **Firmware source `asset_name` now accepts `*`/`?` wildcards** to match a
  release asset without hardcoding its version-specific name (e.g.
  `firmware-*.bin`). A wildcard must match exactly one asset in the release —
  no match, or more than one, fails the pull with a clear error. The matched
  asset's own name is then used as the file written into the directory, and
  the `dest_filename` field is hidden in the UI (and ignored by the backend)
  while `asset_name` is a wildcard pattern.

### Fixed

- Pre-existing `mypy` error in `app/core/firmware/backend.py`'s auto-pull
  loop (unrelated to the above): a default-arg lambda passed to
  `anyio.to_thread.run_sync` that mypy couldn't infer the type of, replaced
  with `functools.partial`.

## [0.30.4] - 2026-08-23

### Changed

- **nicepaper updated 0.18.1 → 0.19.0** (git dependency, no pinned nice4iot
  API changes). Upstream highlights: room-driven `RoomCalendar` widget
  (renders whichever room the requesting device is bound to, with
  category→color mapping and auto-generated per-panel-type templates), a
  Room Occupancy tab in the simplified UI, a device panel-type field to
  filter Screen choices, and a booking system header/category-color list
  editor. Two model changes migrate existing stored data automatically:
  `BookingSystemModel.header` (JSON string → dict) and
  `RoomCalendarWidgetModel` (dropped `room_number`/`room_name`/`ical_url`,
  now resolved from the rendering device's room binding).
- **`mypy` added to the `dev` dependency group** so `mypy extensions` (per
  `CLAUDE.md`) is actually runnable; it currently has nothing to check since
  `extensions/` stays an empty namespace package by design.

## [0.30.3] - 2026-08-22

### Changed

- **niceview updated 0.26.2 → 0.26.3.** Fixes `DrillDownWrapper` replaying its
  slide-in animation on every data change instead of only on list<->detail
  navigation.

## [0.30.2] - 2026-08-22

### Changed

- **niceview updated 0.24.0 → 0.26.2** and **nicepaper updated 0.16.0 → 0.18.1**
  (git dependencies, no pinned nice4iot API changes). Upstream highlights:
  additive `with_repositories` across niceview components, key-select
  modelselect over collections, `JsonDirectoryAdapter`, `Meta.include`/`exclude`
  for grid and list, nicepaper's simplified UI (rooms, booking systems,
  displays) and device bindings, and mypy fixes in both projects.

## [0.30.1] - 2026-08-21

### Added

- **Extensions can add an item to the user menu.** New
  `extensions.register_user_menu_item(label, on_click, *, icon=None)` appends
  an entry to the top-right user menu (the person-icon dropdown), rendered in
  the extensions' own section with nice4iot's uniform menu-item chrome.
  `get_user_menu_items()` returns `(label, icon, on_click)` in registration
  order. Like global cards it is project-independent and not gated by
  per-project enablement; `on_click` may be sync or async. See
  `docs/extensions.md` → *User menu item*.

- **Extensions can embed the whole user menu.** New
  `extensions.render_user_menu()` renders nice4iot's standard person-icon
  dropdown into an extension's own page chrome (a standalone project page),
  keeping the whole extension API surface in `app.extensions`.

- **System-telemetry snapshot cached per device.** A telemetry push with
  `kind=system` now snapshots its numeric values (`battery_V`, `wifi_rssi`, …)
  and string labels (`firmware_id`, `firmware_sha256`, …) into the device
  runtime sidecar (`.runtime.json`). `DeviceRuntime` gains **`system_metrics`**,
  **`system_labels`** and **`system_reported_at`**. The snapshot is replaced
  wholesale on each `system` push (only that kind feeds it), capped at 32
  metrics, giving O(1) access to a device's current battery/RSSI/firmware state
  without scanning the metrics JSONL. Shown on the Device Dashboard status card.

### Changed

- **User menu gains a *Home* link** to the 4IoT entry page (the projects
  overview), rendered at the top of the menu — before any
  extension-registered items.

- **niceview updated** 0.22.0 → 0.24.0. `DrillDownWrapper`'s `list_title=`
  keyword was renamed to `title=` (hard cut, no alias); the Files card wrapper
  (`app/core/file/browser_ui.py`) is updated accordingly. Also brings grid
  choice-field rendering as inline selects and cleaner list subtitles.

## [0.30.0] - 2026-08-20

### Changed

- **nicepaper updated** (pin `b465d23` → `950d1a3`, still 0.16.0). The optional
  `epaper` extension's iCal datasource now sends a fixed browser `User-Agent`
  header on its HTTP session (some calendar servers reject the default aiohttp
  agent) and additionally extracts the optional `CATEGORIES` field from each
  event. No change to nice4iot's own API.

## [0.29.0] - 2026-08-19

### Fixed

- **CI is green again.** `token_fingerprint` is no longer re-exported from
  `app.core.token.backend`; `device_provision` reads the token's own `fingerprint`
  field and the last importer (`test_provisioning_bookkeeping.py`) now imports the
  helper from `app.core.token.models`. Removes the last unused imports that
  `ruff check` flagged and the stale import that broke test collection.

## [0.28.0] - 2026-08-18

### Added

- **Provisioning-token bookkeeping per device.** Each device now records which
  provisioning token it last provisioned with, so an operator can find the devices
  affected by a soon-expiring token. Two read-only fields are added to `Device`:
  **`last_provisioning_token_fingerprint`** (a short, non-reversible SHA-256
  fingerprint of the token value — the shared secret itself is never stored on the
  device) and **`last_provisioning_token_expires_at`** (the token's expiry). The
  device carries the expiry directly, so *"which devices use a token expiring within
  N days"* is answerable by filtering device records alone — even after the token has
  been removed from `.provisioning.json`.

  - `token.models.token_fingerprint(value)` is the new helper producing the
    fingerprint (12 hex chars of the SHA-256 digest; `""` for an empty value). It is
    re-exported from `token.backend` for existing importers.
  - **`AuthToken` gains a derived `fingerprint` field.** It is recomputed from `value`
    on construction, on load, and — via `validate_assignment` on the model — on every
    in-place field edit (the UI form assigns fields rather than reconstructing the
    model). Any `fingerprint` stored in a token file is ignored and recomputed on load.
    The field is read-only in the UI (`niceview.Field(editable=False)`); it is not
    placed in the token card's layout by default.
  - `project.backend.get_auth_project()` now returns **`(project, token)`** instead of
    just `project`, so the provisioning flow knows which token authenticated the call.
  - `device.backend.device_provision()` gains an optional
    **`provisioning_token: AuthToken | None`** keyword; when supplied it records the
    fingerprint and expiry on the device. Omitting it (the default) leaves the fields
    empty, keeping existing callers working unchanged.
  - UI: the device Timeline card shows *Provisioning token expires* (with the
    fingerprint in a tooltip); the project Devices table gains a sortable *Token
    Expires* column.

- **Built-in "provisioning token expiring" alarm.** A new
  `ProvisioningTokenExpiryAlarm` (in `AlarmConfig.provisioning_expiry`) and
  `alarm.backend.evaluate_provisioning_expiry(project_name)` fire one alarm per active
  device whose recorded provisioning-token expiry is within a configurable lead time
  (`token_expiration_threshold`, default 7 days) — read straight from the device
  record, so no token lookup is needed. With `only_tokens_in_active_use=False`,
  project provisioning tokens that no device uses are flagged too, keyed by
  fingerprint. Evaluated on the same 60 s background loop as the device-offline rule.

### Changed

- **`MetricAlarmRule.description` is removed.** The free-text override is gone; a
  triggered metric alarm's message is now always auto-generated from the rule
  (`"<metric> <comparison> <threshold> (got <value>)"`). Files still carrying a
  `description` load fine (pydantic ignores the unknown key) and drop it on next write.

- **Duration fields become `datetime.timedelta` instead of int seconds/days/minutes.**
  Following the device-offline threshold, the remaining interval/lifetime settings move
  to `timedelta`, so niceview 0.21.3 renders its tolerant duration widget (`7d`,
  `2h30m`, ISO 8601) for them:
  - `FirmwareSource.auto_pull_interval_min` (int minutes) → **`auto_pull_interval`**
    (`timedelta`, default 1 h, floored at 5 min).
  - `FileConfig.mqtt_check_interval_s` (int seconds) → **`mqtt_check_interval`**
    (`timedelta`, default 60 s, floored at 10 s).
  - `AppConfig.device_token_expires_in` (int days) → **`timedelta`** (default 7 d),
    matching `provisioning_token_expires_in`.

  Two migration bugs in the earlier int→`timedelta` change are fixed: creating a bearer
  token no longer wraps the already-`timedelta` `device_tokens_expire_in` in
  `timedelta(days=…)` (which crashed provisioning), and `Project`'s legacy parser for
  that field now maps a legacy int to whole days and a pydantic-serialised float to
  seconds (both previously collapsed to a few seconds). HTTP request timeouts stay
  plain int seconds by design.

- **`device_online_threshold_s` moves from `Project` to the device-offline alarm
  config.** The threshold decides when a device counts as offline, which is the one
  thing the device-offline alarm rule is about — and the switch that turns that rule
  on already lived in `AlarmConfig.device_offline`. Splitting the two across
  `project.json` and `.alarm_config.json` meant editing an alarm in two cards.
  `DeviceOfflineConfig` is renamed to **`DeviceOfflineAlarm`** and gains the field, now a
  **`datetime.timedelta`** named **`device_offline_threshold`** (default 1 day) instead of
  an int-seconds `device_online_threshold_s`; `Project.device_online_threshold_s` is
  removed, together with its slot in the `settings` profile. Readers outside the alarm
  module (project and device dashboards) go through the new
  **`alarm.backend.get_device_offline_threshold(project_name)`**, which returns a
  `timedelta` and falls back to the model default if the config cannot be read.
  `device.backend.is_device_online(device, threshold)` now takes a `timedelta`.
  In the UI, the Device Offline block of the alarm config card is a single `ModelForm`
  over the whole model, rendering the activation checkbox (label suppressed) and the
  threshold input side by side in one row.

  *Migration:* a project's stored `device_online_threshold_s` is dropped when
  `project.json` is next read, and the alarm config starts at the 1-day default.
  Projects that used a custom threshold have to set it again on the alarm card.

- **niceview 0.16.0 → 0.22.0.** Chrome button styling gained a second axis: props are
  layered `{place} → shape → role`, where the place is `toolbar`, `form` or `dialog`.
  Two of its breaking changes reach us:

  - `ChromeStyle.button_props` is gone — a base layer below the places no longer
    exists, because "every button of this app is dense" is a statement about a type
    and NiceGUI owns it (`ui.button.default_props`). `app/main.py` therefore drops
    `set_chrome_style(button_props='')` and keeps only the icon shape, now scoped to
    the place it applies to: `set_chrome_style(toolbar_icon_button_props='dense round')`.
    This reverses the note in 0.27.0 that `set_chrome_style()` is deliberately not
    called — with icon-only chrome buttons wanted round, there is now something to say.
  - `confirm_dialog(ok_color=…)` → `ok_role=…`, which picks the confirm button from
    the role layer instead of handing it a color. The three delete confirmations
    (device, project, file) now pass `ok_role='delete'` instead of
    `ok_color='negative'`, so they follow whatever delete buttons look like.

  Also in 0.19.0, unused here so far: `ChromeText` for replacing every string
  niceview shows, an application-wide `FieldStyle`, dialog and notification chrome,
  and `'## Title'` for a form section heading without a card.

  0.20.0 and 0.21.0 are purely additive and reach us as an opportunity rather than
  as work: **`FormAction`** puts a button that is not a field into a form (placed as
  `'@name'` in a layout) and, via **`chrome_actions=`**, into the title row of every
  wrapper — `EditFormWrapper`, `EditGridWrapper` and `DrillDownWrapper` alike. On a
  drill-down the actions belong to the detail view and are hidden in the list, with
  a `DrillDownActionEventArguments` naming the item on screen. That is the way our
  own buttons get into niceview's chrome instead of sitting beside it; the Files
  card's per-row Download/Delete are the first candidates.

  0.21.1 is purely additive too: `ChromeStyle` form-container knobs
  (`form_row_classes`, `form_column_classes`, `form_card_classes`, `form_card_props`)
  and two `FieldStyle` knobs (`caption_classes`, `checkbox_group_classes`); defaults
  unchanged, no code change needed.

  0.21.2 fixes `niceview.Field(label='')` in a model annotation to actually suppress
  the label (previously indistinguishable from unset). `AuthToken.is_active` now
  carries `niceview.Field(label='', …)` on the field itself instead of relying on the
  token card's `field_infos`.

  0.21.3 makes `timedelta` fields accept tolerant input (`7d`, `2h30m`, ISO 8601),
  rewritten to canonical form on blur — the input side of the int-seconds → `timedelta`
  migration of duration fields (e.g. the device-offline threshold above).

  0.22.0 adds **`BoundFieldAdapter(parent, field_name)`**, an `ItemAdapter` that focuses a
  parent adapter onto one embedded sub-model — exactly what the alarm card needed. The
  alarm UI drops its own `_SubAdapter` and binds the Device-Offline and
  Provisioning-Expiry forms to `BoundFieldAdapter(alarm_adapter, 'device_offline'|'provisioning_expiry')`.

- **nicepaper 0.15.1 → 0.16.0.** Internal restructure of the e-paper editor plus a fix for
  an Image widget crashing its form in a project with no image files yet. nice4iot only
  references nicepaper by name (version display, SBOM), so no code change is needed.

- **`URL_REGEX` accepts the forwarding targets people actually use.** It required a
  dotted hostname, which ruled out every address a container talks to inside its own
  network — `http://influx:8086/write`, `http://localhost:8086/write`, and any IP.
  The example in `ForwardingConfig`'s own docstring was among the rejects.

  It now takes a single-label host, an IPv4 or a bracketed IPv6 address, an optional
  port, and anything after the first `/`, `?` or `#`. The scheme stays optional, so a
  `forward_url` stored before this keeps validating. Malformed input is still refused
  (`javascript:`, `ftp://`, `file://`, a host with no name, labels edged with hyphens),
  and the pattern backtracks linearly — 80 labels resolve in well under a millisecond.
  `URL_REGEX` reaches only `ForwardingConfig.forward_url`.

- **The token and forwarding cards render as one form instead of field by field.**
  Both used to place their inputs with `render_field()` calls interleaved with plain
  `ui.button`s, because a callback cannot live in a layout string. niceview 0.20.0's
  `FormAction` closes that gap: the buttons are declared in `actions=` and placed by
  `'@delete'` / `'@copy'` in `layout=`, so each card is a single `render()`.

  Their handlers take the token or rule off `e.form.item` rather than off a
  late-bound default argument, and `render_nonfield_errors()` is no longer called by
  hand — `render()` does it. `TokenListCard._unique_name()` is gone with the label it
  seeded; the forwarding one stays, where the name reaches the device-facing URL.

  Worth knowing when editing these layouts: a field's or action's `':classes'`
  **replace** what niceview would apply, including the alignment it gives an action
  in a row (`self-center`, plus `mb-5` next to an input that reserves message space).

- **The Files card's row actions move into the detail title row.** Download, Publish
  and Delete were three buttons on every list row. Download and Publish are now the
  wrapper's `chrome_actions`, so they sit in niceview's chrome instead of beside it
  and act on the one file the detail view is about; **Delete is niceview's own
  button**, no longer suppressed with `delete_button=None`. The rows lose their
  buttons and become clickable as a whole; what stays in them is what the generic
  `ModelList` rows cannot express and is why `render_list_item` is still ours — the
  type icon, the `project` chip, and the publish stamp (which comes from the card's
  file state, not from the entry).

  Handing Delete back to niceview removes code rather than adding it: the wrapper
  routes through `DirectoryAdapter.delete()`, which only ever touches the card's own
  directory — exactly the device copy meant — and notifies its change listeners, so
  the list refreshes and the view navigates back without our help. The button also
  picks up the `delete` chrome role instead of an action of ours spelling out
  `color=negative` and bypassing the cascade that exists to hold it.

  What used to argue against it was the confirmation text, which differs per entry:
  dropping a device copy so the project file applies again is not the irreversible
  delete of a plain file. A `ChromeText` slot takes a **callable** resolved when the
  text is rendered, so that survives — `_delete_texts()` words the question from the
  entry on screen, and the dialog renders it as markdown either way.

  Two conditions, handled at the level each belongs to: **Publish** is constant per
  card and is therefore absent altogether where it cannot work, while **Delete** is
  per file and is hidden for an inherited entry, which has no device copy to remove
  (the adapter would raise `KeyError` — the button is not merely pointless there, it
  cannot work). Hiding it is sound because niceview updates the title row *before*
  refreshing the body on every navigation, so a visibility set from `render_detail`
  holds — a test pins that ordering, since a niceview change reversing it would
  silently offer Delete on a file it cannot delete.

- **`AuthToken.name` is removed.** Nothing ever read it: authentication matches on
  `value`/`is_active`/`expires_at`, the adapter keys by list position rather than by a
  field, and no API returned it. Device tokens never had one — they are minted by
  `provision_device()`.

  **Existing token files keep working.** Pydantic ignores unknown keys, so a
  `.provisioning.json` or `.tokens.json` still carrying a `"name"` loads as before; the
  key is dropped on the next write. Device token files heal on their own at the first
  authentication, which rewrites them anyway to record `last_use_at`. niceview logs one
  `Unknown field 'name' ignored` per stale entry per read until then — noise, not an
  error. `tests/test_token_name_removal.py` pins both directions.

  The UI loses more than the input: `TokenListCard.show_name` existed only for this
  field and forked the card between provisioning and device tokens. It is gone, together
  with `_unique_name()`, the `name or value[:8]` fallback in the delete notification,
  and the `name=` parameter of `create_token()`.

- **The download-only detail views lose their own Download button**, now that the
  title row has one that reaches every file. They state the reason and point at it
  ("Binary file — no inline preview. Use Download above to save it."), so the text
  no longer dangles where the button used to be.

- **Button props across the UI are normalised.** `flat dense` → `dense flat`, the
  redundant `color=primary` is dropped (a `ui.button` is primary anyway), and
  icon-only buttons are `round`. The alarm acknowledge actions become icon buttons
  with explaining tooltips, the "OK" chip is outlined, and the Files card's Add
  button loses its label.

- **The data explorer's layout is rearranged**: label markers move up into the
  controls row, the summary row moves below the chart, and Add trace sits in the
  last trace row instead of under the list, so it is clear which trace it follows.

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
