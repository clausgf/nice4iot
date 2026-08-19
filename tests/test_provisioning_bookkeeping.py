"""
Provisioning bookkeeping — each device records which provisioning token it last
used, so operators can find devices affected by a soon-expiring token.

The device stores a non-reversible fingerprint of the token (not the shared
secret) plus the token's expiry, filterable directly on the device record.
"""
import datetime

from app.core.device.backend import device_provision, get_device
from app.core.token.backend import create_token, get_provisioning_token_adapter
from app.core.token.models import token_fingerprint
from tests.conftest import setup_project


# ---------------------------------------------------------------------------
# token_fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_is_deterministic_and_short():
    fp1 = token_fingerprint("some-secret-token-value-abc")
    fp2 = token_fingerprint("some-secret-token-value-abc")
    assert fp1 == fp2
    assert len(fp1) == 12
    # not the raw secret
    assert fp1 not in "some-secret-token-value-abc"


def test_fingerprint_differs_per_value():
    assert token_fingerprint("aaaa") != token_fingerprint("bbbb")


def test_fingerprint_of_empty_is_empty():
    assert token_fingerprint("") == ""


# ---------------------------------------------------------------------------
# AuthToken.fingerprint field — derived, read-only, always in sync with value
# ---------------------------------------------------------------------------

def test_authtoken_fingerprint_derived_on_construction():
    from app.core.token.models import AuthToken
    t = create_token(datetime.timedelta(days=1), length=32)
    assert t.fingerprint == token_fingerprint(t.value)
    assert AuthToken().fingerprint == ""  # empty value -> empty fingerprint


def test_authtoken_fingerprint_recomputes_on_value_edit():
    """The UI form assigns fields in place; validate_assignment must resync."""
    t = create_token(datetime.timedelta(days=1), length=32)
    t.value = "a-brand-new-token-value-1234567890"
    assert t.fingerprint == token_fingerprint("a-brand-new-token-value-1234567890")


def test_authtoken_fingerprint_ignores_stored_value_on_load():
    from app.core.token.models import AuthToken
    now = datetime.datetime.now(datetime.timezone.utc)
    t = AuthToken.model_validate({
        "value": "loaded-token-value-abcdefabcdef",
        "expires_at": now, "created_at": now, "updated_at": now,
        "fingerprint": "STALEVALUE",  # hand-edited / outdated
    })
    assert t.fingerprint == token_fingerprint("loaded-token-value-abcdefabcdef")


def test_authtoken_fingerprint_is_persisted(tmp_path):
    from niceview.dataadapter import JsonListAdapter
    from app.core.token.models import AuthToken
    import json
    path = tmp_path / ".provisioning.json"
    adapter = JsonListAdapter(AuthToken, path)
    tok = create_token(datetime.timedelta(days=1), length=32)
    adapter.create(tok)
    on_disk = json.loads(path.read_text())[0]
    assert on_disk["fingerprint"] == token_fingerprint(tok.value)


# ---------------------------------------------------------------------------
# device_provision records the token identity
# ---------------------------------------------------------------------------

def test_provision_records_token_fingerprint_and_expiry(projects_dir):
    project, prov_value = setup_project(
        "proj_bk", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    # Recover the AuthToken object to know its expiry.
    prov_token = next(t for _, t in get_provisioning_token_adapter("proj_bk").items())

    device_provision(project, "dev_bk", provisioning_token=prov_token)

    device = get_device("proj_bk", "dev_bk")
    assert device.last_provisioning_token_fingerprint == token_fingerprint(prov_value)
    assert device.last_provisioning_token_expires_at == prov_token.expires_at


def test_provision_without_token_records_nothing(projects_dir):
    """Backwards-compatible: callers that omit the token leave the fields empty."""
    project, _ = setup_project(
        "proj_bk2", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    device_provision(project, "dev_bk2")
    device = get_device("proj_bk2", "dev_bk2")
    assert device.last_provisioning_token_fingerprint == ""
    assert device.last_provisioning_token_expires_at is None


def test_reprovision_updates_to_the_token_used(projects_dir):
    """When a device is re-provisioned with a different token, the record follows."""
    project, _ = setup_project(
        "proj_bk3", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    adapter = get_provisioning_token_adapter("proj_bk3")
    token_a = next(t for _, t in adapter.items())
    token_b = create_token(datetime.timedelta(days=30), length=64)
    adapter.create(token_b)

    device_provision(project, "dev_bk3", provisioning_token=token_a)
    assert get_device("proj_bk3", "dev_bk3").last_provisioning_token_fingerprint \
        == token_fingerprint(token_a.value)

    device_provision(project, "dev_bk3", provisioning_token=token_b)
    device = get_device("proj_bk3", "dev_bk3")
    assert device.last_provisioning_token_fingerprint == token_fingerprint(token_b.value)
    assert device.last_provisioning_token_expires_at == token_b.expires_at


# ---------------------------------------------------------------------------
# Full API path + correlation
# ---------------------------------------------------------------------------

def test_api_provision_records_token_and_correlates(client, project_autoapprove):
    """Provisioning via the API records a fingerprint that matches the one the
    project's provisioning token would display — the operator's correlation path."""
    project, prov_value = project_autoapprove
    resp = client.post("/api/provision", json={
        "projectName": project.name,
        "deviceName": "e32_bk",
        "provisioningToken": prov_value,
    })
    assert resp.status_code == 200

    device = get_device(project.name, "e32_bk")
    assert device.last_provisioning_token_fingerprint == token_fingerprint(prov_value)
    assert device.last_provisioning_token_expires_at is not None


def test_find_devices_affected_by_expiring_token(projects_dir):
    """The operator query: given a soon-expiring provisioning token, list the
    devices carrying it. Answerable from the device records alone."""
    project, _ = setup_project(
        "proj_exp", is_autocreate_devices=True, is_provisioning_autoapproval=True)
    adapter = get_provisioning_token_adapter("proj_exp")
    soon = create_token(datetime.timedelta(days=2), length=64)
    later = create_token(datetime.timedelta(days=90), length=64)
    adapter.create(soon)
    adapter.create(later)

    device_provision(project, "dev_soon_a", provisioning_token=soon)
    device_provision(project, "dev_soon_b", provisioning_token=soon)
    device_provision(project, "dev_later", provisioning_token=later)

    from app.core.device.backend import get_devices
    cutoff = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    affected = sorted(
        d.name for d in get_devices("proj_exp")
        if d.last_provisioning_token_expires_at
        and d.last_provisioning_token_expires_at <= cutoff
    )
    assert affected == ["dev_soon_a", "dev_soon_b"]
