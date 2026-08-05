"""Unit tests for the device-over-project file overlay behind the unified Files
card (app.core.device.file_overlay)."""
import pytest

from app.core.device.file_overlay import OverlayDirectoryAdapter, resolve_ref
from app.util import is_valid_upload_filename


@pytest.fixture
def dirs(tmp_path):
    """A device directory with the project directory as its underlay."""
    device = tmp_path / 'proj' / 'dev'
    project = tmp_path / 'proj'
    device.mkdir(parents=True)
    return device, project


def _adapter(device, project):
    return OverlayDirectoryAdapter(device, project, suffix=None,
                                   name_filter=is_valid_upload_filename)


def _names(adapter):
    return [entry.name for entry in adapter]


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------

def test_resolve_ref_own_file_wins(dirs):
    device, project = dirs
    (device / 'config.json').write_text('{"own": 1}')
    (project / 'config.json').write_text('{"shared": 1}')
    ref = resolve_ref('config.json', device, project)
    assert ref.read_path == device / 'config.json'
    assert ref.save_path == device / 'config.json'
    assert ref.inherited is False
    assert ref.overrides is True          # it hides the project file


def test_resolve_ref_inherited_reads_project_saves_device(dirs):
    device, project = dirs
    (project / 'config.json').write_text('{"shared": 1}')
    ref = resolve_ref('config.json', device, project)
    assert ref.read_path == project / 'config.json'
    assert ref.save_path == device / 'config.json'   # copy-on-write target
    assert ref.inherited is True
    assert ref.overrides is False


def test_resolve_ref_own_file_without_project_counterpart(dirs):
    device, project = dirs
    (device / 'only.json').write_text('{}')
    ref = resolve_ref('only.json', device, project)
    assert ref.inherited is False and ref.overrides is False


def test_resolve_ref_missing_file_points_at_the_write_dir(dirs):
    device, project = dirs
    ref = resolve_ref('new.json', device, project)
    assert ref.read_path == ref.save_path == device / 'new.json'
    assert ref.inherited is False and ref.overrides is False


def test_resolve_ref_without_underlay_never_inherits(dirs):
    device, project = dirs
    (project / 'config.json').write_text('{}')
    ref = resolve_ref('config.json', project, None)
    assert ref.read_path == ref.save_path == project / 'config.json'
    assert ref.inherited is False and ref.overrides is False


# ---------------------------------------------------------------------------
# OverlayDirectoryAdapter
# ---------------------------------------------------------------------------

def test_listing_is_the_union_with_device_files_shadowing(dirs):
    device, project = dirs
    (device / 'own.json').write_text('{}')
    (device / 'both.json').write_text('device wins')
    (project / 'both.json').write_text('x')
    (project / 'shared.json').write_text('{}')
    adapter = _adapter(device, project)
    assert _names(adapter) == ['both.json', 'own.json', 'shared.json']
    # 'both.json' appears once, with the device copy's size
    both = next(e for e in adapter if e.name == 'both.json')
    assert both.size == len('device wins')


def test_listing_is_sorted_by_name_across_both_directories(dirs):
    device, project = dirs
    for name in ('b.json', 'd.json'):
        (device / name).write_text('{}')
    for name in ('a.json', 'c.json'):
        (project / name).write_text('{}')
    assert _names(_adapter(device, project)) == ['a.json', 'b.json', 'c.json', 'd.json']


def test_read_resolves_through_the_underlay(dirs):
    device, project = dirs
    (project / 'shared.json').write_text('{"a": 1}')
    entry = _adapter(device, project).read('shared.json')
    assert entry.name == 'shared.json'
    assert entry.size == len('{"a": 1}')


def test_read_prefers_the_device_copy(dirs):
    device, project = dirs
    (project / 'both.json').write_text('project version')
    (device / 'both.json').write_text('dev')
    assert _adapter(device, project).read('both.json').size == len('dev')


def test_read_raises_for_a_name_in_neither_layer(dirs):
    device, project = dirs
    with pytest.raises(KeyError):
        _adapter(device, project).read('missing.json')


@pytest.mark.parametrize("name", ['.hidden.json', 'bad name.json', '.mqtt_file_state.json'])
def test_filters_apply_to_the_underlay_too(dirs, name):
    """Dotfiles and name_filter rejects are excluded from both layers, not just
    the adapter's own directory."""
    device, project = dirs
    (project / name).write_text('{}')
    (project / 'good.json').write_text('{}')
    assert _names(_adapter(device, project)) == ['good.json']


def test_missing_underlay_directory_is_tolerated(tmp_path):
    device = tmp_path / 'dev'
    device.mkdir()
    (device / 'own.json').write_text('{}')
    assert _names(_adapter(device, tmp_path / 'nonexistent')) == ['own.json']


def test_without_underlay_behaves_like_a_plain_directory(dirs):
    device, project = dirs
    (device / 'own.json').write_text('{}')
    (project / 'shared.json').write_text('{}')
    adapter = OverlayDirectoryAdapter(device, None, suffix=None,
                                      name_filter=is_valid_upload_filename)
    assert _names(adapter) == ['own.json']


def test_create_and_delete_only_touch_the_own_directory(dirs):
    """Writes never reach the underlay — an inherited name creates a device copy
    and deleting it brings the project file back into the listing."""
    device, project = dirs
    (project / 'shared.json').write_text('{"from": "project"}')
    adapter = _adapter(device, project)

    (device / 'shared.json').write_text('{"from": "device"}')
    assert _names(_adapter(device, project)) == ['shared.json']
    assert adapter.read('shared.json').size == len('{"from": "device"}')

    adapter.delete('shared.json')
    assert (project / 'shared.json').read_text() == '{"from": "project"}'
    assert _names(_adapter(device, project)) == ['shared.json']  # inherited again


def test_listing_matches_the_publisher_merge(dirs):
    """The card's listing and check_and_publish_project's merge must not drift."""
    from app.core.file.backend import _list_publishable_files

    device, project = dirs
    (device / 'own.json').write_text('{}')
    (device / 'both.json').write_text('{}')
    (project / 'both.json').write_text('{}')
    (project / 'shared.txt').write_text('x')

    device_files = _list_publishable_files(device)
    project_files = _list_publishable_files(project)
    device_filenames = {p.name for p in device_files}
    merged = list(device_files) + [p for p in project_files
                                   if p.name not in device_filenames]

    assert sorted(p.name for p in merged) == _names(_adapter(device, project))


# ---------------------------------------------------------------------------
# Coupling guard
# ---------------------------------------------------------------------------

def test_overrides_only_niceview_internals_that_still_exist():
    """OverlayDirectoryAdapter deliberately overrides private DirectoryAdapter
    methods — the underlay rule is too specific to push into niceview itself.

    The price is that a rename in the library breaks us silently: `_iter_paths`
    became `_scan` once already. This test states the coupling explicitly, so the
    next rename fails here with a readable message instead of surfacing as an
    AttributeError somewhere inside a directory listing.
    """
    from niceview import DirectoryAdapter

    for name in ('_scan', '_path'):
        assert callable(getattr(DirectoryAdapter, name, None)), (
            f'niceview DirectoryAdapter no longer has {name}(); '
            f'OverlayDirectoryAdapter overrides it — adjust file_overlay.py'
        )
