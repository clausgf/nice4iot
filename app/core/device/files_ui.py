"""
Device / Project Files — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

Built on niceview's DrillDownWrapper over a DirectoryAdapter in all-files mode
(mixed extensions, keyed by full filename): the list drills down into a per-file
detail view. JSON opens in a validating CodeMirror editor, recognised text files
in a plain editor, images (png/jpg/gif/webp ≤ 2 MB) as an inline preview; SVG and
other binaries stay download-only (untrusted SVG is never rendered inline — see
docs/file-forms.md).
"""
import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NamedTuple

import anyio
from nicegui import ui
from niceview import DirectoryAdapter, DrillDownWrapper, FileEntry
from niceview.util import confirm_dialog

from app.core.device.backend import get_device_path
from app.paths import project_dir as get_project_dir
from app.util import is_valid_upload_filename, render_datetime

import logging
log = logging.getLogger("uvicorn")

# ---------------------------------------------------------------------------
# File-type constants
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    '.yaml': 'YAML',  '.yml':  'YAML',
    '.toml': 'TOML',  '.xml':  'XML',
    '.html': 'HTML',  '.md':   'Markdown',
    '.py':   'Python', '.sh':  'Shell',
    '.css':  'CSS',   '.js':   'JavaScript',
}
_TEXT_EXTENSIONS: set[str] = {'.txt', '.log', '.csv', '.ini', '.cfg', '.conf'} | set(_LANG_MAP)
_MAX_VIEWER_SIZE: int = 100 * 1024  # 100 KB — larger text stays download-only

# Images rendered inline as a data: URI. SVG is deliberately excluded — scripts in
# an inline-rendered SVG would execute; larger images stay download-only.
_IMAGE_MIME: dict[str, str] = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp',
}
_MAX_IMAGE_SIZE: int = 2 * 1024 * 1024  # 2 MB


class _Ctx(NamedTuple):
    """Per-card context: which project/device and whether to publish over MQTT.

    device_name is None for the project Files tab (no device to publish to).
    """
    project_name: str
    device_name: str | None
    mqtt_enabled: bool


def _codemirror_language(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == '.json':
        return 'JSON'
    return _LANG_MAP.get(ext)


# ---------------------------------------------------------------------------
# Shared write / publish / download helpers
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> bool:
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        tmp.rename(path)
        return True
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        ui.notify(f'Save failed: {exc}', type='negative')
        return False


def _maybe_publish(path: Path, ctx: _Ctx) -> None:
    if ctx.mqtt_enabled and ctx.project_name and ctx.device_name:
        from app.core.file.backend import publish_file_now
        asyncio.create_task(publish_file_now(ctx.project_name, ctx.device_name, path))


def _download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Detail view (render_detail) — one file, dispatched by type
# ---------------------------------------------------------------------------

@dataclass
class _FormField:
    """One form field. Phase 2 infers key/kind/value from a flat JSON object's
    values; phase 3 builds the same shape from a schema, adding the metadata
    below (title/enum/min/max/…)."""
    key: str
    kind: str        # string | integer | number | boolean | string_list | enum | textarea | date
    value: Any
    label: str | None = None
    description: str | None = None
    enum: list | None = None
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None
    max_items: int | None = None
    required: bool = False


def _infer_kind(v: Any) -> str | None:
    if isinstance(v, bool):        # bool is a subclass of int — check it first
        return 'boolean'
    if isinstance(v, int):
        return 'integer'
    if isinstance(v, float):
        return 'number'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return 'string_list'
    return None


def _infer_flat_fields(obj: dict) -> list[_FormField] | None:
    """Field specs for a flat object, or None if any value isn't representable
    (nested object, mixed/other list, null) — then no form tab is offered."""
    fields: list[_FormField] = []
    for key, value in obj.items():
        kind = _infer_kind(value)
        if kind is None:
            return None
        fields.append(_FormField(key, kind, value))
    return fields


# --- schema-driven form (phase 3): a minimal JSON-Schema subset -------------
# Deliberately NOT a JSON Schema implementation: flat object only, a fixed set of
# types, unknown keywords ignored, and no $ref (SSRF) / pattern (untrusted regex,
# ReDoS). Rendered by _render_form_field below — never fed to pydantic.create_model
# or niceview — so the untrusted-input path stays small. See docs/file-forms.md.

_SCHEMA_MAX_BYTES = 256 * 1024
_SCHEMA_MAX_FIELDS = 500


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _empty_for(kind: str) -> Any:
    return {'boolean': False, 'string_list': []}.get(kind, None if kind in ('integer', 'number') else '')


def _schema_kind(spec: dict) -> str | None:
    t = spec.get('type')
    if t == 'string':
        if isinstance(spec.get('enum'), list):
            return 'enum'
        if spec.get('format') == 'date':
            return 'date'
        if spec.get('x-multiline') is True:
            return 'textarea'
        return 'string'
    if t == 'integer':
        return 'integer'
    if t == 'number':
        return 'number'
    if t == 'boolean':
        return 'boolean'
    if t == 'array' and isinstance(spec.get('items'), dict) and spec['items'].get('type') == 'string':
        return 'string_list'
    return None  # unknown/unsupported type — ignored (field editable via raw only)


def _fields_from_schema(schema: dict, data: dict) -> list[_FormField] | None:
    """Build form fields from the schema subset, or None if it is not a usable
    flat object schema. Values come from *data*, then the field's ``default``."""
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        return None
    props = schema.get('properties')
    if not isinstance(props, dict):
        return None
    required = set(schema.get('required') or [])
    fields: list[_FormField] = []
    for name, spec in list(props.items())[:_SCHEMA_MAX_FIELDS]:
        if not isinstance(spec, dict):
            continue
        kind = _schema_kind(spec)
        if kind is None:
            continue
        default = spec.get('default')
        value = data.get(name, default if default is not None else _empty_for(kind))
        fields.append(_FormField(
            key=name, kind=kind, value=value,
            label=spec.get('title') if isinstance(spec.get('title'), str) else None,
            description=spec.get('description') if isinstance(spec.get('description'), str) else None,
            enum=spec.get('enum') if isinstance(spec.get('enum'), list) else None,
            minimum=_num(spec.get('minimum')), maximum=_num(spec.get('maximum')),
            max_length=_int(spec.get('maxLength')), max_items=_int(spec.get('maxItems')),
            required=name in required,
        ))
    return fields


def _resolve_schema_path(data_path: Path, fallback_dir: Path | None) -> Path | None:
    """The '<name>.schema.json' sibling of a '<name>.json' data file, resolved in
    the file's own directory first, then *fallback_dir* (device dir → project dir).
    Schema files themselves get no schema."""
    if data_path.suffix.lower() != '.json' or data_path.name.endswith('.schema.json'):
        return None
    schema_name = f'{data_path.name[:-len(".json")]}.schema.json'
    here = data_path.with_name(schema_name)
    if here.is_file():
        return here
    if fallback_dir is not None:
        there = fallback_dir / schema_name
        if there.is_file():
            return there
    return None


def _load_schema(schema_path: Path) -> dict | None:
    try:
        if schema_path.stat().st_size > _SCHEMA_MAX_BYTES:
            return None
        parsed = json.loads(schema_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# --- schema approval (device-uploaded schemas are inert until approved) ------

def _approvals_path(project_name: str) -> Path:
    return get_project_dir(project_name) / '.schema_approvals.json'


def _schema_key(schema_path: Path, project_name: str) -> str:
    try:
        return schema_path.relative_to(get_project_dir(project_name)).as_posix()
    except ValueError:
        return schema_path.name


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_approvals(project_name: str) -> dict:
    path = _approvals_path(project_name)
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_schema_approved(schema_path: Path, project_name: str) -> bool:
    try:
        current = _file_sha256(schema_path)
    except OSError:
        return False
    return _load_approvals(project_name).get(_schema_key(schema_path, project_name)) == current


def _approve_schema(schema_path: Path, project_name: str) -> None:
    """Record the schema's current content hash as approved. Called when a user
    approves an uploaded schema, or saves/edits one in the UI (admin provenance)."""
    try:
        digest = _file_sha256(schema_path)
    except OSError:
        return
    approvals = _load_approvals(project_name)
    approvals[_schema_key(schema_path, project_name)] = digest
    _atomic_write_text(_approvals_path(project_name), json.dumps(approvals, indent=2) + '\n')


def _render_widget(field: _FormField, label: str) -> Callable[[], Any]:
    """Render the input widget for *field*; return a getter for its value.

    Only text goes into text-rendering widgets (labels, options) — schema-supplied
    strings are never passed to ui.markdown/ui.html, so a schema cannot inject markup.
    """
    if field.kind == 'boolean':
        w = ui.switch(label, value=bool(field.value))
        return lambda: bool(w.value)
    if field.kind == 'enum':
        options = [str(x) for x in (field.enum or [])]
        w = ui.select(options, label=label, value=field.value if field.value in options else None) \
            .props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'textarea':
        w = ui.textarea(label, value=field.value or '').props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'date':
        w = ui.input(label, value=field.value or '').props('outlined dense type=date').classes('w-full')
        return lambda: w.value or None
    if field.kind == 'integer':
        w = ui.number(label, value=field.value, precision=0, step=1,
                      min=field.minimum, max=field.maximum).props('outlined dense').classes('w-full')
        return lambda: int(w.value) if w.value is not None else None
    if field.kind == 'number':
        w = ui.number(label, value=field.value, min=field.minimum, max=field.maximum) \
            .props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'string_list':
        w = ui.input_chips(label, value=list(field.value or [])).props('outlined dense').classes('w-full')
        return lambda: list(w.value or [])
    w = ui.input(label, value=field.value or '').props('outlined dense').classes('w-full')
    if field.max_length:
        w.props(f'maxlength={field.max_length}')
    return lambda: w.value


def _render_form_field(field: _FormField) -> Callable[[], Any]:
    label = (field.label or field.key) + (' *' if field.required else '')
    with ui.column().classes('w-full gap-0'):
        getter = _render_widget(field, label)
        if field.description:
            ui.label(field.description).classes('text-caption text-grey-6')
    return getter


def _validate_field(field: _FormField, value: Any) -> str | None:
    """Enforce the subset's constraints with plain checks (no regex). Returns the
    first error message for *field*, or None if the value is acceptable."""
    name = field.label or field.key
    empty = value is None or value == '' or value == []
    if field.required and empty:
        return f'{name}: required'
    if empty:
        return None
    if field.kind in ('integer', 'number'):
        if field.minimum is not None and value < field.minimum:
            return f'{name}: must be ≥ {field.minimum}'
        if field.maximum is not None and value > field.maximum:
            return f'{name}: must be ≤ {field.maximum}'
    if field.kind in ('string', 'textarea') and field.max_length and len(value) > field.max_length:
        return f'{name}: at most {field.max_length} characters'
    if field.kind == 'enum' and field.enum and value not in [str(x) for x in field.enum]:
        return f'{name}: not an allowed value'
    if field.kind == 'string_list' and field.max_items is not None and len(value) > field.max_items:
        return f'{name}: at most {field.max_items} items'
    return None


def _json_form(path: Path, ctx: _Ctx, original: dict, fields: list[_FormField]) -> None:
    getters: dict[str, Callable[[], Any]] = {}
    with ui.column().classes('w-full gap-3'):
        if not fields:
            ui.label('Empty object — nothing to edit as a form.').classes('text-caption text-grey-6')
        for field in fields:
            getters[field.key] = _render_form_field(field)

    def _save() -> None:
        values = {f.key: getters[f.key]() for f in fields}
        for f in fields:
            if (err := _validate_field(f, values[f.key])) is not None:
                ui.notify(err, type='negative')
                return
        # Merge into the existing object: overwrite only the form's keys, keep the
        # rest (a schema may cover only part of the file).
        merged = dict(original)
        merged.update(values)
        if _atomic_write_text(path, json.dumps(merged, indent=2, ensure_ascii=False) + '\n'):
            ui.notify(f'Saved {path.name}', type='positive')
            _maybe_publish(path, ctx)

    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button('Save', on_click=_save).props('color=primary')


def _json_raw_editor(path: Path, ctx: _Ctx, content: str) -> None:
    editor = (
        ui.codemirror(value=content, language='JSON', line_wrapping=True)
        .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
    )

    def _save() -> None:
        try:
            parsed = json.loads(editor.value)
        except json.JSONDecodeError as exc:
            ui.notify(f'Invalid JSON: {exc}', type='negative')
            return
        if _atomic_write_text(path, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'):
            ui.notify(f'Saved {path.name}', type='positive')
            _maybe_publish(path, ctx)
            if path.name.endswith('.schema.json'):
                # Editing/creating a schema in the UI is admin provenance → auto-approved.
                _approve_schema(path, ctx.project_name)

    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button('Save', on_click=_save).props('color=primary')


def _schema_pending_banner(schema_path: Path, ctx: _Ctx, on_approve: Callable[[], None]) -> None:
    with ui.row().classes('w-full items-center gap-2 q-pa-sm rounded-borders') \
            .style('background: rgba(255,167,38,0.15)'):
        ui.icon('warning').classes('text-orange')
        ui.label(f'The schema "{schema_path.name}" was uploaded and needs your approval '
                 'before it drives the form.').classes('grow text-body2')

        def _approve() -> None:
            _approve_schema(schema_path, ctx.project_name)
            ui.notify(f'Approved {schema_path.name}', type='positive')
            on_approve()
        ui.button('Approve', icon='verified', on_click=_approve).props('dense color=primary')


def _json_with_form(path: Path, ctx: _Ctx, parsed: dict, pretty: str,
                    fields: list[_FormField], *, form_default: bool) -> None:
    """Form + Raw tabs; *form_default* selects which is shown first. No live sync
    between the tabs — each renders from the on-disk content read by the caller."""
    with ui.tabs().classes('w-full') as tabs:
        form_tab = ui.tab('Form')
        raw_tab = ui.tab('Raw')
    with ui.tab_panels(tabs, value=(form_tab if form_default else raw_tab)).classes('w-full'):
        with ui.tab_panel(form_tab):
            _json_form(path, ctx, parsed, fields)
        with ui.tab_panel(raw_tab):
            _json_raw_editor(path, ctx, pretty)


def _render_json_detail(path: Path, ctx: _Ctx, fallback_dir: Path | None = None) -> None:
    """JSON detail. With an approved sibling schema the schema-driven form is the
    default tab; without one, a flat object still gets an inferred Form tab (raw
    default). An unapproved uploaded schema shows an approval banner and raw only.
    Wrapped in a local refreshable so approving re-renders the view in place."""

    @ui.refreshable
    def detail() -> None:
        try:
            parsed = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except (OSError, json.JSONDecodeError):
            content = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '{}'
            _json_raw_editor(path, ctx, content)
            return
        if not isinstance(parsed, dict):
            _json_raw_editor(path, ctx, pretty)
            return

        schema_path = _resolve_schema_path(path, fallback_dir)
        if schema_path is not None:
            if not _is_schema_approved(schema_path, ctx.project_name):
                _schema_pending_banner(schema_path, ctx, on_approve=detail.refresh)
                _json_raw_editor(path, ctx, pretty)
                return
            schema = _load_schema(schema_path)
            schema_fields = _fields_from_schema(schema, parsed) if schema is not None else None
            if schema_fields is not None:
                _json_with_form(path, ctx, parsed, pretty, schema_fields, form_default=True)
                return
            ui.label('Schema present but not a usable flat-object schema; editing raw.') \
                .classes('text-caption text-grey-6')

        inferred = _infer_flat_fields(parsed)
        if inferred is None:
            _json_raw_editor(path, ctx, pretty)
            return
        _json_with_form(path, ctx, parsed, pretty, inferred, form_default=False)

    detail()


def _render_text_editor(path: Path, ctx: _Ctx) -> None:
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return

    editor = (
        ui.codemirror(value=content, language=_codemirror_language(path), line_wrapping=True)
        .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
    )

    def _save() -> None:
        # Text is saved verbatim (no reformatting, unlike JSON).
        if _atomic_write_text(path, editor.value):
            ui.notify(f'Saved {path.name}', type='positive')
            _maybe_publish(path, ctx)

    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button('Save', on_click=_save).props('color=primary')


def _render_image_preview(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return
    mime = _IMAGE_MIME.get(path.suffix.lower(), 'application/octet-stream')
    b64 = base64.b64encode(data).decode('ascii')
    ui.image(f'data:{mime};base64,{b64}').classes('w-full') \
        .style('max-height: 70vh; object-fit: contain')


def _render_download_only(path: Path, reason: str) -> None:
    with ui.column().classes('items-start gap-2 q-mt-sm'):
        ui.label(reason).classes('text-body2 text-grey-7')
        ui.button('Download', icon='download',
                  on_click=lambda: _download_file(path)).props('outline')


def _file_detail(dir_path: Path, key: str, ctx: _Ctx,
                 schema_fallback_dir: Path | None = None) -> None:
    """render_detail body for one file, dispatched on type and size."""
    path = dir_path / key
    if not path.is_file():
        ui.label(f'{key!r} not found.').classes('text-negative')
        return
    ext = path.suffix.lower()
    size = path.stat().st_size
    if ext == '.json':
        _render_json_detail(path, ctx, schema_fallback_dir)
    elif ext in _IMAGE_MIME:
        if size <= _MAX_IMAGE_SIZE:
            _render_image_preview(path)
        else:
            _render_download_only(path, f'Image too large to preview ({size / 1024 / 1024:.1f} MB).')
    elif ext in _TEXT_EXTENSIONS:
        if size <= _MAX_VIEWER_SIZE:
            _render_text_editor(path, ctx)
        else:
            _render_download_only(path, f'File too large to edit ({size / 1024:.0f} KB).')
    else:
        _render_download_only(path, 'Binary file — download to view.')


# ---------------------------------------------------------------------------
# List view (render_list_item) — one row
# ---------------------------------------------------------------------------

def _file_list_row(dir_path: Path, key: str, item: FileEntry, select: Callable[[], None],
                   ctx: _Ctx, refresh: Callable[[], None], state: dict) -> None:
    path = dir_path / key
    ext = path.suffix.lower()
    is_json = ext == '.json'
    is_image = ext in _IMAGE_MIME
    is_text = ext in _TEXT_EXTENSIONS
    icon = ('data_object' if is_json else 'image' if is_image
            else 'article' if is_text else 'insert_drive_file')
    size = item.size
    size_str = f'{size / 1024:.1f} KB' if size < 1024 * 1024 else f'{size / 1024 / 1024:.1f} MB'
    published_at = state.get(key, {}).get('published_at') if ctx.mqtt_enabled else None

    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon(icon).classes('text-grey-6 text-sm')
        with ui.column().classes('grow gap-0'):
            ui.label(key).classes('text-body2 cursor-pointer').on('click', select)
            if published_at:
                try:
                    from datetime import datetime
                    ui.label(f'Published: {render_datetime(datetime.fromisoformat(published_at))}') \
                        .classes('text-caption text-grey-6')
                except (ValueError, TypeError):
                    pass
        ui.label(size_str).classes('text-caption text-grey-7')
        ui.button(icon='chevron_right').props('flat dense size=sm').tooltip('Open').on_click(select)
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download') \
            .on_click(lambda _, p=path: _download_file(p))

        if ctx.mqtt_enabled and ctx.project_name and ctx.device_name:
            async def _publish(p=path) -> None:
                from app.core.file.backend import publish_file_now
                ok = await publish_file_now(ctx.project_name, ctx.device_name, p)
                if ok:
                    ui.notify(f'Published {p.name} to device via MQTT', type='positive')
                    refresh()
                else:
                    ui.notify('MQTT publish failed (not connected?)', type='warning')
            ui.button(icon='cloud_upload').props('flat dense size=sm') \
                .tooltip('Force publish to device via MQTT').on_click(_publish)

        async def _delete(p=path) -> None:
            if not await confirm_dialog('Delete File', f'Delete **{p.name}**? This is irreversible.',
                                        ok_label='Delete', ok_color='negative'):
                return
            try:
                p.unlink()
                ui.notify(f'Deleted {p.name}', type='positive')
                refresh()
            except OSError as e:
                ui.notify(f'Delete failed: {e}', type='negative')
        ui.button(icon='delete').props('flat dense size=sm color=negative') \
            .tooltip('Delete').on_click(_delete)


# ---------------------------------------------------------------------------
# New file / upload
# ---------------------------------------------------------------------------

async def _new_json_dialog(directory: Path, refresh: Callable[[], None], ctx: _Ctx) -> None:
    """Create a new JSON file using a CodeMirror editor."""
    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        ui.label('New JSON File').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
            filename_input = ui.input(label='Filename', placeholder='config') \
                .props('outlined dense').classes('grow')
            filename_preview = ui.label('').classes('text-caption text-grey-6 text-no-wrap')

        def _update_preview(e) -> None:
            raw = (e.value or '').strip()
            effective = raw if raw.endswith('.json') else (f'{raw}.json' if raw else '')
            filename_preview.text = f'→ {effective}' if effective else ''

        filename_input.on_value_change(_update_preview)
        editor = ui.codemirror(value='{}', language='JSON', line_wrapping=True) \
            .classes('w-full border rounded q-mt-xs').style('height: clamp(160px, 30vh, 400px)')

        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            def _create() -> None:
                raw = (filename_input.value or '').strip()
                fname = raw if raw.endswith('.json') else f'{raw}.json'
                if not fname or fname == '.json':
                    ui.notify('Please enter a filename', type='warning')
                    return
                if not is_valid_upload_filename(fname):
                    ui.notify(f'Invalid filename: {fname!r}', type='negative')
                    return
                try:
                    parsed = json.loads(editor.value)
                except json.JSONDecodeError as exc:
                    ui.notify(f'Invalid JSON: {exc}', type='negative')
                    return
                dest = directory / fname
                if dest.exists():
                    ui.notify(f'{fname} already exists — open it to edit', type='warning')
                    return
                if _atomic_write_text(dest, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'):
                    ui.notify(f'Created {fname}', type='positive')
                    dialog.close()
                    refresh()
                    _maybe_publish(dest, ctx)

            ui.button('Create', on_click=_create).props('color=primary')

    dialog.open()
    await dialog


def _make_upload_handler(directory: Path, refresh: Callable[[], None], ctx: _Ctx):
    """Return an upload handler that writes uploaded files to *directory* atomically.

    An upload can be several MB, so the blocking write/rename is pushed to a
    worker thread — the same treatment as the device-facing PUT /api/file path."""
    async def _handle(e) -> None:
        # NiceGUI 3.x: the upload event carries a FileUpload (e.file) whose read()
        # is async; the earlier e.name / e.content.read() no longer exist.
        filename = e.file.name
        if not is_valid_upload_filename(filename):
            ui.notify(f'Invalid filename: {filename!r}', type='negative')
            e.sender.reset()
            return
        dest = directory / filename
        tmp = dest.with_name(dest.name + '.tmp')
        content = await e.file.read()

        def _write() -> None:
            tmp.write_bytes(content)
            tmp.rename(dest)

        try:
            await anyio.to_thread.run_sync(_write)
            ui.notify(f'Uploaded {filename}', type='positive')
            refresh()
            _maybe_publish(dest, ctx)
        except Exception as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
            await anyio.to_thread.run_sync(lambda: tmp.unlink(missing_ok=True))
        finally:
            e.sender.reset()
    return _handle


# ---------------------------------------------------------------------------
# Card = DrillDownWrapper(list <-> detail) + an always-visible upload footer
# ---------------------------------------------------------------------------

def _files_card(dir_path: Path, *, title: str, description: str, ctx: _Ctx,
                schema_fallback_dir: Path | None = None) -> None:
    from app.core.file.backend import get_file_config
    dir_path.mkdir(parents=True, exist_ok=True)
    max_upload = get_file_config(ctx.project_name).max_upload_size

    @ui.refreshable
    def wrapper_body() -> None:
        state: dict = {}
        if ctx.mqtt_enabled and ctx.device_name:
            from app.core.file.backend import load_file_state
            state = load_file_state(ctx.project_name, ctx.device_name)
        adapter = DirectoryAdapter(dir_path, suffix=None, name_filter=is_valid_upload_filename)

        def _list_item(key: str, item: FileEntry, select: Callable[[], None]) -> None:
            _file_list_row(dir_path, key, item, select, ctx, wrapper_body.refresh, state)

        DrillDownWrapper.from_adapter(
            FileEntry, adapter,
            list_title=title,
            item_title_field='name',
            add_button=None, delete_button=None,  # our own row/footer actions instead
            render_list_item=_list_item,
            render_detail=lambda _a, key, _set: _file_detail(dir_path, key, ctx, schema_fallback_dir),
        ).render()

    ui.markdown(description).classes('text-caption q-ma-none')
    wrapper_body()

    # Upload footer lives outside the wrapper so it is reachable even when the
    # directory is empty (DrillDownWrapper skips render_list_container then).
    ui.separator().classes('q-mt-sm')
    with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
        ui.label('Upload').classes('text-caption text-grey-7')

        async def _new_json() -> None:
            await _new_json_dialog(dir_path, wrapper_body.refresh, ctx)
        ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

    ui.upload(
        on_upload=_make_upload_handler(dir_path, wrapper_body.refresh, ctx),
        max_file_size=max_upload,
        auto_upload=True,
    ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

_DEVICE_DESC = ('Files stored in the device directory. '
                'Devices can upload (PUT) and download (GET) these via the API.')
_PROJECT_DESC = ('Shared files in the project directory. '
                 'Served to devices as a fallback when no device-specific copy exists.')


async def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the device Files tab (device files + project-file fallback)."""
    from app.core.project.backend import get_project
    try:
        mqtt_enabled = get_project(project_name, check_active=False).is_mqtt_enabled
    except Exception:
        mqtt_enabled = False
    # Both cards publish to this device when MQTT is on.
    ctx = _Ctx(project_name, device_name, mqtt_enabled)
    with ui.grid().classes('grid-cols-1 lg:grid-cols-2 gap-4 w-full'):
        with ui.card().classes('w-full'):
            # Device files fall back to the project dir for their schema, mirroring
            # the data-file fallback.
            _files_card(get_device_path(project_name, device_name),
                        title='Device Files', description=_DEVICE_DESC, ctx=ctx,
                        schema_fallback_dir=get_project_dir(project_name))
        with ui.card().classes('w-full'):
            _files_card(get_project_dir(project_name),
                        title='Project Files', description=_PROJECT_DESC, ctx=ctx)


async def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab (single card, full width)."""
    with ui.card().classes('w-full'):
        _files_card(get_project_dir(project_name),
                    title='Project Files', description=_PROJECT_DESC,
                    ctx=_Ctx(project_name, None, False))
