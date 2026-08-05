# Concept: a model-free field renderer in niceview

Status: **proposal, not implemented.** Two repositories are involved — niceview
gains a small public function, nice4iot's `form_ui.py` is rewritten onto it.
Nothing here changes behaviour that a user can see.

[← Documentation index](README.md) · [File Editing & Schema-Driven Forms](file-forms.md)

---

## The problem

nice4iot renders forms in two different ways.

Everything backed by one of our own Pydantic models — device settings, project
settings, firmware source, alarms, tokens, telemetry, logging — goes through
niceview's `ModelForm`. Field types, widget choice, labels, help text, layout,
props and validation all come from the model, and every card is a handful of
lines (`app/core/file/ui.py` is fourteen).

The **JSON Form tab** cannot: the fields come from an untrusted JSON-Schema
subset, not from a class. So `app/core/file/form_ui.py` hand-rolls its
own switch over the field kinds:

```python
if field.kind == 'enum':
    w = ui.select(options, label=label, value=..., validation=validation) \
        .props('outlined dense').classes('w-full')
    return lambda: w.value
if field.kind == 'textarea':
    ...
```

This is a small copy of `ModelForm._render_widget`, and it costs us:

- **Divergence.** `.props('outlined dense').classes('w-full')` is repeated per
  branch here, while every other form in the app inherits its styling from
  niceview. When niceview's widget conventions move, this file does not.
- **Duplicated vocabulary.** `FormField` is nearly field-for-field a `FieldInfo`:

  | `FormField` | `FieldInfo` |
  |---|---|
  | `label` | `label` |
  | `description` | `help_text` |
  | `enum` | `options` |
  | `minimum` / `maximum` | `min` / `max` |
  | `max_length` | (via `props`) |
  | `required` | `required` |
  | `kind` | `widget_type` |
  | `max_items` | — no equivalent |

- **Missing widgets.** Extending the schema subset (`format: "time"`, a slider
  for a bounded integer, a colour) means writing another branch here, although
  niceview renders all of them already.

## Why not just use `ModelForm`

Because `ModelForm` needs a `type[BaseModel]`, and the only way to get one from a
schema is `pydantic.create_model()` with attacker-influenced field names and
types. `docs/file-forms.md` rules that out deliberately: a device holds a valid
token, can upload `config.schema.json`, and that file would then be shaping
classes inside an authenticated admin session. The interpreter exists to keep
that path short and auditable.

**This proposal does not change that.** The schema still never becomes a type.
What it changes is who owns the *widget*, once our own code has already decided
which widget it is.

## The proposed niceview API

One public function, plus the `FieldInfo` that already exists:

```python
def render_field(field_info: FieldInfo, value: Any = None) -> Any:
    """Render a single widget from a FieldInfo in the current NiceGUI context,
    initialised to *value*, and return it.

    The widget-building half of ModelForm.render_field() without the model:
    no Fields, no item, no adapter, no autosave — the caller reads
    widget.value itself.
    """
```

This is a refactor inside niceview, not new behaviour: `ModelForm._render_widget`
already contains the switch. It splits into

- `render_field(field_info, value)` — build the widget, apply
  `props`/`classes`/`style`/`tooltip`/`validation`, set the initial value;
- `ModelForm._render_widget` — call the above, then wire change handlers,
  validation state and item binding as it does today.

`ModelForm`'s own behaviour must not change; its existing tests are the guard.

### What niceview has to settle

1. **Value conversion.** `ModelForm` converts between item and widget in
   `_from_current_item_to_widget_value` / `_from_widget_value_to_current_item`
   (dates, timedeltas, checkbox groups). `render_field` needs the widget-facing
   direction, and callers need the reverse. Cleanest is a matching
   `field_value(widget, field_info) -> Any`, so the pair is symmetric and the
   conversions stay in one place.
2. **Composite widgets.** `checkbox_group`, `editgrid` and `modelselect` are not
   plain NiceGUI elements; `editgrid`/`modelselect` also need a repository. The
   first version can raise `ValueError` for those three and document it — the
   JSON-Schema subset asks for none of them.
3. **`widget_type` must be explicit.** `ModelForm` infers it from the Python type
   during field resolution. Without a model there is nothing to infer from, so
   `render_field` should require `field_info.widget_type` and raise otherwise.

## What changes in nice4iot

`form.py` keeps everything that decides *what* a field is — inference, the
schema subset, approval, `plan_json_view()`, `validate_field()`. Only the last
step changes: `FormField` grows a mapping to `FieldInfo` instead of `form_ui.py`
growing another `if`.

```python
# form.py — the one place that translates the subset into niceview's vocabulary
_WIDGETS = {
    'string': 'ui.input', 'textarea': 'ui.textarea', 'date': 'date',
    'integer': 'ui.number', 'number': 'ui.number', 'boolean': 'ui.switch',
    'enum': 'ui.select', 'string_list': 'ui.input_chips',
}

def to_field_info(field: FormField) -> FieldInfo:
    return Field(
        label=(field.label or field.key) + (' *' if field.required else ''),
        widget_type=_WIDGETS[field.kind],
        help_text=field.description,
        options=[str(x) for x in field.enum] if field.enum else None,
        min=field.minimum, max=field.maximum,
        precision=0 if field.kind == 'integer' else None,
        required=field.required,
        validation=lambda v, f=field: validate_field(f, v),
        props='outlined dense', classes='w-full',
    )
```

and `form_ui.py` collapses to roughly:

```python
def render_form_fields(fields: list[FormField]) -> Callable[[], dict | None]:
    widgets = {}
    with ui.column().classes('w-full gap-3'):
        for field in fields:
            widgets[field.key] = render_field(to_field_info(field), field.value)
    def collect() -> dict | None:
        values = {k: field_value(w, ...) for k, w in widgets.items()}
        ...  # unchanged: validate_field over all fields, first error wins
    return collect
```

The security properties are unchanged and worth restating, because the review
question will be exactly this:

- The schema still never reaches `create_model`; it produces a `FormField`, whose
  `kind` is one of eight literals **we** assign, and `_WIDGETS` is our table.
- Schema-supplied strings still land only in `label`, `help_text` and `options` —
  text nodes. `FieldInfo` has no field that renders markup.
- `props`/`classes`/`style` are set by us, never from the schema, so a schema
  cannot inject CSS or Quasar props.

## What it is worth

| | Now | After |
|---|---|---|
| `form_ui.py` | 100 lines, 8-branch switch | ~40 lines, one dict |
| Widget styling | repeated per branch | from niceview, like every other form |
| New widget kind | a branch here + a branch in `schema_kind` | a row in `_WIDGETS` + `schema_kind` |
| niceview | — | +1 public function, `ModelForm` refactored onto it |

So: roughly 60 lines in nice4iot, and — the actual point — the JSON form stops
being the one form in the app that ages separately from the rest.

## Order of work

1. niceview: extract `render_field` / `field_value` out of `ModelForm`, keeping
   `ModelForm`'s tests green; add tests for the model-free path.
2. niceview: release; nice4iot's `uv.lock` picks up the new commit.
3. nice4iot: add `to_field_info()` to `form.py`, rewrite `form_ui.py`,
   extend the coupling-guard test in `tests/test_file_overlay.py` to cover the new
   API (it already guards the `DirectoryAdapter` internals we override).
4. nice4iot: `tests/test_files_panels.py` renders every widget kind of the subset
   in one detail view — that test is the regression net for the swap.

Step 4 exists today, which is why this is a safe change to make later rather than
a reason to make it now.
