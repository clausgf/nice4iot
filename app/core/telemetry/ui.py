from nicegui import ui
from niceview import ConflictError
from niceview.form import ModelForm

from app.core.telemetry.backend import get_telemetry_adapter
from app.core.telemetry.models import TelemetryConfig


class TelemetryCard:
    """Card for telemetry backend configuration."""

    def __init__(self, project_name: str):
        self.adapter = get_telemetry_adapter(project_name)
        self.config = self.adapter.read()

        with ui.expansion('Telemetry').classes('w-full q-mb-none').props('dense header-class="text-h6 font-bold"'):
            ui.markdown(TelemetryConfig.Meta.description).classes('text-caption q-ma-none')
            backend_form = ModelForm.from_item(self.config, on_change=lambda e: self._on_backend_change())
            backend_form.render_field('backend').props('outlined dense').classes('w-full')
            self._render_config()

    def _save(self) -> None:
        try:
            self.adapter.save(self.config)
        except ConflictError as e:
            ui.notify(str(e), color='negative')

    def _on_backend_change(self) -> None:
        self._save()
        self._render_config.refresh()

    @ui.refreshable
    def _render_config(self) -> None:
        if self.config.backend == 'none':
            return
        sub_config = getattr(self.config, self.config.backend)
        form = ModelForm.from_item(sub_config, on_change=lambda e: self._save())
        with ui.card().classes('w-full q-mt-sm'):
            form.render()
            for widget in form.widgets.values():
                widget.props('outlined dense').classes('w-full')
