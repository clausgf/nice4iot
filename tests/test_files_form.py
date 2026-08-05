"""Unit tests for the flat-JSON form inference, schema subset and approval
store (app.core.file.form)."""
import pytest

from app.core.file.form import (
    FormField,
    approve_schema,
    fields_from_schema,
    infer_flat_fields,
    infer_kind,
    is_schema_approved,
    plan_json_view,
    resolve_schema_path,
    schema_kind,
    validate_field,
)


@pytest.mark.parametrize("value,kind", [
    (True, 'boolean'),          # bool before int
    (False, 'boolean'),
    (1, 'integer'),
    (0, 'integer'),
    (1.5, 'number'),
    ('x', 'string'),
    ('', 'string'),
    (['a', 'b'], 'string_list'),
    ([], 'string_list'),
])
def test_infer_kind_representable(value, kind):
    assert infer_kind(value) == kind


@pytest.mark.parametrize("value", [
    {},              # nested object
    {'k': 1},        # nested object
    [1, 2],          # non-string list
    ['a', 1],        # mixed list
    None,            # null
])
def test_infer_kind_not_representable(value):
    assert infer_kind(value) is None


def test_infer_flat_fields_all_scalars():
    fields = infer_flat_fields({'a': 1, 'b': 'x', 'c': True, 'd': ['p', 'q'], 'e': 1.5})
    assert fields is not None
    got = {f.key: f.kind for f in fields}
    assert got == {'a': 'integer', 'b': 'string', 'c': 'boolean',
                   'd': 'string_list', 'e': 'number'}
    # order preserved
    assert [f.key for f in fields] == ['a', 'b', 'c', 'd', 'e']


@pytest.mark.parametrize("obj", [
    {'a': {'nested': 1}},   # nested object
    {'a': [1, 2]},          # non-string list
    {'a': None},            # null value
    {'ok': 1, 'bad': {}},   # one bad value poisons the whole form
])
def test_infer_flat_fields_rejects_non_flat(obj):
    assert infer_flat_fields(obj) is None


def test_infer_flat_fields_empty_object_is_empty_list():
    assert infer_flat_fields({}) == []


# ---------------------------------------------------------------------------
# Schema subset (phase 3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec,kind", [
    ({'type': 'string'}, 'string'),
    ({'type': 'string', 'enum': ['a', 'b']}, 'enum'),
    ({'type': 'string', 'format': 'date'}, 'date'),
    ({'type': 'string', 'x-multiline': True}, 'textarea'),
    ({'type': 'integer'}, 'integer'),
    ({'type': 'number'}, 'number'),
    ({'type': 'boolean'}, 'boolean'),
    ({'type': 'array', 'items': {'type': 'string'}}, 'string_list'),
    ({'type': 'array', 'items': {'type': 'number'}}, None),  # only string arrays
    ({'type': 'object'}, None),                               # nesting unsupported
    ({}, None),
])
def test_schema_kind(spec, kind):
    assert schema_kind(spec) == kind


def test_fields_from_schema_metadata_defaults_and_required():
    schema = {
        'type': 'object', 'required': ['mode'],
        'properties': {
            'interval_s': {'type': 'integer', 'minimum': 10, 'maximum': 600, 'title': 'Interval'},
            'mode': {'type': 'string', 'enum': ['eco', 'turbo'], 'description': 'Run mode'},
            'name': {'type': 'string', 'default': 'dev', 'maxLength': 20},
        },
    }
    by = {f.key: f for f in fields_from_schema(schema, {'interval_s': 30})}
    assert by['interval_s'].kind == 'integer' and by['interval_s'].value == 30
    assert by['interval_s'].minimum == 10 and by['interval_s'].maximum == 600
    assert by['interval_s'].label == 'Interval'
    assert by['mode'].kind == 'enum' and by['mode'].enum == ['eco', 'turbo']
    assert by['mode'].required and by['mode'].description == 'Run mode'
    assert by['name'].value == 'dev' and by['name'].max_length == 20  # default applied


def test_fields_from_schema_ignores_unknown_type_and_rejects_non_object():
    assert fields_from_schema({'type': 'string'}, {}) is None
    assert fields_from_schema({'type': 'object'}, {}) is None  # no properties
    fields = fields_from_schema(
        {'type': 'object', 'properties': {'a': {'type': 'string'}, 'b': {'type': 'weird'}}}, {})
    assert [f.key for f in fields] == ['a']  # unknown-type 'b' ignored


def test_validate_field():
    assert validate_field(FormField('x', 'string', None, required=True), '') is not None
    assert validate_field(FormField('x', 'string', None, required=True), 'ok') is None
    num = FormField('n', 'integer', 0, minimum=10, maximum=20)
    assert validate_field(num, 5) is not None
    assert validate_field(num, 25) is not None
    assert validate_field(num, 15) is None
    en = FormField('e', 'enum', None, enum=['a', 'b'])
    assert validate_field(en, 'c') is not None
    assert validate_field(en, 'a') is None
    ln = FormField('s', 'string', '', max_length=3)
    assert validate_field(ln, 'abcd') is not None
    assert validate_field(ln, 'abc') is None


def test_resolve_schema_path(tmp_path):
    dev = tmp_path / 'dev'
    proj = tmp_path / 'proj'
    dev.mkdir()
    proj.mkdir()
    data = dev / 'config.json'
    data.write_text('{}')
    assert resolve_schema_path(data, proj) is None
    (proj / 'config.schema.json').write_text('{}')
    assert resolve_schema_path(data, proj) == proj / 'config.schema.json'   # fallback
    (dev / 'config.schema.json').write_text('{}')
    assert resolve_schema_path(data, proj) == dev / 'config.schema.json'    # device wins
    assert resolve_schema_path(dev / 'config.schema.json', proj) is None    # a schema has no schema
    assert resolve_schema_path(dev / 'notes.txt', proj) is None             # non-json


def test_schema_approval_is_hash_bound(projects_dir):
    from app.core.project.backend import create_project
    from app.paths import project_dir
    create_project('proj')
    schema = project_dir('proj') / 'config.schema.json'
    schema.write_text('{"type":"object","properties":{}}')
    assert is_schema_approved(schema, 'proj') is False
    approve_schema(schema, 'proj')
    assert is_schema_approved(schema, 'proj') is True
    # a device edit changes the content hash -> approval is revoked automatically
    schema.write_text('{"type":"object","properties":{"a":{"type":"string"}}}')
    assert is_schema_approved(schema, 'proj') is False


# ---------------------------------------------------------------------------
# View plan — the decision table from docs/file-forms.md
# ---------------------------------------------------------------------------

@pytest.fixture
def proj(projects_dir):
    """A project directory, so schema approval has somewhere to store its hashes."""
    from app.core.project.backend import create_project
    from app.paths import project_dir
    create_project('proj')
    return project_dir('proj')


def _write(path, text):
    path.write_text(text, encoding='utf-8')
    return path


def test_plan_flat_json_without_schema_offers_the_form_second(proj):
    view = plan_json_view(_write(proj / 'a.json', '{"n": 3, "s": "x"}'), 'proj', None)
    assert [f.key for f in view.fields] == ['n', 's']
    assert view.form_default is False          # raw stays the default without a schema
    assert view.data == {'n': 3, 's': 'x'}
    assert view.pending_schema is None and view.note is None


@pytest.mark.parametrize("content", [
    '{"nested": {"a": 1}}',   # not a flat object
    '{"a": null}',            # null is not representable as a widget
])
def test_plan_non_flat_json_is_raw_only(proj, content):
    view = plan_json_view(_write(proj / 'a.json', content), 'proj', None)
    assert view.fields is None


def test_plan_invalid_json_keeps_the_text_for_the_raw_editor(proj):
    view = plan_json_view(_write(proj / 'a.json', '{broken'), 'proj', None)
    assert view.fields is None
    assert view.text == '{broken'              # shown verbatim, not swallowed
    assert view.data == {}


def test_plan_toplevel_array_is_raw_only(proj):
    view = plan_json_view(_write(proj / 'a.json', '[1, 2]'), 'proj', None)
    assert view.fields is None and view.data == {}


def test_plan_approved_schema_drives_the_form_and_makes_it_default(proj):
    _write(proj / 'a.json', '{"mode": "eco"}')
    schema = _write(proj / 'a.schema.json',
                    '{"type":"object","properties":{"mode":{"type":"string","enum":["eco","turbo"]}}}')
    approve_schema(schema, 'proj')
    view = plan_json_view(proj / 'a.json', 'proj', None)
    assert [f.kind for f in view.fields] == ['enum']
    assert view.form_default is True
    assert view.pending_schema is None


def test_plan_unapproved_schema_is_inert_and_asks_for_approval(proj):
    _write(proj / 'a.json', '{"mode": "eco"}')
    schema = _write(proj / 'a.schema.json',
                    '{"type":"object","properties":{"mode":{"type":"string"}}}')
    view = plan_json_view(proj / 'a.json', 'proj', None)
    assert view.fields is None                 # no form until approved
    assert view.pending_schema == schema


def test_plan_approved_but_unusable_schema_falls_back_to_inference_with_a_note(proj):
    _write(proj / 'a.json', '{"n": 1}')
    schema = _write(proj / 'a.schema.json', '{"type":"string"}')   # not an object schema
    approve_schema(schema, 'proj')
    view = plan_json_view(proj / 'a.json', 'proj', None)
    assert [f.key for f in view.fields] == ['n']   # inferred instead
    assert view.form_default is False
    assert view.note is not None                   # and the user is told why


def test_plan_finds_the_schema_in_the_fallback_directory(proj, tmp_path):
    """A device file with no schema of its own uses the project's."""
    device = proj / 'dev'
    device.mkdir()
    _write(device / 'a.json', '{"mode": "eco"}')
    schema = _write(proj / 'a.schema.json',
                    '{"type":"object","properties":{"mode":{"type":"string"}}}')
    approve_schema(schema, 'proj')
    view = plan_json_view(device / 'a.json', 'proj', proj)
    assert view.form_default is True and [f.key for f in view.fields] == ['mode']
