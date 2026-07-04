from nicegui import ui
from niceview.form import ModelForm

from app.core.forwarding.backend import get_forwarding_adapter
from app.core.forwarding.models import ForwardingConfig


class ForwardingCard:
    """Card for forwarding configuration."""

    def __init__(self, project_name: str):
        self.adapter = get_forwarding_adapter(project_name)

        with ui.expansion('Forwarding').classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
            ui.markdown(ForwardingConfig.Meta.description).classes('text-caption q-ma-none')
            self.update_rows()
            ui.button('Add Forwarding', icon='add').props('color=primary w-full').on_click(self.add_row)

    @ui.refreshable
    def update_rows(self) -> None:
        """Update the rows in the table."""
        for key, item in self.adapter.items():
            form = ModelForm.from_adapter(ForwardingConfig, self.adapter, key, autosave=True)

            with ui.card().classes('w-full q-mb-md'):
                with ui.row().classes('w-full items-center'):
                    form.render_field('name').classes('grow').props('outlined dense hide-bottom-space')
                    ui.button(icon='delete').props('color=negative dense flat').on_click(
                        lambda _, fwd=item: self.delete_forwarding(fwd)
                    )
                with ui.row().classes('w-full'):
                    form.render_field('forward_method').classes('w-1/4 q-mr-sm').props('outlined dense hide-bottom-space')
                    form.render_field('forward_url').classes('grow').props('outlined dense hide-bottom-space')
                form.render_nonfield_errors()

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
        self.update_rows.refresh()
        ui.notify(f"Forwarding '{fwd.name}' deleted")
