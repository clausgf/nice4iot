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
