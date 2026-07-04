from nicegui import PageArguments, ui


async def build_dialog(title: str, message: str, buttons: list[str]) -> str:
    """
    Show a modal confirmation dialog and return the label of the clicked button.

    Button spec format: optional prefix + label.
    Prefix '-' renders the button in negative/red color.
    Prefix '|N' is ignored (legacy width hint).
    """
    def _parse(spec: str) -> tuple[str, str]:
        if spec.startswith('-'):
            return spec[1:], 'negative'
        if spec.startswith('|'):
            rest = spec.lstrip('|0123456789')
            return rest, 'secondary'
        return spec, 'primary'

    with ui.dialog() as dialog, ui.card():
        ui.label(title).classes('text-h6')
        ui.label(message)
        with ui.row().classes('w-full place-content-end q-mt-sm'):
            for spec in buttons:
                label, color = _parse(spec)
                ui.button(label).props(f'color={color}').on_click(lambda _, lbl=label: dialog.submit(lbl))

    return await dialog

