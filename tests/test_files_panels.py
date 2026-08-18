"""Smoke tests that actually render the Files card — list, detail and the
navigation between them.

The rest of the Files suite tests pure logic (test_files_form, test_file_overlay).
Nothing exercised the rendering itself, so a wrong keyword argument between
`device_files_panel` and `_files_card` reached the browser instead of CI. NiceGUI
lets elements be built outside a page context, so rendering them costs no extra
test dependency.

These assert that the card builds without raising, across the states that pick
different code paths — not what the markup looks like.
"""
import asyncio

import pytest
from nicegui import ui

from app.core.device.backend import create_device
from app.core.file.browser_ui import device_files_panel, project_files_panel
from app.core.device.models import Device
from app.paths import device_dir, project_dir

from tests.conftest import setup_project


@pytest.fixture
def project_with_device(projects_dir):
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    return 'proj', 'dev'


def _render(coro):
    """Run a panel coroutine to completion, failing the test on any exception.

    NiceGUI keeps its slot stack per asyncio task, so the container has to be
    built out here and re-entered inside the task asyncio.run() creates.
    """
    container = ui.column()

    async def run() -> None:
        with container:
            await coro

    asyncio.run(run())


def test_device_panel_renders_when_everything_is_empty(project_with_device):
    _render(device_files_panel(*project_with_device))


def test_device_panel_renders_with_own_inherited_and_overriding_files(project_with_device):
    project, device = project_with_device
    (project_dir(project) / 'shared.json').write_text('{"a": 1}')      # inherited
    (project_dir(project) / 'both.json').write_text('{"a": 1}')
    (device_dir(project, device) / 'both.json').write_text('{"a": 2}')  # overrides
    (device_dir(project, device) / 'own.txt').write_text('hello')       # device only
    _render(device_files_panel(project, device))


def test_device_panel_renders_with_mqtt_enabled(projects_dir):
    """Enables the publish button and the file-state read, a separate branch."""
    setup_project('proj', is_mqtt_enabled=True)
    create_device(Device(project_name='proj', name='dev'))
    (project_dir('proj') / 'shared.json').write_text('{}')
    _render(device_files_panel('proj', 'dev'))


def test_device_panel_renders_for_a_missing_project(projects_dir):
    """get_project raises here; the panel is expected to fall back, not blow up."""
    setup_project('proj')
    create_device(Device(project_name='proj', name='dev'))
    _render(device_files_panel('proj', 'dev'))


def test_project_panel_renders(projects_dir):
    setup_project('proj')
    (project_dir('proj') / 'config.json').write_text('{"a": 1}')
    _render(project_files_panel('proj'))


# ---------------------------------------------------------------------------
# Detail view — the other half of the card, and the half the panel tests miss
# ---------------------------------------------------------------------------

def _detail(project, device, key):
    """Render the detail view for one file of the device card."""
    from app.core.file.detail_ui import file_detail
    from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter
    from app.util import is_valid_upload_filename

    ctx = FileCtx(project, device, False, underlay_dir=project_dir(project))
    adapter = OverlayDirectoryAdapter(device_dir(project, device), project_dir(project),
                                      suffix=None, name_filter=is_valid_upload_filename)
    container = ui.column()

    async def run() -> None:
        with container:
            file_detail(adapter, key, ctx)

    asyncio.run(run())


def test_detail_renders_json_with_an_inferred_form(project_with_device):
    project, device = project_with_device
    (device_dir(project, device) / 'flat.json').write_text('{"n": 1, "s": "x", "b": true}')
    _detail(project, device, 'flat.json')


def test_detail_renders_json_that_has_no_form(project_with_device):
    project, device = project_with_device
    (device_dir(project, device) / 'deep.json').write_text('{"nested": {"a": 1}}')
    _detail(project, device, 'deep.json')


def test_detail_renders_broken_json_as_raw(project_with_device):
    project, device = project_with_device
    (device_dir(project, device) / 'broken.json').write_text('{oops')
    _detail(project, device, 'broken.json')


def test_detail_renders_a_schema_driven_form(project_with_device):
    """Every widget kind of the subset at once — the switch in form_ui.py."""
    from app.core.file.form import approve_schema
    project, device = project_with_device
    (device_dir(project, device) / 'cfg.json').write_text('{"mode": "eco"}')
    schema = device_dir(project, device) / 'cfg.schema.json'
    schema.write_text("""{"type":"object","required":["mode"],"properties":{
        "mode":   {"type":"string","enum":["eco","turbo"],"description":"Run mode"},
        "name":   {"type":"string","maxLength":10},
        "notes":  {"type":"string","x-multiline":true},
        "day":    {"type":"string","format":"date"},
        "count":  {"type":"integer","minimum":1,"maximum":9},
        "factor": {"type":"number"},
        "on":     {"type":"boolean"},
        "tags":   {"type":"array","items":{"type":"string"}}}}""")
    approve_schema(schema, project)
    _detail(project, device, 'cfg.json')


def test_detail_renders_the_approval_banner_for_an_unapproved_schema(project_with_device):
    project, device = project_with_device
    (device_dir(project, device) / 'cfg.json').write_text('{"mode": "eco"}')
    (device_dir(project, device) / 'cfg.schema.json').write_text(
        '{"type":"object","properties":{"mode":{"type":"string"}}}')
    _detail(project, device, 'cfg.json')


def test_detail_renders_an_inherited_file_with_its_banner(project_with_device):
    project, device = project_with_device
    (project_dir(project) / 'shared.json').write_text('{"a": 1}')
    _detail(project, device, 'shared.json')


def test_detail_renders_text_image_and_binary(project_with_device):
    project, device = project_with_device
    d = device_dir(project, device)
    (d / 'notes.md').write_text('# hi')
    (d / 'pic.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 32)
    (d / 'blob.bin').write_bytes(b'\x00\x01\x02')
    for key in ('notes.md', 'pic.png', 'blob.bin'):
        _detail(project, device, key)


def test_detail_reports_a_file_that_is_gone(project_with_device):
    project, device = project_with_device
    _detail(project, device, 'vanished.json')


# ---------------------------------------------------------------------------
# The niceview interaction — list <-> detail navigation
# ---------------------------------------------------------------------------

def test_wrapper_navigates_from_the_list_into_the_detail_view(project_with_device):
    """Covers what rendering a panel cannot: that DrillDownWrapper accepts our
    entry type and that open() reaches the detail renderer.

    Navigating swaps the wrapper's body through a ui.refreshable, which NiceGUI
    runs as a background task — hence the loop hand-off and the drain below;
    without draining, a crash inside the detail view would go unnoticed.
    """
    from nicegui import background_tasks, core

    from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter
    from app.core.file.browser_ui import _build_wrapper
    from app.util import is_valid_upload_filename

    project, device = project_with_device
    (device_dir(project, device) / 'own.json').write_text('{"n": 1}')
    (project_dir(project) / 'shared.txt').write_text('hello')       # inherited

    ctx = FileCtx(project, device, False, underlay_dir=project_dir(project))
    adapter = OverlayDirectoryAdapter(device_dir(project, device), project_dir(project),
                                      suffix=None, name_filter=is_valid_upload_filename)
    container = ui.column()

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        try:
            with container:
                wrapper = _build_wrapper(adapter, title='Files', ctx=ctx,
                                         refresh=lambda: None, state={})
                wrapper.render()
                wrapper.open('own.json')     # own file -> detail
                wrapper.open('shared.txt')   # inherited file -> detail with banner
                # gather re-raises whatever the refresh tasks hit
                while pending := list(background_tasks.running_tasks):
                    await asyncio.gather(*pending)
        finally:
            core.loop = None

    asyncio.run(run())


def test_wrapper_add_button_takes_our_async_handler(project_with_device):
    """Add is niceview's own title-row button driving our async on_add.

    niceview 0.15.0 awaits an async on_add but rejects an async *renderer* at
    construction time, so the two look alike and are not. Worth pinning: a
    handler niceview refuses to await is a button that silently does nothing —
    the failure mode 0.15.0 was released to end — and it would never show up in
    a test that only renders the list.
    """
    from nicegui import background_tasks, core

    from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter
    from app.core.file.browser_ui import _build_wrapper
    from app.util import is_valid_upload_filename

    project, device = project_with_device
    ctx = FileCtx(project, device, False, underlay_dir=project_dir(project))
    adapter = OverlayDirectoryAdapter(device_dir(project, device), project_dir(project),
                                      suffix=None, name_filter=is_valid_upload_filename)
    container = ui.column()
    called = False

    async def _on_add() -> None:
        nonlocal called
        called = True

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        try:
            with container:
                wrapper = _build_wrapper(adapter, title='Files', ctx=ctx,
                                         refresh=lambda: None, state={}, on_add=_on_add)
                wrapper.render()
                assert wrapper.add_button is not None      # Add is the wrapper's own button
                assert wrapper.delete_button is not None   # so is Delete
                await wrapper._handle_add()                # what the click awaits
                while pending := list(background_tasks.running_tasks):
                    await asyncio.gather(*pending)
        finally:
            core.loop = None

    asyncio.run(run())
    assert called, 'niceview did not await our async on_add handler'


def test_detail_hides_delete_for_an_inherited_file(project_with_device):
    """Delete is niceview's own title-row button, hidden for an inherited file —
    there is no device copy to remove, and the adapter would raise KeyError.

    This pins an ordering niceview guarantees rather than documents as API: the
    title row is updated *before* the body is refreshed, so the visibility our
    render_detail sets is the last word. If that ever reversed, Delete would sit
    enabled on a file it cannot delete, and nothing else here would notice.
    """
    from nicegui import background_tasks, core

    from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter
    from app.core.file.browser_ui import _build_wrapper
    from app.util import is_valid_upload_filename

    project, device = project_with_device
    (device_dir(project, device) / 'own.json').write_text('{"n": 1}')
    (project_dir(project) / 'shared.txt').write_text('hello')       # inherited

    ctx = FileCtx(project, device, False, underlay_dir=project_dir(project))
    adapter = OverlayDirectoryAdapter(device_dir(project, device), project_dir(project),
                                      suffix=None, name_filter=is_valid_upload_filename)
    container = ui.column()
    seen: dict[str, bool] = {}

    async def run() -> None:
        core.loop = asyncio.get_running_loop()
        try:
            with container:
                wrapper = _build_wrapper(adapter, title='Files', ctx=ctx,
                                         refresh=lambda: None, state={})
                wrapper.render()
                # mqtt_enabled=False, so publish is absent entirely rather than hidden
                assert set(wrapper.action_buttons) == {'download'}
                assert wrapper.delete_button is not None
                for key in ('own.json', 'shared.txt'):
                    wrapper.open(key)
                    while pending := list(background_tasks.running_tasks):
                        await asyncio.gather(*pending)
                    seen[key] = wrapper.delete_button.visible
        finally:
            core.loop = None

    asyncio.run(run())
    assert seen['own.json'] is True, 'Delete must be offered for the device\'s own file'
    assert seen['shared.txt'] is False, 'Delete must be hidden for an inherited file'


def test_delete_confirmation_is_worded_per_entry():
    """The reason Delete can be niceview's own button: a ChromeText slot takes a
    callable, so the one message it offers still asks the right question.

    Dropping a device copy is not the irreversible delete of a plain file, and
    saying so is the whole point of the overlay being visible in this card.
    """
    import datetime
    from pathlib import Path

    from niceview.text import text_of

    from app.core.file.browser_ui import _delete_texts
    from app.core.file.overlay import OverlayFileEntry

    def entry(**kw) -> OverlayFileEntry:
        path = Path('/tmp/config.json')
        return OverlayFileEntry(name='config.json', mtime=datetime.datetime.now(), size=1,
                                read_path=path, save_path=path, **kw)

    shown: OverlayFileEntry | None = None
    texts = _delete_texts(lambda: shown)

    shown = entry(overrides=True)
    message = text_of(texts.delete_item_message)
    assert 'project file will be used again' in message
    assert 'irreversible' not in message.lower(), 'a device copy is not an irreversible delete'
    assert '**config.json**' in message, 'the dialog renders markdown'

    shown = entry()
    assert 'irreversible' in text_of(texts.delete_item_message).lower()
    assert text_of(texts.item_deleted) == 'Deleted config.json'

    shown = None  # never reached through the UI, but must not raise
    assert text_of(texts.delete_item_message)
    assert text_of(texts.item_deleted)


def test_detail_actions_include_publish_only_where_it_can_work(project_with_device):
    """Publish is card-level constant, so it is absent rather than hidden — a
    project card has no device to publish to."""
    from app.core.file.overlay import FileCtx
    from app.core.file.browser_ui import _file_actions

    project, device = project_with_device
    assert 'publish' not in _file_actions(FileCtx(project, None, False), lambda: None)
    assert 'publish' not in _file_actions(FileCtx(project, device, False), lambda: None)
    assert 'publish' in _file_actions(FileCtx(project, device, True), lambda: None)


@pytest.mark.parametrize("raw,expected", [
    ('config', 'config.json'),
    ('config.json', 'config.json'),
    ('  spaced  ', 'spaced.json'),
    ('', '.json'),        # rejected by the validator, never written
    (None, '.json'),      # the input starts out empty
])
def test_new_json_name_completion(raw, expected):
    from app.core.file.browser_ui import _as_json_name
    from app.util import is_valid_upload_filename

    assert _as_json_name(raw) == expected
    if expected == '.json':
        assert not is_valid_upload_filename(_as_json_name(raw))


# ---------------------------------------------------------------------------
# Form round-trip — render_field in, field_value out
# ---------------------------------------------------------------------------

def _round_trip(fields):
    """Render the fields and read them straight back, without touching a widget."""
    from app.core.file.form_ui import render_form_fields

    container = ui.column()
    result = {}

    async def run() -> None:
        with container:
            collect = render_form_fields(fields)
            result['values'] = collect()

    asyncio.run(run())
    return result['values']


def test_form_round_trip_preserves_every_kind_and_stays_json_serialisable():
    """niceview converts widget values by field_type, so a value that goes into a
    widget must come back unchanged — and json.dumps must accept it, which a
    datetime.date from the date widget would not."""
    import json

    from app.core.file.form import FormField

    fields = [
        FormField('s', 'string', 'text'),
        FormField('t', 'textarea', 'multi\nline'),
        FormField('d', 'date', '2026-08-06'),
        FormField('i', 'integer', 42),
        FormField('f', 'number', 1.5),
        FormField('b', 'boolean', True),
        FormField('e', 'enum', 'eco', enum=['eco', 'turbo']),
        FormField('l', 'string_list', ['a', 'b']),
    ]
    values = _round_trip(fields)
    assert values == {'s': 'text', 't': 'multi\nline', 'd': '2026-08-06', 'i': 42,
                      'f': 1.5, 'b': True, 'e': 'eco', 'l': ['a', 'b']}
    assert isinstance(values['i'], int) and not isinstance(values['i'], bool)
    json.dumps(values)   # would raise on a date object


def test_form_round_trip_keeps_empty_values_empty():
    from app.core.file.form import FormField

    values = _round_trip([
        FormField('s', 'string', ''),
        FormField('d', 'date', ''),
        FormField('l', 'string_list', []),
    ])
    assert values == {'s': '', 'd': None, 'l': []}


def test_form_collect_reports_the_first_violation():
    from app.core.file.form import FormField

    values = _round_trip([FormField('n', 'integer', 5, minimum=10)])
    assert values is None   # out of range -> reported, nothing returned
