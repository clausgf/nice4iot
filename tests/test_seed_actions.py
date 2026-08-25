"""Unit tests for the device-seeding action pieces: the effective-seed
resolver, NVS image generation, the ESP Web Tools manifest, and the AP+QR
deep link — everything action_dialogs.py's UI wires together."""
import base64
import json

import pytest

from app.core.seed.ap_setup import build_ap_setup_url, qr_png_data_uri
from app.core.seed.backend import (
    EffectiveSeed, get_effective_seed, get_device_seed_override_adapter, get_seed_adapter,
)
from app.core.seed.boards import BOARDS
from app.core.seed.manifest import build_manifest, manifest_data_uri
from app.core.seed.nvs import NvsGenerationError, _seed_csv_rows, build_nvs_image


# ---------------------------------------------------------------------------
# effective seed resolver
# ---------------------------------------------------------------------------

def _make_project_device_dirs(tmp_path):
    project_dir = tmp_path / 'projects' / 'p'
    device_dir = project_dir / 'd'
    device_dir.mkdir(parents=True)
    return project_dir, device_dir


def test_get_effective_seed_without_override(tmp_path, monkeypatch):
    project_dir, device_dir = _make_project_device_dirs(tmp_path)
    monkeypatch.setattr('app.core.seed.backend.project_dir', lambda name: project_dir)
    monkeypatch.setattr('app.core.seed.backend.device_dir', lambda pname, dname: device_dir)

    src = get_seed_adapter(project_dir).read()
    src.wifi_ssid = 'project-net'
    src.wifi_password = 'project-pw'
    src.api_url = 'https://iot.example.com'
    src.tls_mode = 'custom'
    src.ca_cert = '-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----'
    get_seed_adapter(project_dir).save(src)

    seed = get_effective_seed('p', 'd', 'tok123')
    assert seed.wifi_ssid == 'project-net'
    assert seed.wifi_password == 'project-pw'
    assert seed.api_url == 'https://iot.example.com'
    assert seed.tls_mode == 'custom'
    assert seed.project_name == 'p'
    assert seed.provisioning_token == 'tok123'


def test_get_effective_seed_with_device_override(tmp_path, monkeypatch):
    project_dir, device_dir = _make_project_device_dirs(tmp_path)
    monkeypatch.setattr('app.core.seed.backend.project_dir', lambda name: project_dir)
    monkeypatch.setattr('app.core.seed.backend.device_dir', lambda pname, dname: device_dir)

    src = get_seed_adapter(project_dir).read()
    src.wifi_ssid, src.wifi_password = 'project-net', 'project-pw'
    get_seed_adapter(project_dir).save(src)

    override = get_device_seed_override_adapter(device_dir).read()
    override.override_enabled = True
    override.wifi_ssid, override.wifi_password = 'device-net', 'device-pw'
    get_device_seed_override_adapter(device_dir).save(override)

    seed = get_effective_seed('p', 'd', 'tok')
    assert seed.wifi_ssid == 'device-net'
    assert seed.wifi_password == 'device-pw'


# ---------------------------------------------------------------------------
# NVS image generation
# ---------------------------------------------------------------------------

def _seed(**overrides) -> EffectiveSeed:
    base = dict(wifi_ssid='net', wifi_password='pw', api_url='https://api.example.com',
                tls_mode='public', ca_cert='', project_name='demo', provisioning_token='t' * 32)
    base.update(overrides)
    return EffectiveSeed(**base)


def test_seed_csv_rows_omits_empty_and_tls_for_http():
    rows = _seed_csv_rows(_seed(api_url='http://api.example.com'))
    keys = [r[0] for r in rows]
    assert 'wifiSsid' in keys and 'apiUrl' in keys
    assert 'tlsMode' not in keys and 'caCert' not in keys


def test_seed_csv_rows_includes_tls_for_https_public():
    rows = {r[0]: r for r in _seed_csv_rows(_seed(tls_mode='public'))}
    assert rows['tlsMode'][3] == '1'  # IotTlsMode::Bundle
    assert 'caCert' not in rows


def test_seed_csv_rows_includes_ca_cert_for_custom():
    rows = {r[0]: r for r in _seed_csv_rows(_seed(tls_mode='custom', ca_cert='PEM'))}
    assert rows['tlsMode'][3] == '3'  # IotTlsMode::CaPin
    assert rows['caCert'][3] == 'PEM'


def test_build_nvs_image_matches_requested_size():
    data = build_nvs_image(_seed(), 0x5000)
    assert len(data) == 0x5000


def test_build_nvs_image_too_small_raises():
    with pytest.raises(NvsGenerationError):
        build_nvs_image(_seed(ca_cert='x' * 5000, tls_mode='custom'), 0x3000)


# ---------------------------------------------------------------------------
# ESP Web Tools manifest
# ---------------------------------------------------------------------------

def test_build_manifest_structure():
    board = BOARDS['waveshare_esp32_driver']
    manifest = build_manifest(board, b'MERGEDDATA', b'NVSDATA', nvs_offset=0x9000)
    build = manifest['builds'][0]
    assert build['chipFamily'] == 'ESP32'
    parts = {p['offset']: p['path'] for p in build['parts']}
    assert 0 in parts and 0x9000 in parts  # merged image @ 0, nvs @ the parsed offset


def test_manifest_data_uri_roundtrips():
    board = BOARDS['waveshare_esp32_driver']
    uri = manifest_data_uri(board, b'MERGEDDATA', b'NVSDATA', nvs_offset=0x9000)
    assert uri.startswith('data:application/json;base64,')
    import json
    decoded = json.loads(base64.b64decode(uri.split(',', 1)[1]))
    assert decoded['builds'][0]['chipFamily'] == 'ESP32'
    offsets = {p['offset'] for p in decoded['builds'][0]['parts']}
    assert offsets == {0, 0x9000}


def test_board_asset_names_match_esp32paper_release_convention():
    board = BOARDS['waveshare_esp32_driver']
    assert board.merged_asset_name == 'merged-waveshare_esp32_driver.bin'
    assert board.partitions_asset_name == 'partitions-waveshare_esp32_driver.csv'


# ---------------------------------------------------------------------------
# AP + QR deep link
# ---------------------------------------------------------------------------

def test_build_ap_setup_url_all_params():
    url = build_ap_setup_url(_seed())
    assert url.startswith('http://192.168.4.1/?')
    assert 'wifiSsid=net' in url
    assert 'wifiPassword=pw' in url
    assert 'project=demo' in url
    assert 'provisioningToken=' in url


def test_build_ap_setup_url_omits_empty_fields():
    url = build_ap_setup_url(_seed(wifi_password='', provisioning_token=''))
    assert 'wifiPassword=' not in url
    assert 'provisioningToken=' not in url


def test_qr_png_data_uri_is_decodable():
    uri = qr_png_data_uri('http://192.168.4.1/?wifiSsid=net')
    assert uri.startswith('data:image/png;base64,')
    raw = base64.b64decode(uri.split(',', 1)[1])
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'  # PNG magic bytes


# ---------------------------------------------------------------------------
# Print — a fresh popup window, not the dialog in place (position: fixed
# dialog content prints blank in most browsers; see action_dialogs.py)
# ---------------------------------------------------------------------------

def test_print_qr_js_embeds_values_safely():
    from app.core.seed.action_dialogs import _print_qr_js

    # A title/url containing quotes and HTML-ish characters must not break out
    # of the generated JS string literals or the popup's own HTML.
    js = _print_qr_js('AP + Form Setup — "dev"', 'data:image/png;base64,AAAA', 'http://x/?a=1&b="</script>"')
    assert 'window.open' in js
    assert 'win.print()' in js
    assert json.dumps('AP + Form Setup — "dev"') in js
    assert json.dumps('data:image/png;base64,AAAA') in js
    assert json.dumps('http://x/?a=1&b="</script>"') in js
