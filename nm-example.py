from typing import Annotated
from pydantic import BaseModel, Field
from nicegui import ui

from nicemodel.modelfield import NmField
from nicemodel.modelform import ModelForm
from nicemodel.modeltable import ModelGrid, ModelTable

class User(BaseModel):
    name: Annotated[str, Field(max_length=30, title="Name", description="Full name of the user", extra_argument="abc"), {'testkey': 'testvalue'}]
    age: Annotated[int, NmField(min=0, max=150, label="User's Age")]
    num: int


with ui.row():
    user_form = ModelForm(User, classes='w-full')
    with ui.card():
        ui.label('Example for a User Form:')
        user_form.render()
    user = User(name='John Doe', age=30, num=42)
    user_form.bind_model(user)

    with ui.card():
        ui.label('Binding example - Values of the User Form fields:')
        ui.label().bind_text_from(user, 'name')
        ui.label().bind_text_from(user, 'age')
        ui.label().bind_text_from(user, 'num')
        with ui.row():
            ui.button('num++', on_click=lambda: setattr(user, 'num', user.num + 1))
            ui.button('num--', on_click=lambda: setattr(user, 'num', user.num - 1))

user_list = [user, User(name='Jane Doe', age=25, num=43)]#, User(name='Alice', age=28, num=44), User(name='Bob', age=35, num=45), User(name='Charlie', age=40, num=46), User(name='Dave', age=45, num=47), User(name='Eve', age=50, num=48), User(name='Frank', age=55, num=49), User(name='Grace', age=60, num=50)]

user_table_1 = ModelTable(User, fields=['name', 'age', 'num'], classes='w-full')
with ui.card():
    ui.label('Example for a simple Table:')
    user_table_1.render(user_list)

user_table_2 = ModelTable(User, fields=['name', 'age', 'num'], title='Table Title', selection='single', pagination=5, classes='w-full')
with ui.card():
    ui.label('Example for a Table with title, selection and pagination:')
    user_table_2.render(user_list)
user_table_2.widget.on_select(lambda e: ui.notify(f'selected: {e.selection}'))

user_aggrid_1 = ModelGrid(User, fields=['name', 'age', 'num'], classes='w-full')
with ui.card().classes('w-full'):
    ui.label('Example for a simple AgGrid:')
    user_aggrid_1.render()
user_aggrid_1.bind_model(user_list)

user_aggrid_2 = ModelGrid(User, fields=['name', 'age'], defaultColDef = {'sortable': True, 'editable': True}, rowSelection='single', classes='w-full')
with ui.card().classes('w-full'):
    ui.label('Example for an editable AgGrid:')
    user_aggrid_2.render(user_list)
user_aggrid_2.widget.on('rowSelected', lambda e: ui.notify(f'row {e.args["rowIndex"]} selected={e.args["selected"]}: {e.args}'))

ui.run()
