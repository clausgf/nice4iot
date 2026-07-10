"""
Lenient JSON loading utilities.

These helpers parse JSON files with maximum tolerance:
- Malformed JSON → log.error, return model default
- Unknown fields  → log.error, ignore
- Bad field value → log.error, strip that field, retry with remaining fields
- Missing required field with no default → last resort: log.error and raise

Use LenientJsonAdapter instead of niceview's JsonAdapter wherever config/data
files may be hand-edited by operators.
"""
import json
from typing import TypeVar

import pydantic
from pydantic import ValidationError
from niceview.dataadapter import JsonAdapter

from app.util import logger

T = TypeVar('T', bound=pydantic.BaseModel)


def lenient_model_load(model_type: type[T], json_text: str, context: str = '') -> T:
    """Parse *json_text* and validate against *model_type* with maximum tolerance.

    Behaviour on errors:

    * ``JSONDecodeError``     — logs, returns ``model_type()`` (all defaults)
    * Unknown fields          — logs each unknown key, then ignores them
      (Pydantic already ignores extras; we add the log)
    * Bad / missing field     — logs, strips the offending field, retries;
      the model default fills the gap
    * Unrecoverable error     — logs and raises (true last resort)

    *context* is a human-readable label (e.g. a file path) used in log messages.
    """
    ctx = f' [{context}]' if context else ''

    # 1. Parse raw JSON
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f'JSON parse error{ctx}: {e} — using defaults')
        return model_type()

    if not isinstance(data, dict):
        logger.error(
            f'JSON{ctx} is not an object (got {type(data).__name__}) — using defaults'
        )
        return model_type()

    # 2. Log unknown fields (Pydantic already ignores them on validate)
    known = set(model_type.model_fields.keys())
    for key in sorted(set(data.keys()) - known):
        logger.error(f'Unknown field {key!r}{ctx} — ignoring')

    # 3. Iteratively strip bad fields until validation passes
    bad_keys: set[str] = set()
    while True:
        clean = {k: v for k, v in data.items() if k not in bad_keys}
        try:
            return model_type.model_validate(clean)
        except ValidationError as exc:
            newly_bad: set[str] = set()
            for err in exc.errors():
                loc = err.get('loc', ())
                field = loc[0] if loc else None
                if isinstance(field, str) and field not in bad_keys:
                    logger.error(
                        f'Invalid value for field {field!r}{ctx}: {err["msg"]} — using default'
                    )
                    newly_bad.add(field)
            if not newly_bad:
                # Cannot make progress (e.g. required field with no default is missing)
                logger.error(f'Cannot recover from validation errors{ctx}: {exc}')
                raise
            bad_keys |= newly_bad


def lenient_list_load(item_type: type[T], json_text: str, context: str = '') -> list[T]:
    """Parse *json_text* as a JSON array of *item_type* objects.

    Skips (and logs) individual items that fail validation instead of failing
    the whole list.  Returns ``[]`` on top-level parse errors.
    """
    ctx = f' [{context}]' if context else ''

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f'JSON parse error{ctx}: {e} — returning empty list')
        return []

    if not isinstance(data, list):
        logger.error(f'JSON{ctx} is not an array (got {type(data).__name__}) — returning empty list')
        return []

    result: list[T] = []
    for i, raw_item in enumerate(data):
        try:
            result.append(lenient_model_load(item_type, json.dumps(raw_item), f'{context}[{i}]'))
        except Exception as e:
            logger.error(f'Cannot load item [{i}]{ctx}: {e} — skipping')
    return result


class LenientJsonAdapter(JsonAdapter[T]):
    """JsonAdapter subclass whose ``read()`` uses :func:`lenient_model_load`.

    Drop-in replacement for ``niceview.JsonAdapter``.  All other behaviour
    (atomic writes, optimistic locking, created_field) is inherited unchanged.
    """

    def read(self) -> T:
        try:
            json_text = self._path_name.read_text(encoding='utf-8')
        except OSError as e:
            logger.error(f'Cannot read {self._path_name}: {e} — using defaults')
            return self._item_type()
        return lenient_model_load(self._item_type, json_text, str(self._path_name))
