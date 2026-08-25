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


def to_field_info(field: FormField) -> FieldInfo:
    """Translate one field of the schema subset into niceview's vocabulary.

    The single place where the subset meets the widget layer — a newly supported
    type is a row in `_WIDGETS` plus one in `schema_kind()`, not another branch.
    """
    widget_type, field_type = _WIDGETS[field.kind]
    props = 'outlined dense'
    if field.max_length and field.kind in ('string', 'textarea'):
        props += f' maxlength={field.max_length}'
    return Field(
        label=field.label or field.key,
        widget_type=widget_type,
        field_type=field_type,
        # niceview renders a description wherever description_as says — a tooltip by
        # default, which is also the only slot a switch has. It reaches the widget as
        # text, never as markup.
        description=field.description,
        options=[str(x) for x in field.enum] if field.enum is not None else None,
        min=field.minimum,
        max=field.maximum,
        precision=0 if field.kind == 'integer' else None,
        step=1 if field.kind == 'integer' else None,
        required=field.required,
        # Layer 2: the same check the save path runs, shown under the widget.
        validation=lambda value, f=field: validate_field(f, value),
        props=props,
        classes='w-full',
    )


def _json_value(value: Any) -> Any:
    """Make a widget value JSON-serialisable.

    Only the date widget needs it: niceview reads it back as a `datetime.date`,
    while the subset stores an ISO-8601 string (docs/concepts.md).
    """
    return value.isoformat() if isinstance(value, datetime.date) else value


def render_form_fields(fields: list[FormField]) -> Callable[..., dict | None]:
    """Render *fields* into the current context and return a collector.

    Calling the collector reads the widgets and validates them; it returns the
    values, or None after reporting the first error — so a save handler is just
    ``if (values := collect()) is None: return``. Pass ``validate=False`` to read
    the widgets as-is, with no checks and no notification — for syncing another
    view from the current (possibly incomplete) form state.
    """
    infos = {f.key: to_field_info(f) for f in fields}
    with ui.column().classes('w-full gap-3'):
        if not fields:
            ui.label('Empty object — nothing to edit as a form.').classes('text-caption text-grey-7')
        widgets = {f.key: render_field(infos[f.key], f.value) for f in fields}

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
