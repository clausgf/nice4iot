# File Editing & Schema-Driven Forms

Status: **implemented in 0.14.0.** This documents the feature and the design
decisions behind it. It is spread over five modules in `app/core/file/`, split
so that everything decidable without a browser stays free of NiceGUI:

| Module | Role |
|---|---|
| `overlay.py` | the device-over-project merge; hands the UI a resolved entry per file |
| `form.py` | field inference, the schema subset, schema approval, and `plan_json_view()` — the decision table below, in code |
| `form_ui.py` | one `FormField` → one widget, plus the value collector |
| `detail_ui.py` | the detail half of the card: JSON/text editors, image preview, save/publish/download |
| `browser_ui.py` | the list half: rows, upload, new file, and the panel entry points |

[← Documentation index](README.md) · [Architecture](architecture.md)

---

## Scope

Evolves the existing **Files** tabs for both project files (`<project>/<file>`)
and device files (`<project>/<device>/<file>`) from a set of modal dialogs into a
browse-and-drill-down editor, adds image preview and editable text, and
introduces an optional **form view** for JSON files driven by a minimal
JSON-Schema subset.

What already exists and stays: per-directory file list, upload, download,
delete, "New JSON", CodeMirror JSON editor with validation and atomic save,
read-only text viewer, MQTT force-publish, project→device fallback.

## One list per device

The device Files tab lists the device's **effective** file set: its own files
layered over the project's, with the same precedence the device-facing API
(`get_file_path()`) and the MQTT publisher (`check_and_publish_project()`) apply.
An entry served from the project directory carries a `project` chip. The merge
lives in `app/core/file/overlay.py`.

Writes never reach the project directory from here. Saving an inherited file is a
**copy-on-write**: the content is written to the device directory, the project
file is untouched, and the chip disappears. Uploads and "New JSON" behave the
same way — always device-local, overriding a project file of that name if one
exists. Inherited entries therefore have no delete button; deleting a device
override makes the inherited entry reappear. Project files are edited in the
project's own Files tab, where nothing is inherited.

## Goals

- Drill-down from the file list to a per-file editor (deep-linkable).
- Image files viewable; binary files remain download-only.
- Text files editable (not just JSON); binary never editable.
- JSON files editable as **form** and **raw CodeMirror**, side by side (tabs).
- The form is generated from a minimal, admin-curated schema; device-supplied
  schemas require explicit approval before they drive the UI.

## The schema subset

We accept a **deliberately small subset of JSON Schema** — familiar vocabulary,
easy for device firmware to emit — and **ignore every keyword we don't know**.
This is *not* a JSON Schema implementation and pointedly avoids the full spec's
risk surface (see [Security](#security-model)).

Only a **flat object** is supported: `type: object` with `properties` whose
values are scalars (or a string array). No nested objects, no `$ref`, no
`oneOf`/`anyOf`/`allOf`.

### Type → widget mapping (v1)

| Schema | Widget | Value |
|---|---|---|
| `type: string` | `ui.input` | `str` |
| `type: string` + `enum` | `ui.select` | `str` from the enum |
| `type: string` + `x-multiline: true` | `ui.textarea` | `str` |
| `type: string` + `format: "date"` | date picker | ISO-8601 date string |
| `type: integer` | `ui.number` (integer) | `int` |
| `type: number` | `ui.number` | `float` |
| `type: boolean` | `ui.switch` | `bool` |
| `type: array`, `items.type: string` | `ui.input_chips` | `list[str]` |

`x-multiline` uses the JSON-Schema-blessed `x-` extension prefix (validators
ignore it), since the spec has no standard "multiline" hint.

### Keywords honoured

`type`, `properties`, `enum`, `title`, `description`, `default`, `required`,
`minimum`/`maximum` (numbers), `maxLength` (strings), `maxItems` (arrays),
`format: "date"`, `items.type` (string arrays), `x-multiline`.

### Deliberately NOT supported in v1

Nested objects · arrays of non-strings · `$ref` · `pattern` (untrusted regex —
ReDoS risk, ignored for now) · `oneOf`/`anyOf`/`allOf`/`if`/`then` ·
`additionalProperties` semantics beyond the merge rule below. Unknown keywords
are ignored, so a richer schema still renders (just with fewer honoured
constraints).

## Schema binding

Convention, no new API — a device places its schema through the existing file
upload, a user creates it in the UI:

```
device-dir/
  config.json
  config.schema.json     ← drives the form for config.json
project-dir/
  config.schema.json     ← fallback when the device dir has none
```

`<name>.schema.json` is the schema for `<name>.json`, resolved **device dir
first, then project dir** — the same fallback order as the data files
themselves. Schema files are `.schema.json`, listed like any other file but
recognised as schemas.

## Editor view and default tab

Opening a JSON file shows up to three tabs; which is **default** depends on the
schema:

| Situation | Default tab | Other tabs |
|---|---|---|
| Approved schema present | **Form** | Raw (CodeMirror) |
| Flat JSON, no schema | Raw (CodeMirror) | Form (types inferred from values) |
| Non-flat JSON, or non-JSON text | Raw (CodeMirror) | — |
| Image | **Preview** | — |
| Binary (other) | — (download only) | — |

"Flat JSON" = top-level object whose values are all scalars/string-arrays.
Anything else is raw-only.

This table is `plan_json_view()` in `form.py`: it reads the file, resolves
and checks the schema, and returns which tabs to build and which one leads. The
detail view only switches on the result, so the table is unit-tested directly
rather than through a rendered panel.

## Save semantics — merge

Saving the **form** writes back only the schema's fields and **preserves any
other keys** already in the file:

```
file:   {"interval_s": 30, "secret_key": "abc"}   (schema covers only interval_s)
save →  {"interval_s": 45, "secret_key": "abc"}    (secret_key kept)
```

This is data-safe when a schema covers only part of a file. The **raw** editor
still writes the whole document verbatim. No live sync between the two tabs;
switching tabs re-loads from the current value, with an "unsaved changes" guard.

## Approval workflow & trust model

The security-critical piece. A device holds a valid token and can upload files,
so a **device-supplied schema is untrusted input that would otherwise render in
an authenticated admin browser**. Therefore:

- A device-uploaded schema is **inert** until the user approves it. While
  unapproved, the data file falls back to the raw editor (or the last approved
  schema, if one exists).
- Approval is **bound to the schema's content hash** (SHA-256 of the file
  bytes). Approving stores that hash.
- If the device **changes** the schema, the bytes change → the hash changes → it
  is no longer in the approved set → the file reverts to pending and the user is
  asked to approve again. This is the required "device updates, re-prompt" flow,
  achieved without tracking *who* wrote the file.
- A schema **created or edited in the UI** is admin-provenance: its new hash is
  recorded as approved at save time, so it is active immediately.

Approved hashes live in a project-level sidecar `.schema_approvals.json`
(`{ "<relative-schema-path>": "<sha256>" }`). It is a dotfile, so it never
appears in the file list and is never served to devices.

"Approved" is simply "the current schema file's hash is in the approved set" —
one predicate covers device-uploaded, edited, and UI-created cases.

## Security model

- **Untrusted schema is treated as data, never as code.** The schema-driven form
  is rendered by a small dedicated **interpreter** (a fixed switch over the
  widget types above), **not** by feeding schema-derived types into
  `pydantic.create_model` / niceview. niceview `ModelForm` stays reserved for
  our own code-defined models (device/project settings). This keeps the
  untrusted-input path small and auditable and decoupled from niceview's
  evolution.
- **No HTML/Markdown for schema-supplied text.** `title`, `description`, `enum`
  labels, and values render through `ui.label`/`ui.input`/CodeMirror (text
  nodes) — never `ui.markdown`/`ui.html` — so a schema cannot inject markup/XSS.
- **No network, no untrusted regex.** `$ref` is unsupported (no remote fetch /
  SSRF); `pattern` is ignored (no untrusted regex / ReDoS). Our own validation
  covers `required`, `min`/`max`, `maxLength`, `maxItems`, `enum`, and type.
- **Caps** on schema size and field count; JSON parsed with `json.loads` (no
  code execution).
- **Images** are shown via `<img>` with a `data:` URI (inert; scripts in an
  `<img>`-loaded SVG do not execute). SVG is never inlined via `ui.html`. Limit
  ~2 MB; formats png/jpg/gif/webp; larger or other types stay download-only.
- Filenames keep going through `is_valid_upload_filename` (no traversal).

## Other decisions (defaults)

- **Drill-down** is built on niceview's `DrillDownWrapper` (in-page list↔detail
  navigation with a Back button and slide animation). The originally-planned
  per-file deep-link was dropped in favour of reusing the wrapper; the Files tab
  itself stays deep-linkable via `?tab=Files`.
- **Editable vs download-only:** JSON and the recognised text extensions
  (`.txt/.yaml/.yml/.toml/.md/.csv/.ini/.cfg/.conf/.xml/.html/.css/.js/.py/.sh`)
  are editable; images preview-only; everything else download-only.
- **Validation scope:** UI-only. The server does **not** reject device-uploaded
  data that violates a schema; the schema drives the form and in-UI validation,
  not API ingest. (Server-side validation is a possible later addition.)
- **Where validation shows:** widgets that carry NiceGUI's own validation
  (input, number, select, input_chips) display the message inline, under the
  field; switch and textarea have none, so they are reported on save. Either way
  the save-time check over all fields stays authoritative — inline errors inform,
  they do not block.
- **"New JSON"** asks for a filename only (`niceview.util.input_dialog`), writes
  an empty object and drills straight into its editor, instead of carrying a
  second CodeMirror inside a dialog. Creating a device file that hides a project
  file of the same name is allowed; the confirmation says so.
- **Async I/O:** the large upload write is pushed to a worker thread
  (`anyio.to_thread.run_sync`), like the device-facing `PUT /api/file`. The
  remaining reads (editor content, image bytes, the directory listing, the schema
  read + hash) run inside NiceGUI's synchronous render — and, for the browser,
  inside `DrillDownWrapper`'s synchronous `render_list_item` / `render_detail`
  callbacks — so they cannot be awaited without an async-render hook in niceview.
  They are bounded, single, mostly small local-FS reads, kept synchronous.

## Delivery

Built and shipped in three phases, all in 0.14.0:

1. **Editing UX** — drill-down (DrillDownWrapper), image preview, editable text.
2. **Auto-form** — form tab for *flat JSON without a schema*, field types
   inferred from the current values (raw stays default).
3. **Schema-driven form** — the JSON-Schema subset, the interpreter, and the
   approval workflow above.

## Deferred / out of scope

Server-side validation of device data against the schema · nested objects ·
`pattern`/regex constraints · a hardened real `jsonschema` library (only ever
for *validation*, never rendering, and only if the subset proves too small) ·
non-string arrays.
