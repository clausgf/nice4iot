"""Unit tests for app.core.seed.partition_table — parses the CSV format
gen_esp32part.py actually emits (verified against a real round-trip through
the tool: CSV -> binary -> CSV, using the framework's own min_spiffs.csv /
default_8MB.csv), not a hand-guessed format."""
import pytest

from app.core.seed.partition_table import PartitionTableError, find_partition

# Real gen_esp32part.py output (python3 gen_esp32part.py <compiled-from-min_spiffs.csv>.bin),
# byte-for-byte as produced by the installed framework-arduinoespressif32 toolchain.
MIN_SPIFFS_CSV = """# ESP-IDF Partition Table
# Name, Type, SubType, Offset, Size, Flags
nvs,data,nvs,0x9000,20K,
otadata,data,ota,0xe000,8K,
app0,app,ota_0,0x10000,1920K,
app1,app,ota_1,0x1f0000,1920K,
spiffs,data,spiffs,0x3d0000,128K,
coredump,data,coredump,0x3f0000,64K,
"""

# The other CSV style this repo has seen (whitespace-padded, hex-only sizes) —
# e.g. the framework's *source* min_spiffs.csv, before a gen_esp32part.py round-trip.
PADDED_HEX_CSV = """# Name,   Type, SubType, Offset,  Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
app0,     app,  ota_0,   0x10000, 0x1E0000,
"""


def test_find_partition_k_suffixed_size():
    assert find_partition(MIN_SPIFFS_CSV, 'nvs') == (0x9000, 0x5000)


def test_find_partition_larger_offset():
    assert find_partition(MIN_SPIFFS_CSV, 'app0') == (0x10000, 1920 * 1024)


def test_find_partition_padded_hex_style():
    assert find_partition(PADDED_HEX_CSV, 'nvs') == (0x9000, 0x5000)
    assert find_partition(PADDED_HEX_CSV, 'app0') == (0x10000, 0x1E0000)


def test_find_partition_missing_raises():
    with pytest.raises(PartitionTableError):
        find_partition(MIN_SPIFFS_CSV, 'nonexistent')


def test_find_partition_empty_csv_raises():
    with pytest.raises(PartitionTableError):
        find_partition('', 'nvs')
