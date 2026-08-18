"""
The token card's layout is a string contract against AuthToken: a renamed field
raises only when the form renders. These tests make that happen in CI.
"""
import datetime

from nicegui import ui
from niceview import ModelForm
from niceview.dataadapter import JsonListAdapter

from app.core.token.backend import create_token
from app.core.token.models import AuthToken
from app.core.token.ui import TokenListCard


def _card(tmp_path, *, last_use: bool) -> tuple[TokenListCard, JsonListAdapter, AuthToken]:
    adapter = JsonListAdapter(AuthToken, tmp_path / 'tokens.json')
    adapter.create(create_token(expires_in=datetime.timedelta(days=1), length=32))
    token = next(iter(adapter))
    if last_use:
        token.last_use_at = datetime.datetime.now(datetime.timezone.utc)
        adapter.update(token)
    card = TokenListCard.__new__(TokenListCard)   # no UI context needed for the parts under test
    card.adapter = adapter
    return card, adapter, token


def _render(card, adapter, token) -> ModelForm:
    key = next(iter(adapter.items()))[0]
    with ui.column():
        return ModelForm.from_adapter(
            AuthToken, adapter, key, autosave=True,
            actions=card._actions(), layout=TokenListCard._layout(token),
        ).render()


def test_the_layout_renders_every_field_and_action(tmp_path):
    card, adapter, token = _card(tmp_path, last_use=True)
    form = _render(card, adapter, token)
    assert set(form.widgets) == {'is_active', 'fingerprint', 'value', 'expires_at', 'created_at', 'last_use_at'}
    assert set(form.action_buttons) == {'delete', 'copy'}


def test_last_use_at_is_omitted_until_there_is_one(tmp_path):
    card, adapter, token = _card(tmp_path, last_use=False)
    form = _render(card, adapter, token)
    assert 'last_use_at' not in form.widgets
    assert 'created_at' in form.widgets, 'sanity: the other timestamps still render'


def test_delete_action_acts_on_the_form_it_was_given(tmp_path):
    """Pins our half of the wiring: the handler reads the token off `e.form.item`."""
    card, adapter, token = _card(tmp_path, last_use=False)
    form = _render(card, adapter, token)
    card.update_rows = lambda: None                     # the refreshable needs a UI context
    card.update_rows.refresh = lambda: None

    card._actions()['delete'].on_click(type('E', (), {'form': form})())
    assert list(adapter) == [], 'the action did not reach delete_token()'
