"""
Unit tests for app.core.telemetry.backend — local JSONL store.
"""
import datetime

import pytest

from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.project.backend import create_project
from app.core.telemetry.backend import (
    LOCAL_METRICS_MAX_LINES,
    _append_local_metrics,
    read_local_metrics,
)

_NOW = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def proj_dev(projects_dir):
    create_project("proj")
    create_device(Device(name="dev", project_name="proj"))
    return "proj", "dev"


# ---------------------------------------------------------------------------
# _append_local_metrics
# ---------------------------------------------------------------------------

def test_append_writes_record(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 22.4}, _NOW)
    records = read_local_metrics(p, d)
    assert len(records) == 1
    assert records[0]["kind"] == "sensors"
    assert records[0]["v"]["temp"] == 22.4


def test_append_skips_non_numeric(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"status": "ok"}, _NOW)
    assert read_local_metrics(p, d) == []


def test_append_filters_non_numeric_keeps_numeric(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 22.4, "label": "x"}, _NOW)
    records = read_local_metrics(p, d)
    assert len(records) == 1
    assert "temp" in records[0]["v"]
    assert "label" not in records[0]["v"]


def test_append_skips_when_device_dir_missing(projects_dir):
    create_project("proj2")
    # no device directory created — should silently do nothing
    _append_local_metrics("proj2", "ghost", "sensors", {"temp": 1.0}, _NOW)
    from app.paths import project_dir
    ghost_path = project_dir("proj2") / "ghost"
    assert not ghost_path.exists()


def test_append_cap_trims_oldest(proj_dev):
    p, d = proj_dev
    for i in range(LOCAL_METRICS_MAX_LINES + 10):
        ts = _NOW + datetime.timedelta(seconds=i)
        _append_local_metrics(p, d, "s", {"v": float(i)}, ts)
    records = read_local_metrics(p, d)
    assert len(records) == LOCAL_METRICS_MAX_LINES
    # oldest 10 must have been trimmed
    assert records[0]["v"]["v"] == 10.0


# ---------------------------------------------------------------------------
# read_local_metrics
# ---------------------------------------------------------------------------

def test_read_filters_by_kind(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 1.0}, _NOW)
    _append_local_metrics(p, d, "system", {"batt": 3.9}, _NOW)
    assert len(read_local_metrics(p, d, kind="sensors")) == 1
    assert len(read_local_metrics(p, d, kind="system")) == 1


def test_read_filters_by_since(proj_dev):
    p, d = proj_dev
    t1 = _NOW
    t2 = _NOW + datetime.timedelta(hours=1)
    _append_local_metrics(p, d, "s", {"v": 1.0}, t1)
    _append_local_metrics(p, d, "s", {"v": 2.0}, t2)
    records = read_local_metrics(p, d, since=t2)
    assert len(records) == 1
    assert records[0]["v"]["v"] == 2.0


def test_read_returns_empty_when_no_file(proj_dev):
    p, d = proj_dev
    assert read_local_metrics(p, d) == []
