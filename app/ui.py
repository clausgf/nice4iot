"""Shared NiceGUI presentation helpers used across nice4iot's own UI and by extensions."""
from typing import Literal

from nicegui import ui


def config_expansion(title: str, *, value: bool = False, level: Literal['h6', 'subtitle1'] = 'h6') -> ui.expansion:
    """Foldable card header shared by every config-style card (General tab, global settings).

    nice4iot renders this around each card's content itself rather than
    letting each card build its own header, so the look stays uniform —
    including for extension-registered 'general'/global cards (see
    app.extensions.register_project_card() et al.).
    """
    return ui.expansion(title, value=value).classes('w-full q-mb-none').props(
        f'dense header-class="text-{level} font-bold"'
    )
