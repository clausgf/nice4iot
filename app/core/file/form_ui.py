"""
The JSON Form tab's widgets: one `FormField` → one NiceGUI input.

The field kinds from `form.py` are translated into niceview's `FieldInfo`
vocabulary and rendered with `niceview.render_field()`, which builds the same
widget a `ModelForm` would — without a model. The untrusted schema is never
turned into a type: it produces a `FormField` whose `kind` is one of the eight
literals *we* assign, and `_WIDGETS` below is our table (see docs/concepts.md).

Schema-supplied strings reach only `label`, `description` and `options`, all of
which niceview renders as text — never markup. `props`/`classes` are ours, so a
schema cannot inject Quasar props or CSS.

Knows nothing about files: it renders fields and hands back a collector. Where
the values end up is `detail_ui.py`'s business.
"""
import datetime
from typing import Any, Callable

from nicegui import ui
from niceview import Field, FieldInfo, field_value, render_field
from niceview.fieldinfo import WidgetType

from app.core.file.form import FormField, validate_field

# kind -> (widget, Python type). The type drives field_value()'s conversions: an
# integer field reads back as int rather than float, a chips field as list[str].
_WIDGETS: dict[str, tuple[WidgetType, Any]] = {
    'string':      ('ui.input',       str),
    'textarea':    ('ui.textarea',    str),
    'date':        ('date',           str),
    'integer':     ('ui.number',      int),
    'number':      ('ui.number',      float),
    'boolean':     ('ui.switch',      bool),
    'enum':        ('ui.select',      str),
    'string_list': ('ui.input_chips', list[str]),
}


def _field_validator(field: FormField) -> Callable[[Any], str | None]:
    return lambda value: validate_field(field, value)


def to_field_info(field: FormField, *, full_width: bool = True) -> FieldInfo:
    """Translate one field of the schema subset into niceview's vocabulary.

    The single place where the subset meets the widget layer — a newly supported
    type is a row in `_WIDGETS` plus one in `schema_kind()`, not another branch.
    *full_width* is False for a field sharing a row with others (`x-ui.layout`),
    so it takes an even share of the row instead of the whole width.
    """
    widget_type, field_type = _WIDGETS[field.kind]
    props = 'outlined dense'
    if field.max_length and field.kind in ('string', 'textarea'):
        props += f' maxlength={field.max_length}'
    # niceview's Field() kwargs are typed as required even though FieldInfo's own
    # dataclass defaults every one of them to None — passing None here is valid
    # at runtime (niceview/niceview#fieldinfo), just not reflected in its stubs.
    return Field(
        label=field.label or field.key,
        widget_type=widget_type,
        field_type=field_type,
        # niceview renders a description wherever description_as says — a tooltip by
        # default, which is also the only slot a switch has. It reaches the widget as
        # text, never as markup.
        description=field.description,  # type: ignore[arg-type]
        options=[str(x) for x in field.enum] if field.enum is not None else None,  # type: ignore[arg-type]
        min=field.minimum,  # type: ignore[arg-type]
        max=field.maximum,  # type: ignore[arg-type]
        precision=0 if field.kind == 'integer' else None,  # type: ignore[arg-type]
        step=1 if field.kind == 'integer' else None,  # type: ignore[arg-type]
        required=field.required,
        # Layer 2: the same check the save path runs, shown under the widget.
        validation=_field_validator(field),
        props=props,
        classes='w-full' if full_width else 'flex-1 min-w-0',
    )


def _json_value(value: Any) -> Any:
    """Make a widget value JSON-serialisable.

    Only the date widget needs it: niceview reads it back as a `datetime.date`,
    while the subset stores an ISO-8601 string (docs/concepts.md).
    """
    return value.isoformat() if isinstance(value, datetime.date) else value


def render_form_fields(fields: list[FormField],
                       layout: list[list[str]] | None = None) -> Callable[..., dict | None]:
    """Render *fields* into the current context and return a collector.

    *layout* groups fields into rows (the schema's optional `x-ui.layout` hint,
    see `form.layout_from_schema()`) — a list of rows, each a list of field keys
    sharing one row. Keys not among *fields* are dropped and any field the
    layout misses still gets its own row, so a stale or partial hint can never
    hide or duplicate a field. None (no schema, or no hint) keeps the original
    one-field-per-row layout.

    Calling the collector reads the widgets and validates them; it returns the
    values, or None after reporting the first error — so a save handler is just
    ``if (values := collect()) is None: return``. Pass ``validate=False`` to read
    the widgets as-is, with no checks and no notification — for syncing another
    view from the current (possibly incomplete) form state.
    """
    by_key = {f.key: f for f in fields}
    seen: set[str] = set()
    rows: list[list[str]] = []
    for raw_row in (layout or []):
        row = [k for k in raw_row if k in by_key and k not in seen]
        seen.update(row)
        if row:
            rows.append(row)
    rows.extend([f.key] for f in fields if f.key not in seen)

    infos: dict[str, FieldInfo] = {}
    widgets: dict[str, Any] = {}
    with ui.column().classes('w-full gap-3'):
        if not fields:
            ui.label('Empty object — nothing to edit as a form.').classes('text-caption text-grey-7')
        for row in rows:
            if len(row) == 1:
                key = row[0]
                infos[key] = to_field_info(by_key[key])
                widgets[key] = render_field(infos[key], by_key[key].value)
                continue
            with ui.row().classes('w-full gap-3 items-start'):
                for key in row:
                    infos[key] = to_field_info(by_key[key], full_width=False)
                    widgets[key] = render_field(infos[key], by_key[key].value)

    def collect(*, validate: bool = True) -> dict | None:
        values = {key: _json_value(field_value(w, infos[key])) for key, w in widgets.items()}
        if not validate:
            return values
        for f in fields:
            if (err := validate_field(f, values[f.key])) is not None:
                ui.notify(err, type='negative')
                return None
        return values

    return collect
