"""
File API tests — config/firmware download flow as used by arduino4iot.

HEAD /api/file/{project}/{device}/{filename}   — ETag-based cache check
GET  /api/file/{project}/{device}/{filename}   — download with conditional 304
PUT  /api/file/{project}/{device}/{filename}   — device uploads a file

The device sends If-None-Match and/or If-Modified-Since on subsequent
requests and expects 304 when the file has not changed (avoids unnecessary
downloads). Per RFC 7232 §3.3, If-None-Match takes precedence when both are
present.

File lookup: device-specific path first, project-level fallback if absent.
PUT always writes to the device-specific path.
"""
from email.utils import formatdate

import pytest
from pathlib import Path

from app.core.device.backend import get_file_path
from app.paths import project_dir
from app.config import app_config


FILE_CONTENT = "firmware=v1.2.3\nserver=https://example.com\n"


@pytest.fixture
def device_file(provisioned, projects_dir):
    """A config file in the device directory."""
    path = get_file_path(
        provisioned["project_name"],
        provisioned["device_name"],
        "config.txt",
        check_file_exists=False,
    )
    path.write_text(FILE_CONTENT)
    return path


@pytest.fixture
def project_file(provisioned, projects_dir):
    """A file in the project directory (fallback for devices without their own copy)."""
    path = project_dir(provisioned["project_name"]) / "default.txt"
    path.write_text("project-level default content")
    return path


# ---------------------------------------------------------------------------
# HEAD — auth
# ---------------------------------------------------------------------------

def test_head_no_auth_rejected(client, provisioned, device_file):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt"
    )
    assert resp.status_code == 401


def test_head_wrong_token_rejected(client, provisioned, device_file):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": "bearer " + "x" * 32},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# HEAD — ETag caching (arduino4iot uses If-None-Match to skip downloads)
# ---------------------------------------------------------------------------

def test_head_returns_etag(client, provisioned, device_file):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("etag")


def test_head_304_when_etag_matches(client, provisioned, device_file):
    """Second request with the same ETag must return 304 Not Modified."""
    resp1 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    etag = resp1.headers["etag"]

    resp2 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": etag,
        },
    )
    assert resp2.status_code == 304


def test_head_200_when_etag_differs(client, provisioned, device_file):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": "stale-etag-value",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# HEAD — Last-Modified / If-Modified-Since caching
# ---------------------------------------------------------------------------

def test_head_returns_last_modified(client, provisioned, device_file):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("last-modified")


def test_head_304_when_not_modified_since(client, provisioned, device_file):
    """Second request with If-Modified-Since == Last-Modified must return 304."""
    resp1 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    last_modified = resp1.headers["last-modified"]

    resp2 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 304


def test_head_200_when_modified_since(client, provisioned, device_file):
    """If-Modified-Since older than the file's mtime must return 200."""
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-Modified-Since": "Sat, 01 Jan 2000 00:00:00 GMT",
        },
    )
    assert resp.status_code == 200


def test_head_if_none_match_takes_precedence_over_if_modified_since(client, provisioned, device_file):
    """A stale ETag combined with a matching If-Modified-Since must still return
    200 — RFC 7232 §3.3 says If-None-Match alone decides when both are sent."""
    resp1 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    last_modified = resp1.headers["last-modified"]

    resp2 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": "stale-etag-value",
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 200


def test_head_304_when_etag_and_if_modified_since_both_match(client, provisioned, device_file):
    """A matching ETag combined with a matching If-Modified-Since returns 304."""
    resp1 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    etag = resp1.headers["etag"]
    last_modified = resp1.headers["last-modified"]

    resp2 = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": etag,
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 304


def test_head_200_when_invalid_if_modified_since(client, provisioned, device_file):
    """A malformed If-Modified-Since header must not raise — treated as no match."""
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-Modified-Since": "not-a-date",
        },
    )
    assert resp.status_code == 200


def test_head_mtime_goes_into_last_modified_not_date(client, provisioned, device_file):
    """Regression: get_headers() used to leak the file's mtime into Date
    instead of Last-Modified."""
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    mtime_date = formatdate(device_file.stat().st_mtime, usegmt=True)
    assert resp.headers["last-modified"] == mtime_date
    assert resp.headers.get("date") != mtime_date


def test_head_404_when_file_missing(client, provisioned, projects_dir):
    resp = client.head(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/nonexistent.bin",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET — download
# ---------------------------------------------------------------------------

def test_get_returns_file_content(client, provisioned, device_file):
    resp = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 200
    assert resp.text == FILE_CONTENT


def test_get_304_when_etag_matches(client, provisioned, device_file):
    resp1 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    etag = resp1.headers["etag"]

    resp2 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": etag,
        },
    )
    assert resp2.status_code == 304


def test_get_304_when_not_modified_since(client, provisioned, device_file):
    resp1 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    last_modified = resp1.headers["last-modified"]

    resp2 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 304


def test_get_200_when_modified_since(client, provisioned, device_file):
    resp = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-Modified-Since": "Sat, 01 Jan 2000 00:00:00 GMT",
        },
    )
    assert resp.status_code == 200
    assert resp.text == FILE_CONTENT


def test_get_if_none_match_takes_precedence_over_if_modified_since(client, provisioned, device_file):
    """A stale ETag combined with a matching If-Modified-Since must still return
    200 — RFC 7232 §3.3 says If-None-Match alone decides when both are sent."""
    resp1 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    last_modified = resp1.headers["last-modified"]

    resp2 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": "stale-etag-value",
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 200


def test_get_304_when_etag_and_if_modified_since_both_match(client, provisioned, device_file):
    resp1 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    etag = resp1.headers["etag"]
    last_modified = resp1.headers["last-modified"]

    resp2 = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={
            "Authorization": f"bearer {provisioned['device_token']}",
            "If-None-Match": etag,
            "If-Modified-Since": last_modified,
        },
    )
    assert resp2.status_code == 304


def test_get_project_fallback(client, provisioned, project_file):
    """If device has no own copy, the project-level file is served."""
    resp = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/default.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 200
    assert resp.text == "project-level default content"


# ---------------------------------------------------------------------------
# PUT — device uploads a file (e.g. crash dump, sensor log)
# ---------------------------------------------------------------------------

def test_put_creates_new_file(client, provisioned, projects_dir):
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/upload.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=b"uploaded content",
    )
    assert resp.status_code == 200
    path = get_file_path(
        provisioned["project_name"],
        provisioned["device_name"],
        "upload.txt",
    )
    assert path.read_text() == "uploaded content"


def test_put_overwrites_existing_file(client, provisioned, device_file):
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/config.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=b"new content",
    )
    assert resp.status_code == 200
    assert device_file.read_text() == "new content"


def test_put_no_auth_rejected(client, provisioned):
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/upload.txt",
        content=b"data",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT — size limit (spec: max_file_upload_size = 10 MiB)
# ---------------------------------------------------------------------------

def test_put_5mb_file_within_limit_accepted(client, provisioned, projects_dir):
    """A 5 MiB file must be accepted once the limit is raised to 10 MiB."""
    content = b"X" * (5 * 1024 * 1024)
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/medium.bin",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=content,
    )
    assert resp.status_code == 200


def test_put_too_large_rejected(client, provisioned, projects_dir):
    """Files exceeding max_file_upload_size are rejected with 413."""
    big_content = b"X" * (10 * 1024 * 1024 + 1)
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/big.bin",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=big_content,
    )
    assert resp.status_code == 413


def test_put_too_large_does_not_leave_partial_file(client, provisioned, projects_dir):
    """After a 413, no partial file should remain on disk (atomic upload)."""
    big_content = b"X" * (app_config.max_file_upload_size + 1)
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/partial.bin",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=big_content,
    )
    assert resp.status_code == 413
    partial_path = get_file_path(
        provisioned["project_name"],
        provisioned["device_name"],
        "partial.bin",
        check_file_exists=False,
    )
    assert not partial_path.exists()


# ---------------------------------------------------------------------------
# Filename validation (spec: reject path traversal and invalid chars)
# ---------------------------------------------------------------------------

def test_get_dotdot_filename_rejected(client, provisioned, projects_dir):
    """Filenames containing '..' are rejected with 400."""
    resp = client.get(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/..config",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
    )
    assert resp.status_code == 400


def test_put_invalid_filename_rejected(client, provisioned, projects_dir):
    """Filenames with spaces or special characters are rejected with 400."""
    resp = client.put(
        f"/api/file/{provisioned['project_name']}/{provisioned['device_name']}/bad%21name.txt",
        headers={"Authorization": f"bearer {provisioned['device_token']}"},
        content=b"data",
    )
    assert resp.status_code == 400
