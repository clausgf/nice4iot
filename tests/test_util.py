"""Unit tests for name validation helpers in app.util.

Project and device names are restricted to valid identifiers
(is_valid_name) so that the telemetry metric name ``<project>_<field>`` is
always a valid Prometheus metric name and no backend-specific escaping is
needed. is_valid_filename stays looser (kind, forwarding, extension names).
"""
import pytest

from pydantic import ValidationError

from app.util import is_valid_filename, is_valid_name
from app.core.device.models import Device
from app.core.project.models import Project


@pytest.mark.parametrize("name", [
    "temp_sensor", "MyProj", "_staging", "dev01", "a", "A1_b2",
])
def test_is_valid_name_accepts_identifiers(name):
    assert is_valid_name(name) is True


@pytest.mark.parametrize("name", [
    "my-proj",      # hyphen
    "my+proj",      # plus
    "123proj",      # leading digit
    "temp sensor",  # space
    "temp.sensor",  # dot
    "",             # empty
    "bad!",         # punctuation
])
def test_is_valid_name_rejects_problematic(name):
    assert is_valid_name(name) is False


def test_is_valid_filename_still_allows_hyphen_and_plus():
    # kind / forwarding / extension names keep the looser rule.
    assert is_valid_filename("my-kind+1") is True
    assert is_valid_filename("123kind") is True


@pytest.mark.parametrize("bad", ["my-proj", "123proj", "my+proj"])
def test_project_model_rejects_invalid_name(bad):
    with pytest.raises(ValidationError):
        Project(name=bad)


@pytest.mark.parametrize("bad", ["e32-aabb", "1device", "dev x"])
def test_device_model_rejects_invalid_name(bad):
    with pytest.raises(ValidationError):
        Device(name=bad, project_name="proj")


# ---------------------------------------------------------------------------
# shadow_merge / atomic_write
# ---------------------------------------------------------------------------

def test_shadow_merge_own_hides_under_and_keeps_order():
    from app.util import shadow_merge
    own = ['b.json', 'a.json']
    under = ['a.json', 'c.json']
    assert shadow_merge(own, under, key=str) == ['b.json', 'a.json', 'c.json']


def test_shadow_merge_edge_cases():
    from app.util import shadow_merge
    assert shadow_merge([], ['x'], key=str) == ['x']
    assert shadow_merge(['x'], [], key=str) == ['x']
    # keyed by the callable, not by identity
    pairs_own = [('a', 1)]
    pairs_under = [('a', 2), ('b', 3)]
    assert shadow_merge(pairs_own, pairs_under, key=lambda p: p[0]) == [('a', 1), ('b', 3)]


def test_atomic_write_text_and_bytes(tmp_path):
    from app.util import atomic_write
    target = tmp_path / 'out.json'
    atomic_write(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}'
    atomic_write(target, b'\x00\x01')          # overwrites in place
    assert target.read_bytes() == b'\x00\x01'
    assert list(tmp_path.iterdir()) == [target]  # no temp file left behind


def test_atomic_write_cleans_up_and_raises_on_failure(tmp_path):
    from app.util import atomic_write
    import pytest as _pytest
    target = tmp_path / 'missing-dir' / 'out.json'
    with _pytest.raises(OSError):
        atomic_write(target, 'x')
    assert not (tmp_path / 'missing-dir').exists()


def test_atomic_write_suffix_keeps_concurrent_writers_apart(tmp_path):
    """The device upload, MQTT and UI paths pass distinct suffixes so their temp
    files cannot collide on the same target."""
    from app.util import atomic_write
    target = tmp_path / 'f.bin'
    atomic_write(target, b'a', suffix='.upload.tmp')
    assert target.read_bytes() == b'a'
    assert not (tmp_path / 'f.bin.upload.tmp').exists()
