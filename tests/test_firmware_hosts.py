"""Unit tests for app.core.firmware.github / .gitlab — the host-specific
resolution/asset-parsing/download-allowlist logic that app.core.firmware.
backend dispatches to on src.host. See test_firmware_backend.py for the
host-agnostic pull orchestration (network mocked at the backend dispatch
points, so it doesn't exercise these modules' own parsing logic)."""
import asyncio

import pytest

from app.core.firmware import github, gitlab
from app.core.firmware.models import FirmwareError, FirmwareSource


# ---------------------------------------------------------------------------
# github.py
# ---------------------------------------------------------------------------

def test_github_resolved_asset_picks_named_asset():
    release = {'tag_name': 'v1', 'assets': [
        {'name': 'other.bin', 'url': 'https://api.github.com/other', 'digest': ''},
        {'name': 'firmware.bin', 'url': 'https://api.github.com/x', 'digest': 'sha256:aa'},
    ]}
    src = FirmwareSource(repo='a/b', asset_name='firmware.bin')
    resolved = github.resolved_asset(release, src)
    assert resolved.tag == 'v1'
    assert resolved.download_url == 'https://api.github.com/x'
    assert resolved.digest == 'sha256:aa'


def test_github_resolved_asset_missing_raises():
    release = {'tag_name': 'v1', 'assets': []}
    with pytest.raises(FirmwareError):
        github.resolved_asset(release, FirmwareSource(repo='a/b'))


def test_github_is_allowed_download_host():
    src = FirmwareSource(repo='a/b')
    assert github.is_allowed_download_host('api.github.com', src)
    assert github.is_allowed_download_host('objects.githubusercontent.com', src)
    assert not github.is_allowed_download_host('evil.example.com', src)


# ---------------------------------------------------------------------------
# gitlab.py
# ---------------------------------------------------------------------------

def test_gitlab_resolved_asset_picks_named_link():
    release = {'tag_name': 'v1', 'assets': {'links': [
        {'name': 'other.bin', 'url': 'https://gitlab.com/other'},
        {'name': 'firmware.bin', 'direct_asset_url': 'https://gitlab.com/-/project/releases/v1/firmware.bin',
         'url': 'https://gitlab.com/fallback'},
    ]}}
    src = FirmwareSource(host='gitlab', repo='a/b', asset_name='firmware.bin')
    resolved = gitlab.resolved_asset(release, src)
    assert resolved.tag == 'v1'
    assert resolved.download_url == 'https://gitlab.com/-/project/releases/v1/firmware.bin'
    assert resolved.digest == ''  # GitLab's API carries no asset digest


def test_gitlab_resolved_asset_falls_back_to_url_without_direct_asset_url():
    release = {'tag_name': 'v1', 'assets': {'links': [
        {'name': 'firmware.bin', 'url': 'https://gitlab.com/fallback'},
    ]}}
    resolved = gitlab.resolved_asset(release, FirmwareSource(host='gitlab', repo='a/b'))
    assert resolved.download_url == 'https://gitlab.com/fallback'


def test_gitlab_resolved_asset_missing_raises():
    release = {'tag_name': 'v1', 'assets': {'links': []}}
    with pytest.raises(FirmwareError):
        gitlab.resolved_asset(release, FirmwareSource(host='gitlab', repo='a/b'))


def test_gitlab_is_allowed_download_host_gitlab_com_default():
    src = FirmwareSource(host='gitlab', repo='a/b')
    assert gitlab.is_allowed_download_host('gitlab.com', src)
    assert not gitlab.is_allowed_download_host('evil.example.com', src)


def test_gitlab_is_allowed_download_host_self_hosted():
    src = FirmwareSource(host='gitlab', host_url='https://gitlab.example.com', repo='a/b')
    assert gitlab.is_allowed_download_host('gitlab.example.com', src)
    # a release link pointing off-instance (allowed by GitLab's own data model
    # -- links can be arbitrary URLs) is refused, not just gitlab.com's host
    assert not gitlab.is_allowed_download_host('gitlab.com', src)
    assert not gitlab.is_allowed_download_host('some-cdn.example.net', src)


def test_gitlab_pinned_resolve_release_hits_release_by_tag_endpoint():
    """channel='pinned' should GET /releases/{tag}, not the list endpoint."""
    requested = {}

    class _FakeResponse:
        status_code = 200
        headers = {'etag': 'e1'}

        def json(self):
            return {'tag_name': 'v1.2', 'assets': {'links': []}}

    class _FakeClient:
        async def get(self, url, headers=None):
            requested['url'] = url
            return _FakeResponse()

    src = FirmwareSource(host='gitlab', repo='group/sub/project', channel='pinned', pinned_tag='v1.2')
    release_json, etag = asyncio.run(gitlab.resolve_release(_FakeClient(), 'group/sub/project', src, None))
    assert release_json['tag_name'] == 'v1.2'
    assert etag == 'e1'
    assert '/releases/v1.2' in requested['url']
    assert '/releases?' not in requested['url']


def test_gitlab_stable_resolve_release_hits_list_endpoint_and_takes_first():
    class _FakeResponse:
        status_code = 200
        headers = {'etag': 'e2'}

        def json(self):
            return [{'tag_name': 'v2.0'}, {'tag_name': 'v1.0'}]

    class _FakeClient:
        async def get(self, url, headers=None):
            return _FakeResponse()

    src = FirmwareSource(host='gitlab', repo='a/b', channel='stable')
    release_json, etag = asyncio.run(gitlab.resolve_release(_FakeClient(), 'a/b', src, None))
    assert release_json['tag_name'] == 'v2.0'  # first entry, not sorted client-side again
    assert etag == 'e2'


def test_gitlab_resolve_release_empty_list_raises():
    class _FakeResponse:
        status_code = 200
        headers = {'etag': ''}

        def json(self):
            return []

    class _FakeClient:
        async def get(self, url, headers=None):
            return _FakeResponse()

    with pytest.raises(FirmwareError):
        asyncio.run(gitlab.resolve_release(_FakeClient(), 'a/b', FirmwareSource(host='gitlab', repo='a/b'), None))
