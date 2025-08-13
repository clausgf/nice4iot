from dataclasses import dataclass
import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Union, Unpack
import typing
from pydantic import BaseModel
import pydantic
import typing_extensions

from nicegui import ui
from nicegui.events import ValueChangeEventArguments
from nicegui.dataclasses import KWONLY_SLOTS


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
    widget_type: Literal['ui.input', 'ui.number', 'datetime', 'date', 'time', 'ui.textarea', 'ui.checkbox', 'ui.switch', 'ui.select'] | None = None
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
    Metadata for a UI field. This class is used to annotate a field similar 
    to Pydantic's Field class/method.
    While pydantic's Field is used to define the properties of a field
    related to data validation and JSON serialization, this class is used
    to define the properties of a field in a UI context, such as forms and 
    tables.
    """
    field_type: type = str  # the type of the field, e.g. str, int, float, bool, datetime, date, time

    label: str | None = None
    placeholder: str | None = None

    required: bool = False  # this is not the same as required in pydantic
    hidden: bool = False
    editable: bool = True
    help_text: str | None = None
    # widget type for the field  (default infered from field type)
    widget_type: Literal['ui.input', 'ui.number', 'datetime', 'date', 'time', 'ui.textarea', 'ui.checkbox', 'ui.switch', 'ui.select'] | None = None

    # ui.element
    props: str | None = None
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    tooltip: str | None = None
    # TODO: Do we need to handle slots? How?

    # options when field is used in a table column
    table_required: bool | None = None
    table_align: Literal[None, 'left', 'center', 'right'] | None = None
    table_sortable: bool | None = None
    table_sort_order: Literal[None, 'ad', 'da'] | None = None
    table_style: str | None = None
    table_classes: str | None = None

    # options when field is rendered as ui.aggrid column
    aggrid_editable: bool | None = None
    aggrid_sortable: bool | None = None

    # additional options when field is renderd in a ui.input widget
    password: bool = False
    password_toggle_button: bool = False
    autocomplete: List[str] | None = None
    #validation: Optional[Union[ValidationFunction, ValidationDict]] = None,

    # addtional options when field is rendered as ui.number
    # label, placeholder
    min: float | None = None
    max: float | None = None
    precision: int | None = None
    step: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    format: str | None = None

    # additional options when field is rendered as ui.select
    options: Union[List, Dict, Callable[[str, Any], Awaitable[dict]]] | None = None  # list of options for the select widget


    def __init__(self, **kwargs: Unpack[_NmFieldInfoInputs]):
        # Initialize the field with the provided keyword arguments.
        for key, value in kwargs.items():
            if hasattr(self, key):
                # use default value if not provided (not None)
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
    Create NmFieldInfo instance with the provided keyword arguments.
    This is a convenience function to create fields for forms and tables.
    """
    return NmFieldInfo(**kwargs)


class NmFieldsMixin:
    """
    Mixin class to handle fields and field information for datamodel based UI components.
    """
    _field_names: list[str] = []
    _nm_field_infos: dict[str, NmFieldInfo] = {}
    _widget_lookup: dict[type, str] = {
        str: 'ui.input',
        int: 'ui.number',
        float: 'ui.number',
        bool: 'ui.switch',
        datetime.datetime: 'datetime',
        datetime.date: 'date',
        datetime.time: 'time',
    }

    def __collect_field_names(self, item_type: type[BaseModel], fields: str | Iterable[str], exclude: str | Iterable[str]) -> List[str]:
        """
        Get the fields from the model class.

        Parameters:
        :param model_cls: The model class to get the fields from.
        :fields:
        - str or Iterable[str] or None:
            - If None, get all fields from the model class.
            - If '__all__', get all fields from the model class.
            - If a list of field names, get the fields from the model class that are in the list.
            - If a string with field names separated by commas, get the fields from the model class that are in the string.
        :exclude: fields to exclude from the model class in the same syntax as :fields:.
        """
        model_fields = item_type.model_fields

        # prepare a list of fields to exclude
        if isinstance(exclude, str):
            exclude = [f.strip() for f in exclude.split(',')]
        elif isinstance(exclude, Iterable):
            exclude = list(exclude)
            if not all(isinstance(f, str) for f in exclude):
                raise ValueError(f"Invalid exclude: {exclude} must be a string or a list of field names")
        else:
            raise ValueError(f"Invalid exclude: {exclude} must be a string or a list of field names")

        # prepare a list of include candidate fields
        if isinstance(fields, str):
            if fields.strip() == '__all__':
                include = list(model_fields.keys())
            else:
                include = [f.strip() for f in fields.split(',')]
        elif isinstance(fields, Iterable):
            include = list(fields)
            if not all(isinstance(f, str) for f in include):
                raise ValueError(f"Invalid fields: {fields} must be a string or a list of field names")
        else:
            raise ValueError(f"Invalid field name: {fields} must be '__all__' or a list of field names")

        # collect the final list of field names
        return [f for f in include if f in model_fields and f not in exclude]


    def __label_from_name(self, name: str) -> str:
        """
        Convert a field name to a more user-friendly format.
        """
        return name.replace('_', ' ').capitalize()


    def __field_info_from_pydantic(self, field_name: str, field_info: pydantic.fields.FieldInfo) -> NmFieldInfo:
        """
        Create a field info for the given field name.
        """
        field_type = field_info.annotation

        # check for NmFieldInfo annotation
        nm_field_info = None
        for i in field_info.metadata:
            if isinstance(i, NmFieldInfo):
                nm_field_info = i
        if nm_field_info is None:
            nm_field_info = NmFieldInfo()

        nm_field_info.field_type = field_type
        
        # determine widget type from field type
        if nm_field_info.widget_type is None:
            # remove the Optional from a type
            if typing.get_origin(field_type) is typing.Union:
                # if the field type is a Union, get the first non-None type
                union_types = next((t for t in typing.get_args(field_type) if t is not type(None)), None)
                if len(union_types) == 1:
                    field_type = union_types[0]

            if field_type in self._widget_lookup:
                nm_field_info.widget_type = self._widget_lookup[field_type]
            elif typing.get_origin(field_type) == Literal:
                nm_field_info.widget_type = 'ui.select'
                if nm_field_info.options is None:
                    nm_field_info.options = list(typing.get_args(field_type))
            else:
                nm_field_info.widget_type = 'ui.input'  # default widget type if not specified

        # merge regular field info with NmFieldInfo
        if nm_field_info.label is None:
            nm_field_info.label = field_info.title if field_info.title is not None else self.__label_from_name(field_name)
        if nm_field_info.placeholder is None:
            nm_field_info.placeholder = field_info.description
        if nm_field_info.required is None:
            nm_field_info.required = field_info.is_required()
        if nm_field_info.tooltip is None:
            nm_field_info.tooltip = field_info.description

        # merge regular aditional metadata with NmFieldInfo min/max/step
        if field_type in (int, float):
            meta = field_info.metadata
            if not nm_field_info.min and hasattr(meta, 'gt'):
                nm_field_info.min = field_info.gt
            elif not nm_field_info.min and hasattr(meta, 'ge'):
                nm_field_info.min = field_info.ge
            if not nm_field_info.max and hasattr(meta, 'lt'):
                nm_field_info.max = field_info.lt
            elif not nm_field_info.max and hasattr(meta, 'le'):
                nm_field_info.max = field_info.le
            if not nm_field_info.step and hasattr(meta, 'multiple_of'):
                nm_field_info.step = field_info.multiple_of
        
        return nm_field_info


    def _init_field_infos(self, model_cls: type[BaseModel], nm_field_info_args: dict[str, NmFieldInfo] | None = None):
        """
        Update the field information for the model class.
        """
        self._nm_field_infos = {}
        for field_name, field_info in model_cls.model_fields.items():
            if field_name in self._field_names:
                self._nm_field_infos[field_name] = self.__field_info_from_pydantic(field_name, field_info)

        # update the nm field information with nm_field_info_args
        if nm_field_info_args is not None:
            for field_name, nm_field_info_arg in nm_field_info_args.items():
                if field_name not in self._nm_field_infos:
                    raise ValueError(f"Invalid field name: {field_name} not in model fields")
                self._nm_field_infos[field_name] = NmFieldInfo(**{**self._nm_field_infos[field_name], **nm_field_info_arg})


    def init_fields(self, item_type: type[BaseModel], fields: str | Iterable[str] = '__all__', exclude: str | Iterable[str] = '', nm_field_info_args: dict[str, NmFieldInfo] | None = None):
        self._field_names = self.__collect_field_names(item_type, fields, exclude)
        self._init_field_infos(item_type, nm_field_info_args)


    @property
    def field_names(self) -> Iterable[str]:
        """
        Get the field names of the model.
        """
        return self._field_names


    def get_field_info(self, field_name: str) -> NmFieldInfo:
        """
        Get the field information for the given field name.
        If the field name is not in the field information, raise a ValueError.
        """
        if field_name not in self._nm_field_infos:
            raise ValueError(f"Invalid field name: {field_name} not in model fields")
        return self._nm_field_infos[field_name]


    def get_field_type(self, field_name: str) -> type:
        """
        Get the field type for the given field name.
        If the field name is not in the field information, raise a ValueError.
        """
        if field_name not in self._nm_field_infos:
            raise ValueError(f"Invalid field name: {field_name} not in model fields")
        return self._nm_field_infos[field_name].field_type



@dataclass(**KWONLY_SLOTS)
class FieldChangeEventArguments(ValueChangeEventArguments):
    field_name: str
    old_value: Any
    new_value: Any

