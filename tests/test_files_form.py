"""Unit tests for the flat-JSON form inference, schema subset and approval
store (app.core.device.files_ui)."""
import pytest

from app.core.device.files_ui import (
    _FormField,
    _approve_schema,
    _fields_from_schema,
    _infer_flat_fields,
    _infer_kind,
    _is_schema_approved,
    _resolve_schema_path,
    _schema_kind,
    _validate_field,
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
    assert _infer_kind(value) == kind


@pytest.mark.parametrize("value", [
    {},              # nested object
    {'k': 1},        # nested object
    [1, 2],          # non-string list
    ['a', 1],        # mixed list
    None,            # null
])
def test_infer_kind_not_representable(value):
    assert _infer_kind(value) is None


def test_infer_flat_fields_all_scalars():
    fields = _infer_flat_fields({'a': 1, 'b': 'x', 'c': True, 'd': ['p', 'q'], 'e': 1.5})
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
    assert _infer_flat_fields(obj) is None


def test_infer_flat_fields_empty_object_is_empty_list():
    assert _infer_flat_fields({}) == []


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
    assert _schema_kind(spec) == kind


def test_fields_from_schema_metadata_defaults_and_required():
    schema = {
        'type': 'object', 'required': ['mode'],
        'properties': {
            'interval_s': {'type': 'integer', 'minimum': 10, 'maximum': 600, 'title': 'Interval'},
            'mode': {'type': 'string', 'enum': ['eco', 'turbo'], 'description': 'Run mode'},
            'name': {'type': 'string', 'default': 'dev', 'maxLength': 20},
        },
    }
    by = {f.key: f for f in _fields_from_schema(schema, {'interval_s': 30})}
    assert by['interval_s'].kind == 'integer' and by['interval_s'].value == 30
    assert by['interval_s'].minimum == 10 and by['interval_s'].maximum == 600
    assert by['interval_s'].label == 'Interval'
    assert by['mode'].kind == 'enum' and by['mode'].enum == ['eco', 'turbo']
    assert by['mode'].required and by['mode'].description == 'Run mode'
    assert by['name'].value == 'dev' and by['name'].max_length == 20  # default applied


def test_fields_from_schema_ignores_unknown_type_and_rejects_non_object():
    assert _fields_from_schema({'type': 'string'}, {}) is None
    assert _fields_from_schema({'type': 'object'}, {}) is None  # no properties
    fields = _fields_from_schema(
        {'type': 'object', 'properties': {'a': {'type': 'string'}, 'b': {'type': 'weird'}}}, {})
    assert [f.key for f in fields] == ['a']  # unknown-type 'b' ignored


def test_validate_field():
    assert _validate_field(_FormField('x', 'string', None, required=True), '') is not None
    assert _validate_field(_FormField('x', 'string', None, required=True), 'ok') is None
    num = _FormField('n', 'integer', 0, minimum=10, maximum=20)
    assert _validate_field(num, 5) is not None
    assert _validate_field(num, 25) is not None
    assert _validate_field(num, 15) is None
    en = _FormField('e', 'enum', None, enum=['a', 'b'])
    assert _validate_field(en, 'c') is not None
    assert _validate_field(en, 'a') is None
    ln = _FormField('s', 'string', '', max_length=3)
    assert _validate_field(ln, 'abcd') is not None
    assert _validate_field(ln, 'abc') is None


def test_resolve_schema_path(tmp_path):
    dev = tmp_path / 'dev'
    proj = tmp_path / 'proj'
    dev.mkdir()
    proj.mkdir()
    data = dev / 'config.json'
    data.write_text('{}')
    assert _resolve_schema_path(data, proj) is None
    (proj / 'config.schema.json').write_text('{}')
    assert _resolve_schema_path(data, proj) == proj / 'config.schema.json'   # fallback
    (dev / 'config.schema.json').write_text('{}')
    assert _resolve_schema_path(data, proj) == dev / 'config.schema.json'    # device wins
    assert _resolve_schema_path(dev / 'config.schema.json', proj) is None    # a schema has no schema
    assert _resolve_schema_path(dev / 'notes.txt', proj) is None             # non-json


def test_schema_approval_is_hash_bound(projects_dir):
    from app.core.project.backend import create_project
    from app.paths import project_dir
    create_project('proj')
    schema = project_dir('proj') / 'config.schema.json'
    schema.write_text('{"type":"object","properties":{}}')
    assert _is_schema_approved(schema, 'proj') is False
    _approve_schema(schema, 'proj')
    assert _is_schema_approved(schema, 'proj') is True
    # a device edit changes the content hash -> approval is revoked automatically
    schema.write_text('{"type":"object","properties":{"a":{"type":"string"}}}')
    assert _is_schema_approved(schema, 'proj') is False
