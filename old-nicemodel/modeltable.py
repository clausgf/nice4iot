from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Literal, Self, TypeVar, Union, Unpack
import typing_extensions
from pydantic import BaseModel, ValidationError
from nicegui import ui
from nicegui.events import Handler, ClickEventArguments, ValueChangeEventArguments, handle_event
from nicegui.dataclasses import KWONLY_SLOTS

from nicemodel.modelfield import NmFieldsMixin, NmFieldInfo
from nicemodel.modelform import ModelForm


@dataclass(**KWONLY_SLOTS)
class TableItemEventArguments(ClickEventArguments):
    row_index: int
    item: Any


@dataclass(**KWONLY_SLOTS)
class TableItemFieldEventArguments(TableItemEventArguments):
    field_name: str
    new_value: Any


class _ModelTableOptionInputs(typing_extensions.TypedDict, total=False):
    """
    Kwarg Options for the ModelTable class.
    """
    fields: list[str] | str | None = None # this is not the final list of fields, which is found in _fields
    field_infos: dict[str, NmFieldInfo] | None = None # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    props: str | None = None
    title: str | None = None
    column_defaults: dict | None = None
    selection: Literal[None, 'single', 'multiple'] = None
    pagination: Union[int, dict] | None = None
    cell_renderers: dict[str, Callable[[Any], str]] = {}


class ModelTable(NmFieldsMixin):
    """
    A table class that can be used to create tables for Pydantic models.
    """
    _model_cls: type[BaseModel]
    #_model: list[BaseModel] | None = None
    widget: ui.table | None = None
    fields: list[str] = []  # this is not the final list of fields, which is found in _fields
    field_infos: dict[str, NmFieldInfo] = {} # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str = ''
    tailwind: str = ''
    style: str = ''
    props: str = ''
    title: str | None = None
    column_defaults: dict | None = None
    selection: Literal[None, 'single', 'multiple'] = None
    pagination: Union[int, dict] | None = None
    cell_renderers: dict[str, Callable[[Any], Any]] = {}

    _cols: list[dict[str, str]] = []
    _rows: list[dict[str, Any]] = []

    def __init__(self, model_cls: type[BaseModel], **kwargs: Unpack[_ModelTableOptionInputs]) -> None:
        self._model_cls = model_cls
        if not isinstance(self._model_cls, type) or not issubclass(self._model_cls, BaseModel):
            raise TypeError(f"cls must be a subclass of BaseModel, got {type(self._model_cls)}")

        # Initialize the field with the provided keyword arguments.
        for key, value in kwargs.items():
            if not key.startswith('_') and hasattr(self, key):
                # use default value if not provided, and if provided set the value
                if value is not None:
                    setattr(self, key, value)
            else:
                raise ValueError(f"Invalid field name: {key}")

        self.__init_field_names(self._model_cls, self.fields)
        self._init_field_infos(self._model_cls, self.field_infos)

                # modify the columns in place without creating a new list
        self._cols.clear()
        for field in self._field_names:
            field_info = self._nm_field_infos.get(field)
            if not field_info:
                raise ValueError(f"Field {field} not found in ui_field_infos")
            if field_info.hidden:
                # Skip hidden fields
                continue
            # Create a column for the field
            col = {
                'name': field,
                'label': field_info.label,
                'field': field,
            }
            for k in ['table_required', 'table_align', 'table_sortable', 'table_sort_order', 'table_style', 'table_classes']:
                v = getattr(field_info, k)
                if v is not None:
                    col[k.removeprefix('table_')] = v
            # add the column
            self._cols.append(col)


    def update_rows(self) -> Self:
        """
        Re-Render the rows of the table.
        """
        self._rows.clear() # modify the rows in place without creating a new list
        if self._list_model:
            for i, model in enumerate(self._list_model):
                row = {'__ui_row_index': i}
                for field in self._field_names:
                    field_info = self._nm_field_infos.get(field)
                    if not field_info:
                        raise ValueError(f"Field {field} not found in ui_field_infos")
                    if field_info.hidden:
                        # Skip hidden fields
                        continue
                    if field in self.cell_renderers:
                        row[field] = self.cell_renderers[field](getattr(model, field))
                    else:
                        row[field] = getattr(model, field)
                self._rows.append(row)
        if self.widget:
            self.widget.update()
        return self


    def bind_model(self, list_model: list[BaseModel]) -> Self:
        """
        Bind the table to a model instance.
        """
        if not isinstance(list_model, list) or not all(isinstance(i, self._model_cls) for i in list_model):
            raise TypeError(f"model must be a list of {self._model_cls}, got {type(list_model)}")
        self._list_model = list_model
        self.update_rows()
        return self


    def render(self, list_model: list[BaseModel] | None = None) -> Self:
        """
        Render the table. If the model is given, it will be bound to the table.
        """
        if list_model is not None:
            self.bind_model(list_model)

        self.update_rows()

        # render the table
        kwargs = { k: v for k in ['title', 'column_defaults', 'selection', 'pagination']
                   if ( v := getattr(self, k)) is not None }
        self.widget = ui.table(columns=self._cols, rows=self._rows, row_key='__ui_row_index', **kwargs)
        self.widget.classes(self.classes)
        self.widget.tailwind(self.tailwind)
        self.widget.style(self.style)
        self.widget.props(self.props)

        return self


class _ModelGridOptionInputs(typing_extensions.TypedDict, total=False):
    """
    Kwarg Options for the UiAgGrid class.
    """
    fields: list[str] | str | None = None # this is not the final list of fields, which is found in _fields
    exclude: list[str] | str | None = None
    field_infos: dict[str, NmFieldInfo] | None = None # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    props: str | None = None
    theme: str | None = None
    auto_size_columns: bool | None = None
    defaultColDef: dict | None = None
    rowSelection: Literal[None, 'single', 'multiple'] = None
    cell_renderers: dict[str, Callable[[Any], str]] | None = None
    cell_readers: dict[str, Callable[[str], Any]] | None = None
    title: str | None = None
    delete_button: str | None = None
    add_button: str | None = None
    edit_button: str | None = None
    refresh_button: str | None = None


T = TypeVar('T', bound=BaseModel)


class ModelGrid(NmFieldsMixin):
    """
    A AgGrid class that can be used to create tables for Pydantic models.
    """
    _item_type: type[T]
    _items: Iterable[T]
    _selection_handlers = []
    _change_handlers: List[Handler[TableItemEventArguments]] = []
    _delete_handler: Callable[[Iterable[T], int], bool] | None = None
    _edit_create_handler: Callable[[Iterable[T], int], bool] | None = None

    #_model: list[BaseModel] | None = None
    widget: ui.aggrid | None = None
    fields: list[str] | str = '__all__'  # this is not the final list of fields, which is found in _fields
    exclude: list[str] | str = []  # fields to exclude from the grid
    field_infos: dict[str, NmFieldInfo] = {} # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str = ''
    tailwind: str = ''
    style: str = ''
    props: str = ''
    theme: str | None = None
    auto_size_columns: bool | None = None
    defaultColDef: dict | None = None
    rowSelection: Literal[None, 'single', 'multiple'] = None
    cell_renderers: dict[str, Callable[[Any], Any]] = {}
    cell_readers: dict[str, Callable[[str], Any]] = {}
    title: str | None = None
    delete_button: str | None = None
    add_button: str | None = None
    edit_button: str | None = None
    refresh_button: str | None = None

    _cols: list[dict[str, str]] = []
    _rows: list[dict[str, Any]] = []


    def __init__(self, item_type: type[T], items: Iterable[BaseModel], **kwargs: Unpack[_ModelGridOptionInputs]) -> None:
        """
        Initialize the ModelGrid with a Pydantic model type and a list of items.
        The items must be instances of the model type.

        Note: item_type is needed to determine the type of the items in the grid in case of empty items.
        """
        # check parameter types
        if not isinstance(item_type, type) or not issubclass(item_type, BaseModel):
            raise TypeError(f"cls must be a subclass of BaseModel, got {type(item_type)}")
        if not isinstance(items, Iterable) or not all(isinstance(i, item_type) for i in items):
            raise TypeError(f"model must be a list of {item_type}, got {type(items)}")
        self._item_type = item_type
        self._items = items

        # initialize instance with a new copy of more complex data structures
        self._selection_handlers = []
        self._change_handlers = []
        self._cols = []
        self._rows = []

        # Initialize the field with the provided keyword arguments.
        for key, value in kwargs.items():
            if not key.startswith('_') and hasattr(self, key):
                # use default value if not provided, and if provided set the value
                if value is not None:
                    setattr(self, key, value)
            else:
                raise ValueError(f"Invalid field name: {key}")

        self.init_fields(self._item_type, self.fields, exclude=self.exclude, nm_field_info_args=self.field_infos)

        # create the table columns
        for field_name in self.field_names:
            field_info = self.get_field_info(field_name)
            if field_info.hidden:
                # Skip hidden fields
                continue
            # Create a column for the field
            col = {
                'headerName': field_info.label,
                'field': field_name,
            }
            for k in ['aggrid_editable', 'aggrid_sortable']:
                v = getattr(field_info, k)
                if v is not None:
                    col[k.removeprefix('aggrid_')] = v
            # add the column
            self._cols.append(col)


    def on_select(self, callback: Handler[ValueChangeEventArguments]) -> Self:
        """
        Add a callback to be invoked when the selection changes.
        The callback will receive a ValueChangeEventArguments with the new selection.
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        self._selection_handlers.append(callback)
        return self


    def on_change(self, callback: Handler[TableItemEventArguments]) -> Self:
        """
        Add a callback to be invoked when the form values change after successful validation. 
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        self._change_handlers.append(callback)
        return self


    def on_confirm_delete(self, callback: Callable[[int, BaseModel], bool] | None) -> Self:
        """
        **Instable:** Callback to be invoked when the delete button is clicked.

        The callback should return True if the item shall be deleted, or
        False if the deletion should be cancelled.

        Default if the callback is None is to delete the item without confirmation.

        As a side effect, this function will enable the delete button 
        with a 'Delete' label if it is None.
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        self.delete_button = 'Delete' if self.delete_button is None else self.delete_button
        self._delete_handler = callback
        return self


    def on_edit_create(self, callback: Callable[[int, BaseModel], bool] | None) -> Self:
        """
        **Instable:** Callback to be invoked when the create/edit button is clicked.

        The callback should return True if the item was edited successfully, or
        False if the edit was cancelled or failed.

        Default if the callback is None, is to show an edit dialog with the item's fields.

        Don't forget to enable the create and/or edit buttons.
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        self._edit_create_handler = callback
        return self


    def update_rows(self) -> Self:
        """
        Re-Render the rows of the table.
        """
        self._rows.clear() # modify the rows in place without creating a new list
        if self._items:
            for i, item in enumerate(self._items):
                row = {'__ui_row_index': i}
                for field_name in self.field_names:
                    field_info = self.get_field_info(field_name)
                    if field_info.hidden:
                        # Skip hidden fields
                        continue
                    if field_name in self.cell_renderers:
                        row[field_name] = self.cell_renderers[field_name](getattr(item, field_name))
                    else:
                        row[field_name] = getattr(item, field_name)
                self._rows.append(row)
        if self.widget:
            self.widget.update()
        return self


    def render(self, list_model: list[BaseModel] | None = None) -> Self:
        """
        Render the table. If the model is given, it will be bound to the grid.
        """
        self.update_rows()

        # render the title, add and delete buttons
        with ui.row().classes('w-full'):
            if self.title:
                ui.label(self.title).classes('text-h6')
            ui.space()
            if self.delete_button:
                ui.button(self.delete_button, icon='delete').props('color=red').on_click(self.delete_item)
            if self.add_button:
                ui.button(self.add_button, icon='add').props('color=primary').on_click(self.create_item)
            if self.edit_button:
                ui.button(self.edit_button, icon='edit').props('color=primary').on_click(self.update_item)
            if self.refresh_button:
                ui.button(self.refresh_button, icon='refresh').props('color=primary').on_click(lambda e: self.update_rows())

        # render the table
        kwargs = { k: v for k in ['theme', 'auto_size_columns']
                   if ( v := getattr(self, k)) is not None }
        config_dict = { 'columnDefs': self._cols, 'rowData': self._rows }
        if self.defaultColDef:
            config_dict['defaultColDef'] = self.defaultColDef
        if self.rowSelection:
            config_dict['rowSelection'] = self.rowSelection
        self.widget = ui.aggrid(config_dict, **kwargs)
        self.widget.classes(self.classes)
        self.widget.tailwind(self.tailwind)
        self.widget.style(self.style)
        self.widget.props(self.props)
        self.widget.on('selectionChanged', self._handle_selection_changed)
        self.widget.on('cellValueChanged', self._handle_cell_value_changed)

        return self


    async def _handle_selection_changed(self, event) -> None:
        """
        Handle the row selected event to call the selection handlers.
        """
        row = await self.widget.get_selected_row()
        # print(f"rowSelected: {event} {row}")
        # rowSelected: GenericEventArguments(sender=<nicegui.elements.aggrid.AgGrid object at 0x1123c1090>, client=<nicegui.client.Client object at 0x1123c02d0>, args={'source': 'rowClicked'}) {'__ui_row_index': 1, 'name': 'Jane Doe', 'age': 25, 'num': 43, 'is_active': True, 'is_admin': True, 'birthdatetime': '2025-06-10T10:19:47+00:00', 'gender': 'other'}
        e = ValueChangeEventArguments(sender=event.sender, client=event.client, value=row)
        for handler in self._selection_handlers:
            handle_event(handler, e)


    def _validation_errors(self, model_dict) -> List[str] | None:
        """
        Validate the model with the new value and return a list of validation errors.
        If there are no validation errors, return None.
        """
        field_errors = {}
        nonfield_errors = []
        try:
            # validate the model
            self._item_type.model_validate(model_dict)
        except ValidationError as e:
            for error in e.errors():
                error_was_handled = False
                # check if the error can be attributed to a known field
                for loc in error['loc']:
                    if loc in self._field_names:
                        field_name = loc
                        if field_name not in field_errors:
                            field_errors[field_name] = []
                        field_errors[field_name].append(error['msg'])
                        error_was_handled = True
                if not error_was_handled:
                    # if the error cannot be attributed to a known field, it is a non-field error
                    nonfield_errors.append(error['msg'])
            
            # collect the validation error messages
            errors = []
            for field, messages in field_errors.items():
                errors.append(f"{field}: {', '.join(messages)}")
            errors.extend(nonfield_errors)
            return errors
        return None


    def _handle_cell_value_changed(self, event) -> None:
        """
        Handle the cell value changed event to update the model with the new value
        when using inline editing (aggrid_editable).
        """
        # print(f"cellValueChanged: {event}")
        # GenericEventArguments(sender=<nicegui.elements.aggrid.AgGrid object at ...>, client=<nicegui.client.Client object at ...>,
        #  args={'value': 'John Doexfdsdf', 'oldValue': 'John Doe', 'newValue': 'John Doexfdsdf', 'rowIndex': 0, 
        #   'data': {'__ui_row_index': 0, 'name': 'John Doexfdsdf', 'age': 30}, 
        #   'source': 'edit', 'colId': 'name', 'selected': True, 'rowHeight': 28, 'rowId': '0'})
        row_index = event.args['rowIndex']
        # row_id = event.args['rowId']
        row_id = event.args['data']['__ui_row_index']
        field_name = event.args['colId']
        old_value = event.args['oldValue']
        new_value = event.args['newValue']

        if field_name in self.cell_readers:
            new_value = self.cell_readers[field_name](new_value)

        #  validate the model with the new value
        try:
            item = self._items[row_index]
            dumped_item = item.model_dump()
            dumped_item[field_name] = new_value
            errors = self._validation_errors(dumped_item)
        except IndexError:
            errors = [] if errors is None else errors
            errors.append(f"Internal error: Row index {row_index} not found in model list - try again")
        if not isinstance(item, self._item_type):
            raise TypeError(f"model must be an instance of {self._item_type}, got {type(item)}")
        if not hasattr(item, field_name):
            raise ValueError(f"Field {field_name} not found in model {item}")

        # update the model with the new value
        if errors is None or len(errors) == 0:
            setattr(item, field_name, new_value)
        else:
            # if there are validation errors, revert the value to the old value
            print(f"Validation errors: {errors}")
            ui.notify(f"Invalid edit: {old_value} -> {new_value} - {errors}", color='negative')
            self.update_rows()

        # call the change handlers
        tife = TableItemFieldEventArguments(
            sender=event.sender, client=event.client, 
            row_index=row_index, item=item,
            field_name=field_name, new_value=new_value,
        )
        for handler in self._change_handlers:
            handle_event(handler, tife)


    async def create_item(self, event: ClickEventArguments) -> None:
        """
        Add a new row to the grid and emit change events.
        Requires on_create_item handler or a model with a default constructor).
        """
        if self._edit_create_handler:
            row_index = await self._edit_create_handler(self._items, -1)
        else:
            row_index = await self.default_edit_create_handler(self._items, -1)

        if row_index >= 0:
            # call the change handlers
            tce = TableItemEventArguments(
                sender=event.sender, client=event.client, 
                row_index=row_index, item=self._items[row_index],
            )
            for handler in self._change_handlers:
                handle_event(handler, tce)

        self.update_rows()


    async def update_item(self, event: ClickEventArguments) -> None:
        """
        Edit the selected row in the grid.
        This method will emit an on_change event for the edited row.
        """
        # get the first selected row
        selected_row = await self.widget.get_selected_row()
        if not selected_row:
            ui.notify('No row selected for editing', color='negative')
            return
        row_index = selected_row['__ui_row_index']

        if self._edit_create_handler:
            row_index = await self._edit_create_handler(self._items, row_index)
        else:
            row_index = await self.default_edit_create_handler(self._items, row_index)

        if row_index >= 0:
            # call the change handlers
            tce = TableItemEventArguments(
                sender=event.sender, client=event.client, 
                row_index=row_index, item=self._items[row_index],
            )
            for handler in self._change_handlers:
                handle_event(handler, tce)

        self.update_rows()


    async def delete_item(self, event: ClickEventArguments) -> None:
        """
        Delete a row from the grid and emit change events.
        """
        # determine the selected rows to delete from the grid widget
        selected_rows = await self.widget.get_selected_rows()
        if not selected_rows:
            ui.notify('No row selected for deletion', color='negative')
            return

        # collect the row indices to delete
        del_indices = []
        for selected_row in selected_rows:
            row_index = selected_row['__ui_row_index']
            # check if the row index is valid
            if row_index < 0 or row_index >= len(self._items):
                print(f'Row index {row_index} out of range')
                return
            del_indices.append(row_index)

        # delete the indices in reverse order to avoid index errors
        del_indices.sort(reverse=True)
        for row_index in del_indices:
            item = self._items[row_index]

            if self._delete_handler:
                really_delete = self._delete_handler(row_index, item)
            else:
                really_delete = True

            if really_delete:
                del self._items[row_index]

                # call the change handlers
                tie = TableItemEventArguments(
                    sender=event.sender, client=event.client, 
                    row_index=row_index, item=item,
                )
                for handler in self._change_handlers:
                    handle_event(handler, tie)

        self.update_rows()


    async def default_edit_create_handler(self, items: Iterable[T], row_index: int) -> int:
        """
        Default edit handler that shows a dialog to edit the item.
        If the row_index is -1, a new item will be created (needs a default constructor).
        Returns the index edited or created on success, -1 otherwise.

        TODO: This should work with a key instead of a row index as the .
        """
        # create a copy of the item to edit or create
        do_create = row_index < 0 or row_index >= len(items)
        if do_create:
            item = self._item_type()
        else:
            item = items[row_index].model_copy(deep=True)

        form = ModelForm(item, classes='w-full')
        with ui.dialog().style('width: 400px') as dialog:
            with ui.card().classes('w-full'):
                form.render()
                ui.separator()
                with ui.row():
                    ui.space()
                    ui.button('Cancel', on_click=lambda: dialog.submit('cancel'))
                    ui.button('Create' if do_create else 'Ok', on_click=lambda: dialog.submit('confirm'))

        success = ('confirm' == await dialog)
        dialog.clear()

        if success:
            if do_create:
                # add the new item to the list
                items.append(item)
                row_index = len(items) - 1
            else:
                # update the existing item
                items[row_index] = item
            return row_index
        else:
            return -1
