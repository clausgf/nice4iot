"""
File forms — the logic behind the JSON Form tab, without any UI.

Four concerns, all synchronous and free of NiceGUI so they stay easy to test:

* **Inference** — a flat JSON object's values are mapped to field kinds, so a
  file without a schema still gets a form.
* **Schema subset** — a `<name>.schema.json` sibling describes the fields
  explicitly. Deliberately NOT a JSON Schema implementation: flat object only,
  a fixed set of types, unknown keywords ignored, and no `$ref` (SSRF) or
  `pattern` (untrusted regex, ReDoS). See docs/concepts.md.
* **Approval** — a schema is inert until its content hash is approved, so a
  device-uploaded schema cannot drive the admin's form on its own.
* **View plan** — `plan_json_view()` combines the three into the decision the
  detail view needs: Form tab or not, which tab is default, approval pending.

Rendering lives in `form_ui.py` / `detail_ui.py`; the field specs
produced here are never fed to `pydantic.create_model` or niceview, which keeps
the untrusted-input path small.
"""
import contextlib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.paths import project_dir as get_project_dir
from app.util import atomic_write

_SCHEMA_MAX_BYTES = 256 * 1024
_SCHEMA_MAX_FIELDS = 500


# ---------------------------------------------------------------------------
# Field specs
# ---------------------------------------------------------------------------

@dataclass
class FormField:
    """One form field. Inference fills key/kind/value from a flat JSON object's
    values; a schema builds the same shape and adds the metadata below
    (title/enum/min/max/…)."""
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


def infer_kind(v: Any) -> str | None:
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


def infer_flat_fields(obj: dict) -> list[FormField] | None:
    """Field specs for a flat object, or None if any value isn't representable
    (nested object, mixed/other list, null) — then no form tab is offered."""
    fields: list[FormField] = []
    for key, value in obj.items():
        kind = infer_kind(value)
        if kind is None:
            return None
        fields.append(FormField(key, kind, value))
    return fields


# ---------------------------------------------------------------------------
# Schema subset
# ---------------------------------------------------------------------------

def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _empty_for(kind: str) -> Any:
    return {'boolean': False, 'string_list': []}.get(kind, None if kind in ('integer', 'number') else '')


def schema_kind(spec: dict) -> str | None:
    t = spec.get('type')
    if t == 'string':
        if isinstance(spec.get('enum'), list) and spec['enum']:
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


def fields_from_schema(schema: dict, data: dict) -> list[FormField] | None:
    """Build form fields from the schema subset, or None if it is not a usable
    flat object schema. Values come from *data*, then the field's ``default``."""
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        return None
    props = schema.get('properties')
    if not isinstance(props, dict):
        return None
    required = set(schema.get('required') or [])
    fields: list[FormField] = []
    for name, spec in list(props.items())[:_SCHEMA_MAX_FIELDS]:
        if not isinstance(spec, dict):
            continue
        kind = schema_kind(spec)
        if kind is None:
            continue
        default = spec.get('default')
        value = data.get(name, default if default is not None else _empty_for(kind))
        fields.append(FormField(
            key=name, kind=kind, value=value,
            label=spec.get('title') if isinstance(spec.get('title'), str) else None,
            description=spec.get('description') if isinstance(spec.get('description'), str) else None,
            enum=spec.get('enum') if isinstance(spec.get('enum'), list) else None,
            minimum=_num(spec.get('minimum')), maximum=_num(spec.get('maximum')),
            max_length=_int(spec.get('maxLength')), max_items=_int(spec.get('maxItems')),
            required=name in required,
        ))
    return fields


_LAYOUT_MAX_ROWS = 100
_LAYOUT_MAX_COLS = 20


def layout_from_schema(schema: dict, fields: list[FormField]) -> list[list[str]] | None:
    """Row grouping for the Form tab from the schema's optional `x-ui.layout` hint:
    a list of rows, each a list of property keys sharing one row. Returns None if
    absent or malformed — the renderer then falls back to one field per row.

    Keys are cross-checked against *fields* (already filtered by `schema_kind()`),
    so a layout can only group fields `fields_from_schema` already decided are
    safe to render — never introduce or duplicate one. `render_form_fields()`
    still gives any field the layout misses its own row, so a field can never be
    silently dropped from the form by a stale or partial hint.
    """
    x_ui = schema.get('x-ui')
    raw_layout = x_ui.get('layout') if isinstance(x_ui, dict) else None
    if not isinstance(raw_layout, list):
        return None
    known = {f.key for f in fields}
    seen: set[str] = set()
    rows: list[list[str]] = []
    for raw_row in raw_layout[:_LAYOUT_MAX_ROWS]:
        if not isinstance(raw_row, list):
            continue
        row = [k for k in raw_row[:_LAYOUT_MAX_COLS] if isinstance(k, str) and k in known and k not in seen]
        seen.update(row)
        if row:
            rows.append(row)
    return rows or None


def resolve_schema_path(data_path: Path, fallback_dir: Path | None) -> Path | None:
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


def load_schema(schema_path: Path) -> dict | None:
    try:
        if schema_path.stat().st_size > _SCHEMA_MAX_BYTES:
            return None
        parsed = json.loads(schema_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Schema approval (device-uploaded schemas are inert until approved)
# ---------------------------------------------------------------------------

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


def is_schema_approved(schema_path: Path, project_name: str) -> bool:
    try:
        current = _file_sha256(schema_path)
    except OSError:
        return False
    return _load_approvals(project_name).get(_schema_key(schema_path, project_name)) == current


def approve_schema(schema_path: Path, project_name: str) -> None:
    """Record the schema's current content hash as approved. Called when a user
    approves an uploaded schema, or saves/edits one in the UI (admin provenance)."""
    try:
        digest = _file_sha256(schema_path)
    except OSError:
        return
    approvals = _load_approvals(project_name)
    approvals[_schema_key(schema_path, project_name)] = digest
    with contextlib.suppress(OSError):
        atomic_write(_approvals_path(project_name), json.dumps(approvals, indent=2) + '\n')


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_field(field: FormField, value: Any) -> str | None:
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


# ---------------------------------------------------------------------------
# View plan — which JSON editor a file gets
# ---------------------------------------------------------------------------

@dataclass
class JsonView:
    """What the JSON detail view shows for one file, decided without any NiceGUI.

    This is the decision table from docs/concepts.md in code: whether there is a
    Form tab at all, which tab is default, and whether a schema is waiting for
    approval. The renderer only switches on the result.
    """
    text: str                               # raw-editor content: pretty JSON, or the file verbatim
    data: dict                              # parsed object the form merges its values into
    fields: list[FormField] | None = None   # None → raw editor only, no Form tab
    form_default: bool = False              # show the Form tab first
    pending_schema: Path | None = None      # unapproved schema → approval banner, raw only
    note: str | None = None                 # one line of explanation above the editor
    layout: list[list[str]] | None = None   # schema's x-ui.layout hint, or None for one row/field


def _read_verbatim(path: Path) -> str:
    """The file as text for the raw editor, whatever is in it. Undecodable bytes
    are replaced rather than raising — the alternative is showing nothing at all."""
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def plan_json_view(path: Path, project_name: str, fallback_dir: Path | None) -> JsonView:
    """Decide how *path* should be presented, following the schema first and the
    file's own shape second.

    *fallback_dir* is where a schema sidecar is looked up when the file's own
    directory has none (device dir → project dir).
    """
    try:
        parsed = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return JsonView(text=_read_verbatim(path) if path.is_file() else '{}', data={})
    if not isinstance(parsed, dict):
        return JsonView(text=json.dumps(parsed, indent=2, ensure_ascii=False), data={})

    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    note = None

    schema_path = resolve_schema_path(path, fallback_dir)
    if schema_path is not None:
        if not is_schema_approved(schema_path, project_name):
            return JsonView(text=pretty, data=parsed, pending_schema=schema_path)
        schema = load_schema(schema_path)
        schema_fields = fields_from_schema(schema, parsed) if schema is not None else None
        if schema is not None and schema_fields is not None:
            layout = layout_from_schema(schema, schema_fields)
            return JsonView(text=pretty, data=parsed, fields=schema_fields, form_default=True, layout=layout)
        # An approved but unusable schema falls back to inference, with a note —
        # silently ignoring it would look like the schema had no effect.
        note = 'Schema present but not a usable flat-object schema; editing raw.'

    return JsonView(text=pretty, data=parsed, fields=infer_flat_fields(parsed), note=note)
