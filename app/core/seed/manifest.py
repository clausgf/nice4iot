"""Builds an ESP Web Tools flash manifest (see app/static/esp-web-tools/README.md
and https://github.com/esphome/esp-web-tools) for Web-Serial-Flash: esp32paper's
pre-merged full-flash image (bootloader + partition table + boot_app0 + app,
already merged at their real offsets by esp32paper's CI — see
app.core.seed.boards.Board.merged_asset_name) at offset 0, plus a freshly
generated NVS image at the offset app.core.seed.partition_table.find_partition
read out of that same build's published partition table — never a hardcoded
offset.

Both parts are embedded as data: URIs rather than served from a new HTTP
endpoint: the merged image would otherwise require exposing device-bearer-token
-protected file storage to the admin browser session, and the NVS image is
generated fresh per flash from ephemeral dialog state (the chosen
provisioning token) that has no server-side home of its own. ESP Web Tools
fetches each part with `fetch()`, which resolves data: URIs, so this needs no
new API route.
"""
import base64
import json

from app.core.seed.boards import Board

MERGED_IMAGE_OFFSET = 0


def _data_uri(data: bytes) -> str:
    return 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')


def build_manifest(board: Board, merged_image: bytes, nvs_image: bytes, nvs_offset: int) -> dict:
    """ESP Web Tools manifest dict for `board`, ready for json.dumps()."""
    return {
        'name': 'nice4iot device seed',
        'version': '1',
        'builds': [
            {
                'chipFamily': board.chip_family,
                'parts': [
                    {'path': _data_uri(merged_image), 'offset': MERGED_IMAGE_OFFSET},
                    {'path': _data_uri(nvs_image), 'offset': nvs_offset},
                ],
            },
        ],
    }


def manifest_data_uri(board: Board, merged_image: bytes, nvs_image: bytes, nvs_offset: int) -> str:
    """The manifest itself as a data: URI, for <esp-web-install-button manifest=...>."""
    manifest_json = json.dumps(build_manifest(board, merged_image, nvs_image, nvs_offset))
    return 'data:application/json;base64,' + base64.b64encode(manifest_json.encode('utf-8')).decode('ascii')
