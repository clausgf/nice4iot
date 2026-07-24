"""Unit tests for the Software Bill of Materials backend (app.sbom)."""
from app.sbom import collect_sbom, package_version


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
