import datetime
import json

from nicegui import ui
from niceview.dataadapter import JsonListAdapter
from niceview.form import ModelForm

from app.core.token.backend import create_token
from app.core.token.models import AuthToken

DEFAULT_TOKEN_LENGTH = 64
DEFAULT_TOKEN_EXPIRY = datetime.timedelta(days=7)


class TokenListCard:
    """
    Reusable card for managing a list of AuthTokens via a JsonListAdapter.

    Works for both provisioning tokens (show_name=True) and device bearer tokens
    (show_name=False).
    """

    def __init__(self, adapter: JsonListAdapter,
                 show_name: bool = True,
                 allow_add: bool = True,
                 token_length: int = DEFAULT_TOKEN_LENGTH,
                 expires_in: datetime.timedelta = DEFAULT_TOKEN_EXPIRY):
        self.adapter = adapter
        self.show_name = show_name
        self.token_length = token_length
        self.expires_in = expires_in

        self.update_rows()
        if allow_add:
            ui.button('Add Token', icon='add').props('color=primary w-full').on_click(self.add_token)

    @ui.refreshable
    def update_rows(self) -> None:
        for key, item in self.adapter.items():
            form = ModelForm.from_adapter(AuthToken, self.adapter, key, autosave=True)
            with ui.card().classes('w-full q-mb-md'):
                with ui.row().classes('w-full items-center'):
                    form.render_field('is_active', label='', tooltip='Active')
                    if self.show_name:
                        form.render_field('name').classes('grow').props('outlined dense hide-bottom-space')
                    ui.button(icon='delete').props('color=negative dense flat').on_click(
                        lambda _, token=item: self.delete_token(token)
                    )
                with ui.row().classes('w-full items-center'):
                    form.render_field('value').classes('grow').props('outlined dense hide-bottom-space')
                    ui.button(icon='content_copy').props('dense flat').on('click', handler=lambda: (
                        ui.clipboard.write(form.item.value),
                        ui.notify('Token copied to clipboard', type='positive')
                    ))
                with ui.row().classes('w-full'):
                    form.render_field('expires_at').props('outlined dense hide-bottom-space')
                    form.render_field('created_at').props('outlined dense hide-bottom-space')
                    if form.item.last_use_at is not None:
                        form.render_field('last_use_at').props('outlined dense hide-bottom-space')
                form.render_nonfield_errors()

    def _unique_name(self, base: str = 'token') -> str:
        existing = {item.name for item in self.adapter}
        if base not in existing:
            return base
        i = 1
        while f'{base}-{i}' in existing:
            i += 1
        return f'{base}-{i}'

    def add_token(self) -> None:
        name = self._unique_name() if self.show_name else ''
        new_token = create_token(expires_in=self.expires_in, length=self.token_length, name=name)
        self.adapter.create(new_token)
        self.update_rows.refresh()
        ui.notify(f"Token '{name}' added" if name else "Token added")

    def delete_token(self, token: AuthToken) -> None:
        self.adapter.delete(self.adapter.key_from_item(token))
        self.update_rows.refresh()
        label = token.name or token.value[:8] + '...'
        ui.notify(f"Token '{label}' deleted")
