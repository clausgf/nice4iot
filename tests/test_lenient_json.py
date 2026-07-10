"""
Acceptance tests for lenient JSON loading (app/util_json.py).

Validates that all entry points tolerate hand-edited JSON files:
- Malformed JSON  → log + return default
- Unknown fields  → log + ignore
- Bad field value → log + use model default (does not affect other fields)
- One bad item in a list → log + skip that item, keep the rest
"""
import json
import pytest
from pathlib import Path
from pydantic import BaseModel, Field

from niceview.dataadapter import JsonAdapter, lenient_model_load, lenient_list_load


# ---------------------------------------------------------------------------
# Minimal models for isolated unit tests
# ---------------------------------------------------------------------------

class Simple(BaseModel):
    name: str = 'default_name'
    count: int = 0
    ratio: float = 1.0
    tag: str = 'none'


class WithRequired(BaseModel):
    """Model with a field that has no default — triggers the 'last resort' path."""
    required_id: str  # no default
    optional_label: str = 'ok'


# ===========================================================================
# lenient_model_load
# ===========================================================================

class TestLenientModelLoad:

    def test_valid_json_loads_normally(self):
        obj = lenient_model_load(Simple, '{"name": "hello", "count": 5}')
        assert obj.name == 'hello'
        assert obj.count == 5
        assert obj.ratio == 1.0  # default

    def test_malformed_json_returns_default(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(Simple, '{not valid json}', context='test.json')
        assert obj == Simple()
        assert 'JSON parse error' in caplog.text
        assert 'test.json' in caplog.text

    def test_not_an_object_returns_default(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(Simple, '[1, 2, 3]', context='test.json')
        assert obj == Simple()
        assert 'JSON object' in caplog.text

    def test_unknown_field_is_logged_and_ignored(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(
                Simple,
                '{"name": "hi", "unknown_key": "x", "another_unknown": 99}',
                context='cfg.json',
            )
        assert obj.name == 'hi'
        assert not hasattr(obj, 'unknown_key')
        assert 'unknown_key' in caplog.text
        assert 'another_unknown' in caplog.text

    def test_bad_field_value_uses_default_for_that_field(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(
                Simple,
                '{"name": "ok", "count": "not_an_int"}',
                context='cfg.json',
            )
        assert obj.name == 'ok'          # correct field unaffected
        assert obj.count == 0            # default used for bad field
        assert 'count' in caplog.text

    def test_multiple_bad_fields_each_use_default(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(
                Simple,
                '{"count": "bad", "ratio": "bad", "tag": "fine"}',
                context='multi.json',
            )
        assert obj.count == 0    # default
        assert obj.ratio == 1.0  # default
        assert obj.tag == 'fine' # correct value preserved

    def test_bad_field_does_not_affect_other_fields(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(
                Simple,
                '{"name": "preserved", "count": "bad_value", "tag": "also_preserved"}',
            )
        assert obj.name == 'preserved'
        assert obj.tag == 'also_preserved'
        assert obj.count == 0  # default, not crashing

    def test_all_valid_fields_no_log(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = lenient_model_load(Simple, '{"name": "clean", "count": 7}')
        assert obj.name == 'clean'
        assert caplog.text == ''

    def test_empty_object_uses_all_defaults(self):
        obj = lenient_model_load(Simple, '{}')
        assert obj == Simple()

    def test_required_field_present_loads_ok(self):
        obj = lenient_model_load(WithRequired, '{"required_id": "abc"}')
        assert obj.required_id == 'abc'
        assert obj.optional_label == 'ok'

    def test_required_field_missing_raises(self):
        """Missing required field with no default is the 'last resort' — must raise."""
        with pytest.raises(Exception):
            lenient_model_load(WithRequired, '{"optional_label": "hi"}')

    def test_context_appears_in_log_messages(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            lenient_model_load(Simple, 'BROKEN', context='/data/project/.project.json')
        assert '/data/project/.project.json' in caplog.text


# ===========================================================================
# lenient_list_load
# ===========================================================================

class TestLenientListLoad:

    def test_valid_list_loads_all_items(self):
        data = json.dumps([{'name': 'a', 'count': 1}, {'name': 'b', 'count': 2}])
        result = lenient_list_load(Simple, data)
        assert len(result) == 2
        assert result[0].name == 'a'
        assert result[1].count == 2

    def test_malformed_json_returns_empty_list(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            result = lenient_list_load(Simple, '{not list}', context='tokens.json')
        assert result == []
        assert 'JSON parse error' in caplog.text

    def test_not_an_array_returns_empty_list(self, caplog):
        import logging
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            result = lenient_list_load(Simple, '{"a": 1}', context='tokens.json')
        assert result == []
        assert 'JSON array' in caplog.text

    def test_one_bad_item_skipped_rest_kept(self, caplog):
        import logging
        data = json.dumps([
            {'name': 'good1'},
            {'count': 'not_an_int'},  # bad — uses default for count, but keeps item
            {'name': 'good2'},
        ])
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            result = lenient_list_load(Simple, data, context='list.json')
        # 'count: not_an_int' is lenient-recoverable → item survives with count=0
        assert len(result) == 3
        assert result[1].count == 0   # default
        assert result[0].name == 'good1'
        assert result[2].name == 'good2'

    def test_unrecoverable_item_skipped(self, caplog):
        import logging
        data = json.dumps([
            {'required_id': 'ok'},
            {'optional_label': 'no_required_field'},  # no required_id → skipped
            {'required_id': 'also_ok'},
        ])
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            result = lenient_list_load(WithRequired, data, context='list.json')
        assert len(result) == 2
        assert result[0].required_id == 'ok'
        assert result[1].required_id == 'also_ok'
        assert 'Skipping item' in caplog.text

    def test_empty_list_returns_empty(self):
        result = lenient_list_load(Simple, '[]')
        assert result == []

    def test_unknown_fields_in_list_items_logged_and_ignored(self, caplog):
        import logging
        data = json.dumps([{'name': 'x', 'unknown_field': 'drop_me'}])
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            result = lenient_list_load(Simple, data)
        assert len(result) == 1
        assert result[0].name == 'x'
        assert 'unknown_field' in caplog.text


# ===========================================================================
# JsonAdapter (integration)
# ===========================================================================

class TestJsonAdapter:

    def test_reads_valid_file(self, tmp_path):
        f = tmp_path / 'cfg.json'
        f.write_text('{"name": "hello", "count": 3}')
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        obj = adapter.read()
        assert obj.name == 'hello'
        assert obj.count == 3

    def test_malformed_file_returns_default(self, tmp_path, caplog):
        import logging
        f = tmp_path / 'cfg.json'
        f.write_text('{broken json')
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = adapter.read()
        assert obj == Simple()
        assert 'JSON parse error' in caplog.text

    def test_missing_file_returns_default(self, tmp_path, caplog):
        import logging
        f = tmp_path / 'does_not_exist.json'
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = adapter.read()
        assert obj == Simple()
        assert 'Cannot read' in caplog.text

    def test_unknown_field_logged_and_ignored(self, tmp_path, caplog):
        import logging
        f = tmp_path / 'cfg.json'
        f.write_text('{"name": "x", "obsolete_field": 99}')
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = adapter.read()
        assert obj.name == 'x'
        assert 'obsolete_field' in caplog.text

    def test_bad_field_uses_default(self, tmp_path, caplog):
        import logging
        f = tmp_path / 'cfg.json'
        f.write_text('{"name": "ok", "count": "bad"}')
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        with caplog.at_level(logging.ERROR, logger='uvicorn'):
            obj = adapter.read()
        assert obj.name == 'ok'
        assert obj.count == 0

    def test_save_and_read_roundtrip(self, tmp_path):
        f = tmp_path / 'cfg.json'
        adapter = JsonAdapter(Simple, f, create_if_not_exist=False)
        obj = Simple(name='saved', count=42)
        adapter.save(obj)
        loaded = adapter.read()
        assert loaded.name == 'saved'
        assert loaded.count == 42

    def test_create_if_not_exist_writes_defaults(self, tmp_path):
        f = tmp_path / 'new.json'
        assert not f.exists()
        JsonAdapter(Simple, f, create_if_not_exist=True)
        assert f.exists()
        obj = JsonAdapter(Simple, f, create_if_not_exist=False).read()
        assert obj == Simple()
