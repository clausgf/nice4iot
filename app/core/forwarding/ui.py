from nicegui import ui
from niceview import FormAction, ModelForm

from app.core.forwarding.backend import get_forwarding_adapter
from app.core.forwarding.models import ForwardingConfig


class ForwardingCard:
    """Content for the forwarding configuration card (caller provides the card/header)."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.adapter = get_forwarding_adapter(project_name)

        ui.markdown(ForwardingConfig.Meta.description).classes('text-caption q-ma-none')
        self.update_rows()
        ui.button('Add Forwarding', icon='add').classes('w-full').on_click(self.add_row)

    def _actions(self) -> dict[str, FormAction]:
        return {
            'delete': FormAction(icon='delete', tooltip='Delete forwarding',
                                 props='color=negative',
                                 on_click=lambda e: self.delete_forwarding(e.form.item)),
        }

    @staticmethod
    def _layout() -> list:
        return [
            [':w-full items-center gap-2', 'name', '@delete:mb-0'],
            ['forward_method:w-1/4', 'forward_url'],
        ]

    @ui.refreshable
    def update_rows(self) -> None:
        """Update the rows in the table."""
        for key, _item in self.adapter.items():
            with ui.card().classes('w-full q-mb-md'):
                ModelForm.from_adapter(
                    ForwardingConfig, self.adapter, key, autosave=True,
                    base_props='outlined dense hide-bottom-space',
                    actions=self._actions(),
                    layout=self._layout(),
                ).render()

    def _unique_name(self, base: str = 'forwarding') -> str:
        existing = {item.name for item in self.adapter}
        if base not in existing:
            return base
        i = 1
        while f'{base}_{i}' in existing:
            i += 1
        return f'{base}_{i}'

    def add_row(self) -> None:
        """Add a new forwarding entry."""
        name = self._unique_name()
        self.adapter.create(ForwardingConfig(name=name, forward_url='http://example.com', forward_method='GET'))
        self.update_rows.refresh()
        ui.notify(f"Forwarding '{name}' added")

    def delete_forwarding(self, fwd: ForwardingConfig) -> None:
        """Delete a forwarding entry."""
        self.adapter.delete(self.adapter.key_from_item(fwd))
        project_name = getattr(self, 'project_name', None)
        if project_name:
            from app.health import clear_health
            clear_health(f'{project_name}:forwarding:{fwd.name}')
        self.update_rows.refresh()
        ui.notify(f"Forwarding '{fwd.name}' deleted")
