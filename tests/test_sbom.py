"""Unit tests for the Software Bill of Materials backend (app.sbom)."""
from app.sbom import app_commit_date, app_revision, collect_sbom, package_version


def test_collect_sbom_returns_sorted_name_version_pairs():
    sbom = collect_sbom()
    assert isinstance(sbom, list)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in sbom)
    names = [name for name, _ in sbom]
    # Case-insensitive sort, and every entry carries a version string.
    assert names == sorted(names, key=str.lower)
    assert all(isinstance(v, str) and v for _, v in sbom)


def test_collect_sbom_includes_a_known_core_dependency():
    names = {name.lower() for name, _ in collect_sbom()}
    # nicegui is a hard dependency, always present in any real environment.
    assert 'nicegui' in names


def test_collect_sbom_deduplicates_by_name():
    names = [name for name, _ in collect_sbom()]
    assert len(names) == len(set(names))


def test_package_version_for_installed_package():
    assert package_version('nicegui') is not None


def test_package_version_for_absent_package_is_none():
    assert package_version('this-distribution-does-not-exist-xyz') is None


def test_app_revision_is_str_or_none():
    rev = app_revision()
    assert rev is None or isinstance(rev, str)


def test_app_revision_prefers_baked_env(monkeypatch):
    monkeypatch.setenv('NICE4IOT_GIT_COMMIT', 'abc1234def56789')
    # Baked value wins over any git lookup, truncated to 12 chars.
    assert app_revision() == 'abc1234def56'


def test_app_commit_date_is_str_or_none():
    d = app_commit_date()
    assert d is None or isinstance(d, str)


def test_app_commit_date_prefers_baked_env(monkeypatch):
    monkeypatch.setenv('NICE4IOT_GIT_COMMIT_DATE', '2026-08-02T21:48:49+00:00')
    assert app_commit_date() == '2026-08-02T21:48:49+00:00'


def test_app_commit_date_empty_env_falls_through_to_git(monkeypatch):
    # An empty baked value is treated as unset (falls through to git), never
    # returned as an empty string.
    monkeypatch.setenv('NICE4IOT_GIT_COMMIT_DATE', '')
    result = app_commit_date()
    assert result != ''
    assert result is None or isinstance(result, str)
