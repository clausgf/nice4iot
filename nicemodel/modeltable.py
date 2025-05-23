from typing import Any, Callable, Literal, Self, Union, Unpack
import typing_extensions
from pydantic import BaseModel, ValidationError
from nicegui import ui

from nicemodel.modelfield import NmFieldsMixin, NmFieldInfo


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

        self._create_field_names(self._model_cls, self.fields)
        self._create_field_infos(self._model_cls, self.field_infos)

                # modify the columns in place without creating a new list
        self._cols.clear()
        for field in self._field_names:
            field_info = self._ui_field_infos.get(field)
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
                row = {'__ui_row_id': i}
                for field in self._field_names:
                    field_info = self._ui_field_infos.get(field)
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
        self.widget = ui.table(columns=self._cols, rows=self._rows, row_key='__ui_row_id', **kwargs)
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
    field_infos: dict[str, NmFieldInfo] | None = None # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    props: str | None = None
    theme: str | None = None
    auto_size_columns: bool | None = None
    defaultColDef: dict | None = None
    rowSelection: Literal[None, 'single', 'multiple'] = None
    cell_renderers: dict[str, Callable[[Any], str]] = {}


class ModelGrid(NmFieldsMixin):
    """
    A AgGrid class that can be used to create tables for Pydantic models.
    """
    _model_cls: type[BaseModel]
    _list_model: list[BaseModel] | None = None
    #_model: list[BaseModel] | None = None
    widget: ui.aggrid | None = None
    fields: list[str] = []  # this is not the final list of fields, which is found in _fields
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

    _cols: list[dict[str, str]] = []
    _rows: list[dict[str, Any]] = []

    def __init__(self, model_cls: type[BaseModel], **kwargs: Unpack[_ModelGridOptionInputs]) -> None:
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

        self._create_field_names(self._model_cls, self.fields)
        self._create_field_infos(self._model_cls, self.field_infos)

        # modify the columns in place without creating a new list
        self._cols.clear()
        for field in self._field_names:
            field_info = self._ui_field_infos.get(field)
            if not field_info:
                raise ValueError(f"Field {field} not found in ui_field_infos")
            if field_info.hidden:
                # Skip hidden fields
                continue
            # Create a column for the field
            col = {
                'headerName': field_info.label,
                'field': field,
            }
            for k in ['aggrid_editable', 'aggrid_sortable']:
                v = getattr(field_info, k)
                if v is not None:
                    col[k.removeprefix('aggrid_')] = v
            # add the column
            self._cols.append(col)


    def update_rows(self) -> Self:
        """
        Re-Render the rows of the table.
        """
        self._rows.clear() # modify the rows in place without creating a new list
        if self._list_model:
            for i, model in enumerate(self._list_model):
                row = {'__ui_row_id': i}
                for field in self._field_names:
                    field_info = self._ui_field_infos.get(field)
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
        Render the table. If the model is given, it will be bound to the grid.
        """
        if list_model is not None:
            self.bind_model(list_model)
        
        self.update_rows()

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
        self.widget.on('cellValueChanged', self.handle_cell_value_changed)
        return self


    def handle_cell_value_changed(self, event) -> None:
        """
        Handle the cell value changed event to update the model with the new value.
        """
        # print(f"cellValueChanged: {event}")
        # GenericEventArguments(sender=<nicegui.elements.aggrid.AgGrid object at ...>, client=<nicegui.client.Client object at ...>,
        #  args={'value': 'John Doexfdsdf', 'oldValue': 'John Doe', 'newValue': 'John Doexfdsdf', 'rowIndex': 0, 
        #   'data': {'__ui_row_id': 0, 'name': 'John Doexfdsdf', 'age': 30}, 
        #   'source': 'edit', 'colId': 'name', 'selected': True, 'rowHeight': 28, 'rowId': '0'})
        row_index = event.args['rowIndex']
        # row_id = event.args['rowId']
        row_id = event.args['data']['__ui_row_id']
        field_name = event.args['colId']
        old_value = event.args['oldValue']
        new_value = event.args['newValue']

        # try to modify the model in place
        try:
            model = self._list_model[row_index]
        except IndexError:
            print(f"IndexError: {row_index} not in list_model")
            self.update_rows(self._list_model)
            return
        if not isinstance(model, self._model_cls):
            raise TypeError(f"model must be an instance of {self._model_cls}, got {type(model)}")
        if not hasattr(model, field_name):
            raise ValueError(f"Field {field_name} not found in model {model}")
        # update the model with the new value
        model.__setattr__(field_name, new_value)
        try:
            type(model).model_validate(model)
        except ValidationError as e:
            print(f"ValidationError: {e}")
            ui.notify(f"ValidationError: {e}", color='negative')
            # revert the value to the old value
            model.__setattr__(field_name, old_value)
            self.update_rows(self._list_model)
