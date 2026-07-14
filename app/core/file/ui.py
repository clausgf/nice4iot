from niceview.form import ModelForm

from app.core.file.backend import get_file_adapter
from app.core.file.models import FileConfig


def FileConfigCard(project_name: str) -> None:
    """Content for the per-project file transfer settings card (caller provides the card/header)."""
    adapter = get_file_adapter(project_name)
    form = ModelForm.from_adapter(FileConfig, adapter, autosave=True)
    form.render_field('max_upload_size').props('outlined dense').classes('w-full')
    form.render_field('mqtt_check_interval_s').props('outlined dense').classes('w-full')
    form.render_field('mqtt_qos').props('outlined dense').classes('w-full')
    form.render_field('mqtt_retain').classes('w-full')
