from nicegui import ui
from niceview import ConflictError, StorageError
from niceview import ModelForm

from app.core.logging.backend import get_logging_adapter
from app.core.logging.models import LoggingConfig


class LoggingCard:
    """Content for the logging backend configuration card (caller provides the card/header)."""

    def __init__(self, project_name: str):
        self.adapter = get_logging_adapter(project_name)
        self.config = self.adapter.read()

        ui.markdown(LoggingConfig.Meta.description).classes('text-caption q-ma-none')

        self._render_backend('File', self.config.file)
        self._render_backend('Loki', self.config.loki)

    def _save(self) -> None:
        try:
            self.adapter.save(self.config)
        except (ConflictError, StorageError) as e:
            ui.notify(str(e), color='negative')

    def _render_backend(self, title: str, config) -> None:
        form = ModelForm.from_item(config, on_change=lambda e: self._save())
        marker = f'logging-{title.lower()}'
        with ui.card().classes('w-full').mark(marker):
            ui.label(title).classes('font-bold')
            form.render()
            for widget in form.widgets.values():
                widget.props('outlined dense').classes('w-full')
