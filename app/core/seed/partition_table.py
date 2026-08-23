"""Parses an ESP-IDF partition table CSV — the same format `gen_esp32part.py`
reads and writes, and what esp32paper's release workflow now publishes as
`partitions-<board>.csv` alongside `merged-<board>.bin` — to find a
partition's real offset and size at flash time, instead of hardcoding them in
`app.core.seed.boards` (which goes stale the moment the toolchain's partition
scheme changes, silently).

Columns: ``# Name, Type, SubType, Offset, Size, Flags``. Offset is always
hex (``0x...``); size may print as a K/M-suffixed value (e.g. ``20K`` for
0x5000) instead of hex — `gen_esp32part.py`'s own `to_csv()` does this
whenever the value divides evenly, so both forms must be accepted.
"""
import csv
import io


class PartitionTableError(Exception):
    """The partition table CSV could not be parsed, or lacks the requested partition."""


def _parse_int(value: str) -> int:
    value = value.strip()
    for suffix, multiplier in (('k', 1024), ('m', 1024 * 1024)):
        if value.lower().endswith(suffix):
            return _parse_int(value[:-1]) * multiplier
    return int(value, 0)


def find_partition(csv_text: str, name: str) -> tuple[int, int]:
    """Return (offset, size) in bytes for the partition named `name`.

    Raises PartitionTableError if the CSV is malformed or has no such partition.
    """
    reader = csv.reader(io.StringIO(csv_text), skipinitialspace=True)
    for row in reader:
        if not row or not row[0].strip() or row[0].lstrip().startswith('#'):
            continue
        row = [cell.strip() for cell in row]
        if len(row) < 5:
            continue
        if row[0] != name:
            continue
        try:
            return _parse_int(row[3]), _parse_int(row[4])
        except ValueError as e:
            raise PartitionTableError(f'invalid offset/size for partition {name!r}: {e}') from e
    raise PartitionTableError(f'partition {name!r} not found in partition table')
