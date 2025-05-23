from typing import List, Literal, Unpack
from pydantic import BaseModel
import typing_extensions


class _NmFieldInfoInputs(typing_extensions.TypedDict, total=False):
    """
    This class exists solely to add type checking for the `**kwargs` in `UiFieldInfo.from_field`.
    This idea is from the pydantic source code, class _FromFieldInfoInputs
    """
    label: str | None
    placeholder: str | None
    required: bool | None
    hidden: bool | None
    editable: bool | None
    help_text: str | None
    form_widget_cls: str | None
    props: str | None
    classes: str | None
    tailwind: str | None
    style: str | None
    tooltip: str | None
    password: bool | None
    password_toggle_button: bool | None
    autocomplete: List[str] | None
    min: float | None
    max: float | None
    precision: int | None
    step: float | None
    prefix: str | None
    suffix: str | None
    format: str | None


class NmFieldInfo():
    """
    Metadata for a UI field. This class is used to define the properties of a field in a form or table.
    It is a generic class that can be used with any Pydantic model.

    This class is used irrespective of its is used explicitly.
    """
    label: str | None = None
    placeholder: str | None = None

    required: bool = False  # this is not the same as required in pydantic
    hidden: bool = False
    editable: bool = True
    help_text: str | None = None
    form_widget_cls: str | None = None # TODO better type, we excpect subclasses of ui.element

    # ui.element
    props: str | None = None
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    tooltip: str | None = None
    # how can we handle slots?

    # ui.table/columns
    table_required: bool | None = None
    table_align: Literal[None, 'left', 'center', 'right'] | None = None
    table_sortable: bool | None = None
    table_sort_order: Literal[None, 'ad', 'da'] | None = None
    table_style: str | None = None
    table_classes: str | None = None

    # ui.aggrid/columns
    aggrid_editable: bool | None = None
    aggrid_sortable: bool | None = None

    # ui.input: label, placeholder, and the values below
    password: bool = False
    password_toggle_button: bool = False
    autocomplete: List[str] | None = None
    #validation: Optional[Union[ValidationFunction, ValidationDict]] = None,

    # ui.number
    # label, placeholder
    min: float | None = None
    max: float | None = None
    precision: int | None = None
    step: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    format: str | None = None


    def __init__(self, **kwargs: Unpack[_NmFieldInfoInputs]):
        # Initialize the field with the provided keyword arguments.
        for key, value in kwargs.items():
            if hasattr(self, key):
                # use default value if not provided, and if provided set the value
                if value is not None:
                    setattr(self, key, value)
            else:
                raise ValueError(f"Invalid field name: {key}")

    def __repr__(self):
        """Print non-none values"""
        non_default_values = {k: v for k, v in self.__dict__.items() if v is not None}
        formatted_values = ', '.join(
            f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" 
            for k, v in non_default_values.items()
        )
        if formatted_values:
            return f"{self.__class__.__name__}({formatted_values})"
        return super().__repr__()


def NmField(**kwargs: Unpack[_NmFieldInfoInputs]) -> NmFieldInfo:
    """
    A decorator to create a UiFieldInfo instance with the provided keyword arguments.
    This is a convenience function to create fields for forms and tables.
    """
    return NmFieldInfo(**kwargs)


class NmFieldsMixin:
    """
    Mixin class to handle fields and field information for datamodel based UI components.
    """
    _field_names: list[str] = []
    _ui_field_infos: dict[str, NmFieldInfo] = {}

    def _create_field_names(self, model_cls: type[BaseModel], fields: list[str] | str | None = None):
        """
        Get the fields from the model class.
        """
        model_fields = model_cls.model_fields
        if fields is None:
            # if fields is None, get all fields from the model class
            self._field_names = list(model_fields.keys())
        elif isinstance(fields, str):
            # if fields is a string, check if it is __all__
            if fields == "__all__":
                self._field_names = list(model_fields.keys())
            else:
                raise ValueError(f"Invalid field name: {fields} must be '__all__' or a list of field names")
        elif isinstance(fields, list):
            # if fields is a list, check if it is a list of field names
            if len(fields) == 0 or (len(fields) == 1 and fields[0] == "__all__"):
                # if fields is empty or __all__, get all fields from the model class
                self._field_names = list(model_cls.model_fields.keys())
            else:
                # check if all fields are valid field names
                self._field_names = fields
                for field in self._field_names:
                    if not isinstance(field, str):
                        raise ValueError(f"Invalid field name: {field} is not a string")
                    if field not in model_fields:
                        raise ValueError(f"Invalid field name: {field} not in model fields")
        else:
            raise ValueError(f"Invalid field name: {fields}")


    def _create_field_infos(self, model_cls: type[BaseModel], field_infos: dict[str, NmFieldInfo] | None = None):
        """
        Update the field information for the model class.
        """
        self._ui_field_infos = {}
        for field_name, field_info in model_cls.model_fields.items():
            field_type = field_info.annotation
            # check for UiFieldInfo
            ui_field_info = None
            for i in field_info.metadata:
                if isinstance(i, NmFieldInfo):
                    ui_field_info = i
            if ui_field_info is None:
                ui_field_info = NmFieldInfo()
            # merge regular field info with UiFieldInfo
            ui_field_info.label = ui_field_info.label or field_info.title or self._nice_field_label(field_name)
            ui_field_info.placeholder = ui_field_info.placeholder or field_info.description
            ui_field_info.required = ui_field_info.required or field_info.is_required()
            if (not ui_field_info.form_widget_cls) and hasattr(self.__class__, '_get_field_widget_cls_from_type') and callable(getattr(self.__class__, '_get_field_widget_cls_from_type')):
                # if the class has a _get_field_widget_cls_from_type method, use it to get the widget class
                ui_field_info.form_widget_cls = self._get_field_widget_cls_from_type(field_type)
            ui_field_info.tooltip = ui_field_info.tooltip or field_info.description
            self._ui_field_infos[field_name] = ui_field_info
        # if field_infos is not None, update the field information with the provided field_infos
        if field_infos is not None:
            for field_name, field_info in field_infos.items():
                if field_name not in self._ui_field_infos:
                    raise ValueError(f"Invalid field name: {field_name} not in model fields")
                # merge the provided field info with the existing field info
                self._ui_field_infos[field_name] = NmFieldInfo(**{**self._ui_field_infos[field_name], **field_info})


    def _nice_field_label(self, name: str) -> str:
        """
        Convert a field name to a more user-friendly format.
        """
        # Replace underscores with spaces and capitalize the first letter
        return name.replace('_', ' ').capitalize()
