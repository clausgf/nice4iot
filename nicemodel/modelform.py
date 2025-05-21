from typing import Unpack
import typing_extensions
from pydantic import BaseModel
from nicegui import ui

from nicemodel.modelfield import NmFieldsMixin, NmFieldInfo


class _ModelFormOptionInputs(typing_extensions.TypedDict, total=False):
    """
    Kwarg Options for the UiForm class.
    """
    fields: list[str] | str | None = None
    field_infos: dict[str, NmFieldInfo] | None = None
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    props: str | None = None


class ModelForm(NmFieldsMixin):
    """
    A form class that can be used to create forms for Pydantic models.
    """

    _model_cls: type[BaseModel]
    _model: BaseModel | None = None
    _widgets: dict[str, ui.element] = {}
    _widget_lookup: dict[type, str] = {
        str: 'ui.input',
        int: 'ui.number',
        float: 'ui.number',
        bool: 'checkbox',
    }
    fields: list[str] = []  # this is not the final list of fields, which is found in _fields
    field_infos: dict[str, NmFieldInfo] = {} # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str = ''
    tailwind: str = ''
    style: str = ''
    props: str = ''

    def __init__(self, model_cls: type[BaseModel], **kwargs: Unpack[_ModelFormOptionInputs]):
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

    def bind_model(self, model: BaseModel):
        """
        Bind the form to a model instance.
        This will update the form fields with the values from the model.
        """
        if not isinstance(model, self._model_cls):
            raise TypeError(f"model must be an instance of {self._model_cls}, got {type(model)}")
        self._model = model
        if self._widgets:
            for field in self._field_names:
                field_info = self._ui_field_infos.get(field)
                if not field_info:
                    raise ValueError(f"Field {field} not found in ui_field_infos")
                if field in self._widgets:
                    self._widgets[field].bind_value(model, field)

    def _get_field_widget_cls_from_type(self, ui_field_type: type) -> str:
        """
        Get the widget type for a field based field type.
        """
        return self._widget_lookup.get(ui_field_type, 'ui.input')

    def render(self, model: BaseModel | None = None):
        """
        Render the form. If the model is given, it will be bound to the form.
        """
        self._widgets = {}
        for field in self._field_names:
            field_info = self._ui_field_infos.get(field)
            if not field_info:
                raise ValueError(f"Field {field} not found in ui_field_infos")
            if field_info.hidden:
                # Skip hidden fields
                continue
            if not field_info.editable:
                # Render a non-editable field
                self._widgets[field] = ui.label(field_info.label)
                continue
            # Render an editable field based on its widget class
            widget_cls = field_info.form_widget_cls
            if not widget_cls:
                raise ValueError(f"Widget class not found for field {field}")
            if widget_cls == 'ui.input':
                # Render an input field
                # collect non-none arguments from ['label', 'placeholder', 'password', 'password_toggle_button', 'autocomplete']
                kwargs = {k: v 
                          for k in ['label', 'placeholder', 'password', 'password_toggle_button', 'autocomplete']
                          if ( v := getattr(field_info, k)) is not None}
                #print(f"{field}/{field_info} -> ui.input({kwargs})")
                self._widgets[field] = ui.input(**kwargs)
            elif widget_cls == 'ui.number':
                # Render a number field
                kwargs = { k: v for k in ['label', 'placeholder', 'min', 'max', 'precision', 'step', 'prefix', 'suffix', 'format']
                           if ( v := getattr(field_info, k)) is not None }
                #print(f"{field}/{field_info} -> ui.input({kwargs})")
                self._widgets[field] = ui.number(**kwargs)
            elif widget_cls == 'checkbox':
                # Render a checkbox
                self._widgets[field] = ui.checkbox(label=field_info.label)
            else:
                raise ValueError(f"Invalid widget class: {widget_cls}")
            self._widgets[field].classes(self.classes)
            self._widgets[field].tailwind(self.tailwind)
            self._widgets[field].style(self.style)
            self._widgets[field].props(self.props)

            self._widgets[field].on('blur', self.handle_field_changed)

        # Bind the model to the form
        if model is not None:
            self.bind_model(model)

    def handle_field_changed(self, event) -> None:
        """
        Handle the cell value changed event to update the model with the new value.
        """
        print(f"changed: {event}")
        # GenericEventArguments(sender=<nicegui.elements.aggrid.AgGrid object at ...>, client=<nicegui.client.Client object at ...>,
        #  args={'value': 'John Doexfdsdf', 'oldValue': 'John Doe', 'newValue': 'John Doexfdsdf', 'rowIndex': 0, 
        #   'data': {'__ui_row_id': 0, 'name': 'John Doexfdsdf', 'age': 30}, 
        #   'source': 'edit', 'colId': 'name', 'selected': True, 'rowHeight': 28, 'rowId': '0'})
