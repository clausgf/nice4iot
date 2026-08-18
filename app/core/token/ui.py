import datetime
from collections.abc import Callable

from nicegui import ui
from niceview.dataadapter import JsonListAdapter
from niceview import Field, FormAction, FormActionEventArguments, ModelForm

from app.core.token.backend import create_token
from app.core.token.models import AuthToken

DEFAULT_TOKEN_LENGTH = 64
DEFAULT_TOKEN_EXPIRY = datetime.timedelta(days=7)


class TokenListCard:
    """
    Reusable card for managing a list of AuthTokens via a JsonListAdapter.

    One shape for both kinds of token, provisioning and device bearer.
    """

    def __init__(self, adapter: JsonListAdapter,
                 allow_add: bool = True,
                 token_length: int | Callable[[], int] = DEFAULT_TOKEN_LENGTH,
                 expires_in: datetime.timedelta | Callable[[], datetime.timedelta] = DEFAULT_TOKEN_EXPIRY):
        self.adapter = adapter
        self.token_length = token_length
        self.expires_in = expires_in

        self.update_rows()
        if allow_add:
            ui.button('Add Token', icon='add').classes('w-full').on_click(self.add_token)

    def _actions(self) -> dict[str, FormAction]:

        def _copy(e: FormActionEventArguments) -> None:
            ui.clipboard.write(e.form.item.value)
            ui.notify('Token copied to clipboard', type='positive')

        return {
            'delete': FormAction(icon='delete', tooltip='Delete token',
                                 props='color=negative',
                                 on_click=lambda e: self.delete_token(e.form.item)),
            'copy': FormAction(icon='content_copy', tooltip='Copy to clipboard',
                               on_click=_copy),
        }

    @staticmethod
    def _layout(item: AuthToken) -> list:
        timestamps_line = ['expires_at', 'created_at']
        if item.last_use_at is not None:
            timestamps_line.append('last_use_at')
        return [
            ['is_active:shrink', 'fingerprint', '@delete:mb-0'],
            ['value', '@copy:mb-0'],
            timestamps_line,
        ]

    @ui.refreshable
    def update_rows(self) -> None:
        for key, item in self.adapter.items():
            with ui.card().classes('w-full q-mb-md'):
                ModelForm.from_adapter(
                    AuthToken, self.adapter, key, autosave=True,
                    base_props='hide-bottom-space',
                    actions=self._actions(),
                    layout=self._layout(item),
                ).render()

    def add_token(self) -> None:
        length = self.token_length() if callable(self.token_length) else self.token_length
        expires = self.expires_in() if callable(self.expires_in) else self.expires_in
        self.adapter.create(create_token(expires_in=expires, length=length))
        self.update_rows.refresh()
        ui.notify("Token added")

    def delete_token(self, token: AuthToken) -> None:
        self.adapter.delete(self.adapter.key_from_item(token))
        self.update_rows.refresh()
        # The first characters of the value are what identifies a token on screen now
        # that the label is gone — and it is being deleted, so it is no longer a secret.
        ui.notify(f"Token '{token.value[:8]}…' deleted")
