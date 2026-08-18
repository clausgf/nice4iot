"""
The forwarding card's layout is a string contract against ForwardingConfig:
a renamed field raises only when the form renders. Same shape as test_token_card.
"""
from nicegui import ui
from niceview import ModelForm
from niceview.dataadapter import JsonListAdapter

from app.core.forwarding.models import ForwardingConfig
from app.core.forwarding.ui import ForwardingCard


def _card(tmp_path) -> tuple[ForwardingCard, JsonListAdapter]:
    adapter = JsonListAdapter(ForwardingConfig, tmp_path / 'forwarding.json')
    adapter.create(ForwardingConfig(name='influx', forward_url='http://example.com/write',
                                    forward_method='POST'))
    card = ForwardingCard.__new__(ForwardingCard)   # no UI context needed for the parts under test
    card.adapter = adapter
    return card, adapter


def _render(card, adapter) -> ModelForm:
    key = next(iter(adapter.items()))[0]
    with ui.column():
        return ModelForm.from_adapter(
            ForwardingConfig, adapter, key, autosave=True,
            actions=card._actions(), layout=ForwardingCard._layout(),
        ).render()


def test_the_layout_renders_every_field_and_action(tmp_path):
    card, adapter = _card(tmp_path)
    form = _render(card, adapter)
    assert set(form.widgets) == {'name', 'forward_method', 'forward_url'}
    assert set(form.action_buttons) == {'delete'}


def test_the_method_keeps_its_width_and_the_url_fills(tmp_path):
    """forward_method brings its own width, so it does not get niceview's even share;
    forward_url brings none and takes the rest."""
    card, adapter = _card(tmp_path)
    form = _render(card, adapter)
    assert 'w-1/4' in form.widgets['forward_method'].classes
    assert 'flex-1' in form.widgets['forward_url'].classes


def test_delete_action_acts_on_the_form_it_was_given(tmp_path):
    card, adapter = _card(tmp_path)
    form = _render(card, adapter)
    card.update_rows = lambda: None                     # the refreshable needs a UI context
    card.update_rows.refresh = lambda: None

    card._actions()['delete'].on_click(type('E', (), {'form': form})())
    assert list(adapter) == [], 'the action did not reach delete_forwarding()'
