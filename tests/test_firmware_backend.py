"""Unit tests for app.core.firmware.backend — config/state IO, release resolution
helpers, pull orchestration (network mocked), and the should-pull decision."""
import asyncio
import hashlib

import pytest
from pydantic import ValidationError

from app.core.firmware import backend
from app.core.firmware.backend import (
    FirmwareError,
    _should_pull,
    _validate_repo,
    load_firmware_source,
    load_firmware_state,
    release_url,
    save_firmware_state,
)
from app.core.firmware.models import FirmwareSource, FirmwareState


def _release(tag='v1.0.0', digest=None, asset='firmware.bin'):
    return {'tag_name': tag,
            'assets': [{'name': asset, 'url': 'https://api.github.com/x', 'digest': digest or ''}]}


# ---------------------------------------------------------------------------
# config / state persistence
# ---------------------------------------------------------------------------

def test_load_source_default_when_absent(tmp_path):
    src = load_firmware_source(tmp_path)
    assert src.repo == ''
    assert src.channel == 'stable'
    assert src.asset_name == 'firmware.bin'


def test_state_roundtrip(tmp_path):
    assert load_firmware_state(tmp_path) is None
    save_firmware_state(tmp_path, FirmwareState(tag='v2', digest='sha256:abc', etag='e1'))
    st = load_firmware_state(tmp_path)
    assert st.tag == 'v2' and st.digest == 'sha256:abc' and st.etag == 'e1'


# ---------------------------------------------------------------------------
# model validation
# ---------------------------------------------------------------------------

def test_repo_validator_accepts_owner_name():
    assert FirmwareSource(repo='clausgf/nice4iot').repo == 'clausgf/nice4iot'


def test_repo_validator_accepts_gitlab_subgroup():
    # GitLab projects can live under nested subgroups, unlike GitHub's flat
    # owner/name — repo accepts any number of '/'-separated segments.
    assert FirmwareSource(repo='group/subgroup/project').repo == 'group/subgroup/project'


@pytest.mark.parametrize('bad', ['https://github.com/a/b', 'no-slash', 'a b/c'])
def test_repo_validator_rejects_non_owner_name(bad):
    with pytest.raises(ValidationError):
        FirmwareSource(repo=bad)


def test_host_url_validator_accepts_bare_origin_strips_trailing_slash():
    assert FirmwareSource(host_url='https://gitlab.example.com/').host_url == 'https://gitlab.example.com'


@pytest.mark.parametrize('bad', ['gitlab.example.com', 'https://gitlab.example.com/group', 'ftp://gitlab.example.com'])
def test_host_url_validator_rejects_non_bare_origin(bad):
    with pytest.raises(ValidationError):
        FirmwareSource(host_url=bad)


def test_filename_validator_defaults_and_rejects():
    assert FirmwareSource(asset_name='').asset_name == 'firmware.bin'
    with pytest.raises(ValidationError):
        FirmwareSource(dest_filename='../evil')


def test_validate_repo_helper():
    assert _validate_repo(' owner/name ') == 'owner/name'
    with pytest.raises(FirmwareError):
        _validate_repo('not-a-repo')


def test_release_url_github():
    assert release_url(FirmwareSource(repo='')) == ''
    assert release_url(FirmwareSource(repo='a/b', channel='stable')) == \
        'https://github.com/a/b/releases/latest'
    assert release_url(FirmwareSource(repo='a/b', channel='prerelease')) == \
        'https://github.com/a/b/releases'
    assert release_url(FirmwareSource(repo='a/b', channel='pinned', pinned_tag='v1.2')) == \
        'https://github.com/a/b/releases/tag/v1.2'
    # pinned without a tag falls back to the releases list
    assert release_url(FirmwareSource(repo='a/b', channel='pinned')) == \
        'https://github.com/a/b/releases'


def test_release_url_gitlab():
    gitlab_com = FirmwareSource(host='gitlab', repo='a/b', channel='stable')
    assert release_url(gitlab_com) == 'https://gitlab.com/a/b/-/releases'
    assert release_url(FirmwareSource(host='gitlab', repo='a/b/c', channel='pinned', pinned_tag='v1.2')) == \
        'https://gitlab.com/a/b/c/-/releases/v1.2'
    # a self-hosted host_url is used instead of gitlab.com
    self_hosted = FirmwareSource(host='gitlab', host_url='https://gitlab.example.com', repo='a/b')
    assert release_url(self_hosted) == 'https://gitlab.example.com/a/b/-/releases'


# ---------------------------------------------------------------------------
# should-pull decision
# ---------------------------------------------------------------------------

def test_should_pull_matrix():
    from app.core.firmware.backend import ResolvedAsset
    stable = FirmwareSource(repo='a/b', channel='stable')
    pinned = FirmwareSource(repo='a/b', channel='pinned', pinned_tag='v1')
    r = ResolvedAsset(tag='v1', asset_name='firmware.bin', download_url='u', digest='sha256:aa')

    assert _should_pull(stable, None, r) is True                      # no state
    assert _should_pull(stable, FirmwareState(tag='v1'), r) is False  # same tag
    assert _should_pull(stable, FirmwareState(tag='v0'), r) is True   # newer tag
    # pinned: re-pull only when the asset bytes (digest) change
    assert _should_pull(pinned, FirmwareState(tag='v1', digest='sha256:aa'), r) is False
    assert _should_pull(pinned, FirmwareState(tag='v1', digest='sha256:bb'), r) is True


# ---------------------------------------------------------------------------
# pull orchestration (network mocked)
# ---------------------------------------------------------------------------

def _mock_github(monkeypatch, release_json, download):
    """`download` is (data, digest) tuple for the single asset. Mocks the
    host-agnostic dispatch points in backend.py directly, so it works
    regardless of src.host — the name is legacy from before GitLab support."""
    async def fake_resolve(client, src, etag):
        return release_json, 'etag-xyz'

    async def fake_download(client, url, max_size, src):
        return download

    monkeypatch.setattr(backend, '_resolve_release_json', fake_resolve)
    monkeypatch.setattr(backend, '_download_asset', fake_download)


def test_pull_writes_file_and_records_state(tmp_path, monkeypatch):
    data = b'FIRMWARE-CONTENT'
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    _mock_github(monkeypatch, _release(tag='v1.2.3', digest=digest), (data, digest))

    src = FirmwareSource(repo='owner/name')
    result = asyncio.run(backend.pull_firmware(tmp_path, src, project_name='p'))

    assert result.changed is True and result.tag == 'v1.2.3'
    assert (tmp_path / 'firmware.bin').read_bytes() == data
    st = load_firmware_state(tmp_path)
    assert st.tag == 'v1.2.3' and st.digest == digest and st.etag == 'etag-xyz'
    assert st.asset == 'firmware.bin'


def test_pull_digest_mismatch_writes_nothing(tmp_path, monkeypatch):
    data = b'FIRMWARE-CONTENT'
    claimed = 'sha256:' + 'a' * 64  # release claims this
    actual = 'sha256:' + hashlib.sha256(data).hexdigest()  # download computes this
    _mock_github(monkeypatch, _release(digest=claimed), (data, actual))

    src = FirmwareSource(repo='owner/name')
    with pytest.raises(FirmwareError):
        asyncio.run(backend.pull_firmware(tmp_path, src, project_name='p'))
    assert not (tmp_path / 'firmware.bin').exists()
    assert load_firmware_state(tmp_path) is None


def test_pull_skips_when_unchanged_and_does_not_download(tmp_path, monkeypatch):
    data = b'X'
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    save_firmware_state(tmp_path, FirmwareState(tag='v1.0.0', digest=digest))

    downloaded = {'called': False}

    async def fake_resolve(client, src, etag):
        return _release(tag='v1.0.0', digest=digest), 'etag-new'

    async def fake_download(client, url, max_size, src):
        downloaded['called'] = True
        return data, digest

    monkeypatch.setattr(backend, '_resolve_release_json', fake_resolve)
    monkeypatch.setattr(backend, '_download_asset', fake_download)

    src = FirmwareSource(repo='owner/name')
    result = asyncio.run(backend.pull_firmware(tmp_path, src, project_name='p'))

    assert result.changed is False
    assert downloaded['called'] is False  # no download when already up to date


def test_pull_not_modified_304(tmp_path, monkeypatch):
    async def fake_resolve(client, src, etag):
        return None, etag or ''  # simulate HTTP 304

    monkeypatch.setattr(backend, '_resolve_release_json', fake_resolve)
    save_firmware_state(tmp_path, FirmwareState(tag='v9', etag='old'))

    src = FirmwareSource(repo='owner/name')
    result = asyncio.run(backend.pull_firmware(tmp_path, src, project_name='p', use_conditional=True))
    assert result.changed is False


def test_pull_requires_repo(tmp_path):
    with pytest.raises(FirmwareError):
        asyncio.run(backend.pull_firmware(tmp_path, FirmwareSource(repo=''), project_name='p'))


def test_pull_respects_dest_filename(tmp_path, monkeypatch):
    data = b'FIRMWARE-CONTENT'
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    _mock_github(monkeypatch, _release(tag='v1.2.3', digest=digest, asset='release.bin'), (data, digest))

    src = FirmwareSource(repo='owner/name', asset_name='release.bin', dest_filename='custom.bin')
    result = asyncio.run(backend.pull_firmware(tmp_path, src, project_name='p'))

    assert result.changed is True
    assert (tmp_path / 'custom.bin').read_bytes() == data
    assert not (tmp_path / 'release.bin').exists()
    st = load_firmware_state(tmp_path)
    assert st.asset == 'release.bin'  # state records the release asset name
    assert (tmp_path / 'custom.bin').exists()  # file is written with dest_filename