"""
`AuthToken.name` was removed in 0.28.0. A token file still carrying one must load
rather than be rejected, and must not get the key back on write.
"""
import datetime
import json

from niceview.dataadapter import JsonListAdapter
from pydantic import TypeAdapter

from app.core.token.backend import create_token, load_device_tokens, save_device_tokens
from app.core.token.models import AuthToken


_OLD_FILE = [{
    "name": "Factory floor",
    "is_active": True,
    "value": "OLDTOKENVALUE0123456789abcdefghij",
    "expires_at": "2099-01-01T00:00:00Z",
    "last_use_at": None,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2020-01-01T00:00:00Z",
}]


def test_a_file_with_a_label_still_loads(tmp_path):
    """The point of the removal being safe: the unknown key is ignored, not fatal."""
    path = tmp_path / '.provisioning.json'
    path.write_text(json.dumps(_OLD_FILE))
    tokens = list(JsonListAdapter(AuthToken, path))
    assert len(tokens) == 1
    assert tokens[0].value == "OLDTOKENVALUE0123456789abcdefghij"
    assert tokens[0].is_active is True
    assert not hasattr(tokens[0], 'name')


def test_a_write_drops_the_label(tmp_path):
    path = tmp_path / '.provisioning.json'
    path.write_text(json.dumps(_OLD_FILE))

    adapter = JsonListAdapter(AuthToken, path)
    _key, token = next(iter(adapter.items()))
    token.is_active = False
    adapter.update(token)

    on_disk = json.loads(path.read_text())
    assert on_disk[0]['is_active'] is False, 'the edit was not written'
    assert 'name' not in on_disk[0], 'the label survived the write'


def test_a_new_token_writes_no_name(tmp_path):
    path = tmp_path / '.provisioning.json'
    adapter = JsonListAdapter(AuthToken, path)
    adapter.create(create_token(expires_in=datetime.timedelta(days=1), length=32))
    assert 'name' not in json.loads(path.read_text())[0]

    # save_device_tokens serialises through a TypeAdapter, not through the adapter.
    dumped = json.loads(TypeAdapter(list[AuthToken]).dump_json(
        [create_token(expires_in=datetime.timedelta(days=1), length=32)]))
    assert 'name' not in dumped[0]


def test_device_tokens_load_and_shed_the_label(projects_dir):
    """The device-token path uses its own load/save pair rather than the adapter."""
    from tests.conftest import setup_project
    from app.core.device.backend import create_device
    from app.core.device.models import Device
    from app.core.token.backend import get_device_token_filename

    project, _ = setup_project('proj_tok')
    create_device(Device(name='dev_tok', project_name=project.name))

    path = get_device_token_filename(project.name, 'dev_tok')
    path.write_text(json.dumps(_OLD_FILE))

    tokens = load_device_tokens(project.name, 'dev_tok')
    assert len(tokens) == 1, 'a file with a label must not be discarded'

    save_device_tokens(project.name, 'dev_tok', tokens)
    assert 'name' not in json.loads(path.read_text())[0]
