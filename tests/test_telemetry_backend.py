"""
Unit tests for app.core.telemetry.backend — local JSONL store, read_series()
source selection/fallback, and the Prometheus matrix parser.
"""
import asyncio
import datetime

import pytest

import app.core.telemetry.backend as telemetry_backend
from app.core.device.backend import create_device
from app.core.device.models import Device
from app.core.project.backend import create_project
from app.core.telemetry.backend import (
    LOCAL_METRICS_MAX_LINES,
    _append_local_metrics,
    read_local_metrics,
    read_series,
)
from app.core.telemetry.models import MetricSeries
from app.core.telemetry.prometheus.backend import _parse_matrix

_NOW = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def clear_backend_cache():
    telemetry_backend.flush_telemetry_backend_cache()
    yield
    telemetry_backend.flush_telemetry_backend_cache()


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


# ---------------------------------------------------------------------------
# _parse_matrix — Prometheus/VictoriaMetrics response conversion
# ---------------------------------------------------------------------------

def test_parse_matrix_basic():
    payload = {
        'status': 'success',
        'data': {'resultType': 'matrix', 'result': [
            {'metric': {'__name__': 'proj_temp', 'device': 'dev', 'kind': 'sensors'},
             'values': [[1735732860, "22.6"], [1735732800, "22.4"]]},  # unordered on purpose
            {'metric': {'__name__': 'proj_batt', 'device': 'dev'},
             'values': [[1735732800, "3.9"], [1735732860, "NaN"]]},
        ]},
    }
    series = _parse_matrix(payload, 'proj')

    assert [(s.kind, s.metric) for s in series] == [('default', 'batt'), ('sensors', 'temp')]
    temp = series[1]
    assert [v for _, v in temp.points] == [22.4, 22.6]  # sorted ascending by ts
    assert temp.points[0][0].tzinfo is not None
    assert len(series[0].points) == 1  # NaN sample dropped


def test_parse_matrix_skips_foreign_and_empty_series():
    payload = {'data': {'result': [
        {'metric': {'__name__': 'otherproject_temp'}, 'values': [[1735732800, "1"]]},
        {'metric': {'__name__': 'proj_empty'}, 'values': [[1735732800, "NaN"]]},
    ]}}
    assert _parse_matrix(payload, 'proj') == []


def test_parse_matrix_empty_response():
    assert _parse_matrix({}, 'proj') == []


# ---------------------------------------------------------------------------
# read_series — source selection and fallback
# ---------------------------------------------------------------------------

def test_read_series_local_when_no_backend(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 1.0, "hum": 50.0}, _NOW)
    _append_local_metrics(p, d, "sensors", {"temp": 2.0}, _NOW + datetime.timedelta(minutes=1))

    series, source = asyncio.run(read_series(p, d, since=None))

    assert source == 'local'
    by_key = {(s.kind, s.metric): s for s in series}
    assert [v for _, v in by_key[('sensors', 'temp')].points] == [1.0, 2.0]
    assert ('sensors', 'hum') in by_key


def test_read_series_uses_backend_when_configured(monkeypatch, proj_dev):
    p, d = proj_dev
    expected = [MetricSeries(kind='sensors', metric='temp', points=[(_NOW, 1.0)])]

    class StubBackend:
        async def read_series(self, device_name, start, end):
            assert device_name == d
            assert start < end
            return expected

    monkeypatch.setattr(telemetry_backend, '_get_active_backend', lambda project: StubBackend())
    series, source = asyncio.run(read_series(p, d, since=None))

    assert source == 'stub'
    assert series == expected


def test_read_series_falls_back_on_backend_error(monkeypatch, proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "s", {"v": 1.0}, _NOW)

    class BrokenBackend:
        async def read_series(self, device_name, start, end):
            raise NotImplementedError("no read path")

    monkeypatch.setattr(telemetry_backend, '_get_active_backend', lambda project: BrokenBackend())
    series, source = asyncio.run(read_series(p, d, since=None))

    assert source == 'local'
    assert series[0].points[0][1] == 1.0
