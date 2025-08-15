from nicegui import PageArguments, ui


async def page_args_card(args: PageArguments):
    with ui.card().props('flat bordered'):
        with ui.card_section().props('header').classes('text-bold w-full'):
            ui.label('args')
            ui.separator()
        with ui.card_section().props('content').classes('w-full'):
            with ui.grid(columns=2):
                ui.label('path')
                ui.label(str(args.path))
                ui.label('path_parameters')
                ui.label(str(args.path_parameters))
                ui.label('query_parameters')
                ui.label(str(args.query_parameters))
                ui.label('data')
                ui.label(str(args.data))

# ***************************************************************************

