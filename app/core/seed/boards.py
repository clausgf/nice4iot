"""Board registry for Web-Serial-Flash: chip family (for the ESP Web Tools
manifest) and the asset-name convention for esp32paper's per-board release
files, per board.

Flash offsets are deliberately NOT stored here — an earlier version hardcoded
them from this machine's PlatformIO toolchain, but that goes stale silently
the moment esp32paper's partition scheme or toolchain pin changes. Instead,
`app.core.seed.action_dialogs.web_serial_flash_dialog` flashes esp32paper's
published `merged-<board>.bin` (bootloader + partition table + boot_app0 +
app, already merged by esp32paper's CI at the real offsets its own build
used — see esp32paper/.github/workflows/build.yml) at offset 0, and reads the
NVS offset/size out of the published `partitions-<board>.csv` for that same
build (app.core.seed.partition_table.find_partition) — so the numbers always
come from the actual release being flashed, never a hand-maintained copy.

Board ids match arduino4iot's IOT_BOARD_ID (see esp32paper/platformio.ini's
`-DIOT_BOARD_ID=...` per env) — the same string esp32paper's release assets
are suffixed with (`firmware-<id>.bin`, `merged-<id>.bin`, `partitions-<id>.csv`)
and that a device reports as its own "board_id" telemetry. This is why it is
`waveshare_esp32_driver` below, not `esp32dev` (that's the *PlatformIO board*,
a different identifier esp32paper never publishes assets under).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Board:
    id: str            # arduino4iot IOT_BOARD_ID / esp32paper's release asset {board} suffix
    label: str
    chip_family: str   # ESP Web Tools manifest "chipFamily" (esphome/esp-web-tools README)

    @property
    def merged_asset_name(self) -> str:
        """Bootloader+partition-table+boot_app0+app, merged at their real
        offsets by esp32paper's CI — flashed as one part at offset 0."""
        return f'merged-{self.id}.bin'

    @property
    def partitions_asset_name(self) -> str:
        """That same build's partition table, as CSV — parsed for the real
        nvs offset/size (app.core.seed.partition_table.find_partition)."""
        return f'partitions-{self.id}.csv'


BOARDS: dict[str, Board] = {
    'waveshare_esp32_driver': Board(
        id='waveshare_esp32_driver',
        label='Waveshare ESP32 e-Paper Driver Board (ESP32-WROOM-32)',
        chip_family='ESP32',
    ),
    'seeed_xiao_esp32s3': Board(
        id='seeed_xiao_esp32s3',
        label='Seeed XIAO ESP32-S3 (EE04 ePaper board)',
        chip_family='ESP32-S3',
    ),
}
