from nicegui import app, ui

from app.core.forwarding.forwarding import get_forwadings, update_forwadings
from app.core.forwarding.models import ForwardingModel, ForwardingModelList
from app.core.project import get_project


class ForwardingConfigCard:
    """Card for forwarding configuration."""

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.forwardings = get_forwadings(project_name)

        self.cols = [
            {'headerName': 'Name', 'field': 'id' },
            {'headerName': 'Method', 'field': 'forward_method' },
            {'headerName': 'URL', 'field': 'forward_url' },
        ]
        self.rows = []
        self.update_rows()
        with ui.card().classes('w-full') as self.card:
            # table with forwarding
            with ui.row().classes('w-full'):
                ui.label('Forwardings').classes('text-h6')
                ui.space()
                ui.button('Add', icon='add').props('color=primary').on_click(self.add_row)
                ui.button('Delete', icon='delete').props('color=red').on_click(self.delete_row)
            self.aggrid = ui.aggrid({
                'columnDefs': self.cols,
                'rowData': self.rows,
                'defaultColDef': {
                    'sortable': True,
                    'editable': True,
                },
                'rowSelection': 'single',
                'animateRows': True
            }).on('cellValueChanged', self.handle_cell_value_changed)


    def update_rows(self) -> None:
        """Update the rows in the table."""
        self.rows.clear()
        for k,v in self.forwardings.forwards.items():
           self.rows.append({
               'id': k,
               'forward_method': v.forward_method,
               'forward_url': v.forward_url,
           })


    def handle_cell_value_changed(self, event) -> None:
        """Handle cell value changed event."""
        row_data = event.args['data']
        colId = event.args['colId']
        if colId == 'id':
            # update the key in the forwardings dict
            old_key = event.args['oldValue'].strip()
            new_key = event.args['newValue'].strip()
            if old_key != new_key:
                self.forwardings.forwards[new_key] = self.forwardings.forwards.pop(old_key)
        else:
            # update the value in the forwardings dict
            if colId == 'forward_method':
                self.forwardings.forwards[row_data['id']].forward_method = row_data['forward_method']
            elif colId == 'forward_url':
                self.forwardings.forwards[row_data['id']].forward_url = row_data['forward_url']

        ForwardingModelList.model_validate(self.forwardings)
        ForwardingModel.model_validate(self.forwardings.forwards[row_data['id']])
        ForwardingModel.model_validate(self.forwardings.forwards[row_data['id']].)

        # save the changes
        self.forwardings = update_forwadings(self.project_name, self.forwardings)
        ui.notify(f"Saved forwardings: {row_data}")


    def add_row(self) -> None:
        """Add a new row to the table."""
        self.forwardings.forwards[''] = ForwardingModel()
        self.update_rows()
        ui.notify('Row added')
        self.aggrid.update()


    async def delete_row(self) -> None:
        """Delete the selected row from the table."""
        selected_row = await self.aggrid.get_selected_row()
        if not selected_row:
            ui.notify('No row selected')
            return
        del self.forwardings.forwards[selected_row['id']]

        # save the changes
        self.forwardings = update_forwadings(self.project_name, self.forwardings)

        # update the ui
        self.update_rows()
        self.aggrid.update()
        ui.notify(f"Row {selected_row['id']} deleted")
