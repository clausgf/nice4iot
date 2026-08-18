from niceview import ModelForm

from app.core.file.backend import get_file_adapter
from app.core.file.models import FileConfig


async def file_config_card(project_name: str) -> None:
    """Content for the per-project file transfer settings card (caller provides the card/header)."""
    adapter = get_file_adapter(project_name)
    # updated_at is the config's optimistic-lock timestamp, not a setting.
    form = ModelForm.from_adapter(FileConfig, adapter, autosave=True, exclude='updated_at',
                                  base_props='outlined dense hide-bottom-space',
                                  default_classes='w-full',
                                  profile='settings',)
    form.render()
