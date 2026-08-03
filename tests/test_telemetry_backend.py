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
    INFO_METRIC_KEY,
    LABEL_MAX_COUNT,
    LABEL_MAX_LEN,
    LOCAL_METRICS_MAX_LINES,
    _append_local_metrics,
    flatten_metrics,
    latest_labels,
    normalize_metrics,
    observed_metrics,
    read_local_metrics,
    read_series,
    sanitize_metric_name,
    split_metrics,
    write_telemetry,
)
from app.core.telemetry.models import MetricSeries
from app.core.telemetry.prometheus.backend import PrometheusBackend
from app.core.telemetry.prometheus.models import PrometheusConfig
from app.core.telemetry.influxdb.backend import (
    InfluxLineBackend,
    _escape_measurement,
    _escape_tag,
)
from app.core.telemetry.influxdb.models import InfluxLineConfig
from app.core.telemetry.prometheus.backend import _parse_matrix, _unit_for, metric_prefix

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


# ---------------------------------------------------------------------------
# flatten_metrics — hierarchical JSON -> underscore-joined keys
# ---------------------------------------------------------------------------

def test_flatten_metrics_nested():
    assert flatten_metrics({"a": {"b": 1}}) == {"a_b": 1}


def test_flatten_metrics_deep_and_mixed():
    payload = {
        "env": {"temp": 22.4, "hum": 41},
        "battery": {"V": 3.71},
        "wifi_rssi": -67,
    }
    assert flatten_metrics(payload) == {
        "env_temp": 22.4,
        "env_hum": 41,
        "battery_V": 3.71,
        "wifi_rssi": -67,
    }


def test_flatten_metrics_multi_level():
    assert flatten_metrics({"a": {"b": {"c": 5}}}) == {"a_b_c": 5}


def test_flatten_metrics_already_flat_unchanged():
    assert flatten_metrics({"temp": 22.4, "count": 3}) == {"temp": 22.4, "count": 3}


def test_flatten_metrics_empty_nested_contributes_nothing():
    assert flatten_metrics({"a": {}, "b": 1}) == {"b": 1}


def test_flatten_metrics_preserves_non_dict_leaves():
    # Non-numeric leaves are kept here; the numeric filter runs downstream.
    assert flatten_metrics({"a": {"b": "ok"}, "c": [1, 2]}) == {"a_b": "ok", "c": [1, 2]}


def test_write_telemetry_flattens_into_local_store(proj_dev):
    p, d = proj_dev
    asyncio.run(write_telemetry(p, d, {"env": {"temp": 22.4}}, kind="sensors",
                                timestamp=_NOW))
    records = read_local_metrics(p, d)
    assert len(records) == 1
    assert records[0]["v"] == {"env_temp": 22.4}


# ---------------------------------------------------------------------------
# observed_metrics — kind -> metric names across a project's devices
# ---------------------------------------------------------------------------

def test_observed_metrics_empty_when_no_data(proj_dev):
    p, _ = proj_dev
    assert observed_metrics(p) == {}


def test_observed_metrics_groups_by_kind(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 1.0, "hum": 2.0}, _NOW)
    _append_local_metrics(p, d, "system", {"batt": 3.0}, _NOW)
    assert observed_metrics(p) == {"sensors": ["hum", "temp"], "system": ["batt"]}


def test_observed_metrics_aggregates_across_devices(projects_dir):
    create_project("multi")
    create_device(Device(name="dev1", project_name="multi"))
    create_device(Device(name="dev2", project_name="multi"))
    _append_local_metrics("multi", "dev1", "sensors", {"temp": 1.0}, _NOW)
    _append_local_metrics("multi", "dev2", "sensors", {"hum": 2.0}, _NOW)
    assert observed_metrics("multi") == {"sensors": ["hum", "temp"]}


def test_observed_metrics_unknown_project():
    assert observed_metrics("does_not_exist") == {}


# ---------------------------------------------------------------------------
# sanitize_metric_name — backend-compatible metric names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("cpu.load", "cpu_load"),
    ("cpu.load-1m", "cpu_load_1m"),
    ("temp °C", "temp__C"),
    ("a,b=c", "a_b_c"),
    ("valid_name99", "valid_name99"),
    ("", "_"),
    ("!!!", "___"),
    ("Ünïcode", "_n_code"),
])
def test_sanitize_metric_name(raw, expected):
    assert sanitize_metric_name(raw) == expected


def test_normalize_metrics_flattens_and_sanitizes():
    assert normalize_metrics({"a.b": {"c d": 1}}) == {"a_b_c_d": 1}


def test_normalize_metrics_preserves_numeric_leaves():
    payload = {"cpu.load-1m": 0.7, "net": {"rx.bytes": 1024}}
    assert normalize_metrics(payload) == {"cpu_load_1m": 0.7, "net_rx_bytes": 1024}


def test_write_telemetry_sanitizes_into_local_store(proj_dev):
    p, d = proj_dev
    asyncio.run(write_telemetry(p, d, {"cpu.load-1m": 0.7, "env": {"temp °C": 22.4}},
                                kind="sensors", timestamp=_NOW))
    records = read_local_metrics(p, d)
    assert len(records) == 1
    assert records[0]["v"] == {"cpu_load_1m": 0.7, "env_temp__C": 22.4}


# ---------------------------------------------------------------------------
# metric_prefix — Prometheus-safe project prefix (write/read consistency)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("project, expected", [
    ("myproj", "myproj"),
    ("my-proj", "my_proj"),      # hyphen invalid in Prometheus metric names
    ("my+proj", "my_proj"),      # plus invalid
    ("123proj", "_123proj"),     # must not start with a digit
    ("", "_"),                   # empty -> valid single underscore
    ("valid_9", "valid_9"),
])
def test_metric_prefix(project, expected):
    assert metric_prefix(project) == expected


@pytest.mark.parametrize("name, expected", [
    ("temperature_celsius", "celsius"),
    ("heap_free_bytes", "bytes"),
    ("uptime_seconds", "seconds"),
    ("flow_seconds_total", "seconds"),   # counter marker stripped, unit still found
    ("messages_sent_total", ""),          # no unit before _total
    ("temperature", ""),                  # bare name, no unit suffix
    ("battery_voltage", ""),              # 'voltage' is the quantity, not a base unit
    ("env_temp_celsius", "celsius"),      # works on flattened nested names too
])
def test_unit_for(name, expected):
    assert _unit_for(name) == expected


def test_parse_matrix_strips_sanitized_prefix():
    """A project with a hyphen stores metrics under the sanitized prefix; the
    parser must strip that same sanitized prefix on read."""
    payload = {'data': {'result': [
        {'metric': {'__name__': 'my_proj_temp', 'device': 'dev', 'kind': 'sensors'},
         'values': [[1735732800, "22.4"]]},
    ]}}
    series = _parse_matrix(payload, 'my-proj')
    assert [(s.kind, s.metric) for s in series] == [('sensors', 'temp')]


# ---------------------------------------------------------------------------
# InfluxDB line protocol — escaping of names/keys (defence in depth)
# ---------------------------------------------------------------------------

def test_escape_measurement():
    assert _escape_measurement("a b,c") == r"a\ b\,c"


def test_escape_tag():
    assert _escape_tag("a b,c=d") == r"a\ b\,c\=d"


def test_build_line_escapes_measurement_device_kind_and_field_keys():
    backend = InfluxLineBackend("pro j", InfluxLineConfig())
    line = backend._build_line("dev,1", {"a b": 1.0}, "ki nd", 42)
    # measurement (project) escapes space+comma; device/kind tag values escape
    # space/comma/equals; field keys escape space. No separate project tag.
    assert line == r"pro\ j,device=dev\,1,kind=ki\ nd a\ b=1.0 42"


def test_build_line_kind_is_a_tag_and_escapes_equals():
    """kind is now a tag value, so '=' in it must be escaped (unlike a measurement)."""
    backend = InfluxLineBackend("proj", InfluxLineConfig())
    line = backend._build_line("dev", {"temp": 1.0}, "ki=nd", 42)
    assert line == r"proj,device=dev,kind=ki\=nd temp=1.0 42"


def test_build_line_plain_names_unchanged():
    backend = InfluxLineBackend("proj", InfluxLineConfig())
    line = backend._build_line("dev", {"temp": 22.4}, "sensors", 42)
    assert line == "proj,device=dev,kind=sensors temp=22.4 42"


# ---------------------------------------------------------------------------
# split_metrics — numeric vs. string labels
# ---------------------------------------------------------------------------

def test_split_numeric_and_labels():
    num, lab = split_metrics({"temp": 22.4, "count": 3, "site": "hall2", "firmware_version": "1.4.0"})
    assert num == {"temp": 22.4, "count": 3}
    assert lab == {"site": "hall2", "firmware_version": "1.4.0"}


def test_split_drops_reserved_info_numeric():
    num, lab = split_metrics({INFO_METRIC_KEY: 1, "temp": 1.0})
    assert INFO_METRIC_KEY not in num
    assert num == {"temp": 1.0}


def test_split_drops_reserved_and_invalid_label_names():
    num, lab = split_metrics({"device": "x", "kind": "y", "__name__": "z", "1bad": "v", "good": "v"})
    assert lab == {"good": "v"}       # device/kind/__name__ reserved; 1bad is an invalid label name
    assert num == {}


def test_split_caps_value_length_and_trims():
    num, lab = split_metrics({"v": "  " + "x" * (LABEL_MAX_LEN + 10) + "  "})
    assert lab["v"] == "x" * LABEL_MAX_LEN


def test_split_caps_label_count():
    payload = {f"l{i}": "v" for i in range(LABEL_MAX_COUNT + 5)}
    _num, lab = split_metrics(payload)
    assert len(lab) == LABEL_MAX_COUNT


def test_split_empty_string_dropped():
    _num, lab = split_metrics({"a": "   ", "b": "x"})
    assert lab == {"b": "x"}


# ---------------------------------------------------------------------------
# labels in the local store, the Prometheus info series, the Influx info line
# ---------------------------------------------------------------------------

def test_append_stores_labels_in_l(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 22.4}, _NOW, labels={"site": "hall2"})
    rec = read_local_metrics(p, d)[0]
    assert rec["v"] == {"temp": 22.4}
    assert rec["l"] == {"site": "hall2"}


def test_append_without_labels_omits_l(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "sensors", {"temp": 1.0}, _NOW)
    assert "l" not in read_local_metrics(p, d)[0]


def test_latest_labels_last_value_wins(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "system", {"t": 1.0}, _NOW,
                          labels={"firmware_version": "1.0.0", "site": "hall1"})
    _append_local_metrics(p, d, "system", {"t": 2.0}, _NOW, labels={"firmware_version": "1.1.0"})
    assert latest_labels(p, d) == {"firmware_version": "1.1.0", "site": "hall1"}


def test_latest_labels_empty_without_any(proj_dev):
    p, d = proj_dev
    _append_local_metrics(p, d, "system", {"t": 1.0}, _NOW)
    assert latest_labels(p, d) == {}


def _series_by_name(wr):
    def _name(ts):
        return next(lbl.value for lbl in ts.labels if lbl.name == "__name__")
    return {_name(ts): ts for ts in wr.timeseries}


def _labels_of(ts):
    return {lbl.name: lbl.value for lbl in ts.labels}


def test_prometheus_emits_clean_numeric_and_info_series():
    be = PrometheusBackend("myproj", PrometheusConfig())
    wr = be._build_write_request(
        "dev1", {"temp": 22.4}, "system", 1000,
        {"firmware_version": "1.4.0", "site": "hall2"},
    )
    prefix = metric_prefix("myproj")
    series = _series_by_name(wr)
    assert f"{prefix}_temp" in series
    assert f"{prefix}_{INFO_METRIC_KEY}" in series
    # numeric series stays clean — no label churn
    num_labels = _labels_of(series[f"{prefix}_temp"])
    assert "firmware_version" not in num_labels and "site" not in num_labels
    assert num_labels["device"] == "dev1" and num_labels["kind"] == "system"
    # info series carries all labels, value 1
    info = series[f"{prefix}_{INFO_METRIC_KEY}"]
    info_labels = _labels_of(info)
    assert info_labels["firmware_version"] == "1.4.0"
    assert info_labels["site"] == "hall2"
    assert info.samples[0].value == 1


def test_prometheus_no_info_series_without_labels():
    be = PrometheusBackend("myproj", PrometheusConfig())
    wr = be._build_write_request("dev1", {"temp": 1.0}, "system", 1000, {})
    prefix = metric_prefix("myproj")
    assert f"{prefix}_{INFO_METRIC_KEY}" not in _series_by_name(wr)


def test_influx_info_line():
    be = InfluxLineBackend("myproj", InfluxLineConfig())
    line = be._build_info_line("dev1", {"firmware_version": "1.4.0", "site": "hall2"}, "system", 1234)
    assert line.startswith(f"myproj_{INFO_METRIC_KEY},")
    assert "device=dev1" in line and "kind=system" in line
    assert "firmware_version=1.4.0" in line and "site=hall2" in line
    assert line.endswith("value=1i 1234")


def test_influx_no_info_line_without_labels():
    be = InfluxLineBackend("myproj", InfluxLineConfig())
    assert be._build_info_line("dev1", {}, "system", 1) is None


def test_write_telemetry_splits_and_passes_labels_to_backend(proj_dev, monkeypatch):
    """write_telemetry sends only numerics as metrics and the string fields as labels."""
    p, d = proj_dev
    captured: dict = {}

    class _FakeBackend:
        async def write(self, device_name, values, kind, timestamp, labels=None):
            captured['values'] = values
            captured['labels'] = labels

        async def read_series(self, *a, **k):
            return []

    monkeypatch.setattr(telemetry_backend, '_get_active_backend', lambda pn: _FakeBackend())
    asyncio.run(write_telemetry(p, d, {"temp": 22.4, "site": "hall2"}, kind="sensors"))
    assert captured['values'] == {"temp": 22.4}
    assert captured['labels'] == {"site": "hall2"}
