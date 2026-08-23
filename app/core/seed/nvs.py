"""Builds an ESP-IDF NVS partition image from an EffectiveSeed, matching
arduino4iot's stable NVS schema (namespace "iot"; see
docs/concepts.md#nvs-schema-stable-interface in the arduino4iot repo, and its
examples/nvs_seed_template.csv). Shells out to esp_idf_nvs_partition_gen
rather than reimplementing ESP-IDF's NVS binary format in-process.

cliCert/cliKey (mutual-TLS client credentials) are part of arduino4iot's
schema but not of SeedSettings — out of scope here.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.seed.backend import EffectiveSeed

# IotTlsMode (arduino4iot include/iot_seed.h): 0=None 1=Bundle 2=Insecure 3=CaPin.
# SeedSettings only ever exposes 'public' (Bundle) or 'custom' (CaPin) — "Insecure"
# is intentionally not offered by the admin UI.
_TLS_MODE_CODE = {'public': 1, 'custom': 3}


class NvsGenerationError(Exception):
    """The NVS partition image could not be generated."""


def _seed_csv_rows(seed: EffectiveSeed) -> list[list[str]]:
    """CSV rows for nvs_partition_gen, in the "iot" namespace. A key is left
    out entirely (not written empty) when its value is absent — an empty but
    *present* key would block arduino4iot's own seedCredentials() from ever
    filling it in later (see the NVS schema doc)."""
    rows = [['key', 'type', 'encoding', 'value'], ['iot', 'namespace', '', '']]
    if seed.wifi_ssid:
        rows.append(['wifiSsid', 'data', 'string', seed.wifi_ssid])
    if seed.wifi_password:
        rows.append(['wifiPass', 'data', 'string', seed.wifi_password])
    if seed.api_url:
        rows.append(['apiUrl', 'data', 'string', seed.api_url])
    if seed.project_name:
        rows.append(['project', 'data', 'string', seed.project_name])
    if seed.provisioning_token:
        rows.append(['provToken', 'data', 'string', seed.provisioning_token])
    # TLS trust only matters for an https:// API URL; the on-device AP form
    # deliberately never touches it either (see docs/concepts.md).
    if seed.api_url.startswith('https://'):
        rows.append(['tlsMode', 'data', 'u8', str(_TLS_MODE_CODE.get(seed.tls_mode, 1))])
        if seed.tls_mode == 'custom' and seed.ca_cert:
            rows.append(['caCert', 'data', 'string', seed.ca_cert])
    return rows


def build_nvs_image(seed: EffectiveSeed, size: int) -> bytes:
    """Generate the NVS partition binary for `seed`, exactly `size` bytes
    (must match the target board's nvs partition size — see app.core.seed.boards).

    Synchronous/blocking (subprocess + file IO) — callers in async context
    must wrap this with anyio.to_thread.run_sync, per the async IO rule.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / 'seed.csv'
        out_path = tmp_path / 'seed.bin'
        with csv_path.open('w', newline='') as f:
            csv.writer(f).writerows(_seed_csv_rows(seed))
        result = subprocess.run(
            [sys.executable, '-m', 'esp_idf_nvs_partition_gen', 'generate',
             str(csv_path), str(out_path), hex(size), '--version', '2'],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not out_path.is_file():
            raise NvsGenerationError(
                f'nvs_partition_gen failed (exit {result.returncode}): '
                f'{result.stderr.strip() or result.stdout.strip()}'
            )
        return out_path.read_bytes()
