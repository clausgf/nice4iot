"""
The JSON Form tab's widgets: one `FormField` → one NiceGUI input.

A deliberately small interpreter over the field kinds from `form.py` — a
fixed switch, not schema-derived types fed into `pydantic.create_model` or
niceview's ModelForm. That keeps the untrusted-input path short and auditable
(see docs/file-forms.md); niceview's ModelForm stays reserved for our own
code-defined models.

Only text ever reaches a text-rendering widget (labels, options, help lines) —
schema-supplied strings never go to ui.markdown/ui.html, so a schema cannot
inject markup.

Knows nothing about files: it renders fields and hands back a collector. Where
the values end up is `detail_ui.py`'s business.
"""
from typing import Any, Callable

from nicegui import ui

from app.core.file.form import FormField, validate_field

# Widgets that carry NiceGUI's own validation (a ValidationElement) show the
# message inline, under the field. The rest — switch, textarea — are validated on
# save only. Either way the save-time check stays authoritative: inline errors
# inform, they do not block.
_VALIDATES_INLINE = {'string', 'date', 'integer', 'number', 'enum', 'string_list'}


def _render_widget(field: FormField, label: str) -> Callable[[], Any]:
    """Render the input widget for *field*; return a getter for its value."""
    validation = ((lambda v: validate_field(field, v))
                  if field.kind in _VALIDATES_INLINE else None)

    if field.kind == 'boolean':
        w = ui.switch(label, value=bool(field.value))
        return lambda: bool(w.value)
    if field.kind == 'enum':
        options = [str(x) for x in (field.enum or [])]
        w = ui.select(options, label=label, value=field.value if field.value in options else None,
                      validation=validation).props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'textarea':
        w = ui.textarea(label, value=field.value or '').props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'date':
        w = ui.input(label, value=field.value or '', validation=validation) \
            .props('outlined dense type=date').classes('w-full')
        return lambda: w.value or None
    if field.kind == 'integer':
        w = ui.number(label, value=field.value, precision=0, step=1, min=field.minimum,
                      max=field.maximum, validation=validation).props('outlined dense').classes('w-full')
        return lambda: int(w.value) if w.value is not None else None
    if field.kind == 'number':
        w = ui.number(label, value=field.value, min=field.minimum, max=field.maximum,
                      validation=validation).props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'string_list':
        w = ui.input_chips(label, value=list(field.value or []), validation=validation) \
            .props('outlined dense').classes('w-full')
        return lambda: list(w.value or [])
    w = ui.input(label, value=field.value or '', validation=validation) \
        .props('outlined dense').classes('w-full')
    if field.max_length:
        w.props(f'maxlength={field.max_length}')
    return lambda: w.value


def _render_field(field: FormField) -> Callable[[], Any]:
    label = (field.label or field.key) + (' *' if field.required else '')
    with ui.column().classes('w-full gap-0'):
        getter = _render_widget(field, label)
        if field.description:
            ui.label(field.description).classes('text-caption text-grey-7')
    return getter


def render_form_fields(fields: list[FormField]) -> Callable[[], dict | None]:
    """Render *fields* into the current context and return a collector.

    Calling the collector reads the widgets and validates them; it returns the
    values, or None after reporting the first error — so a save handler is just
    ``if (values := collect()) is None: return``.
    """
    getters: dict[str, Callable[[], Any]] = {}
    with ui.column().classes('w-full gap-3'):
        if not fields:
            ui.label('Empty object — nothing to edit as a form.').classes('text-caption text-grey-7')
        for field in fields:
            getters[field.key] = _render_field(field)

    def collect() -> dict | None:
        values = {f.key: getters[f.key]() for f in fields}
        for f in fields:
            if (err := validate_field(f, values[f.key])) is not None:
                ui.notify(err, type='negative')
                return None
        return values

    return collect
