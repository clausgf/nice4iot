import datetime
from typing import Any, List, Self, Unpack
from zoneinfo import ZoneInfo
import typing_extensions
from pydantic import BaseModel, ValidationError
from nicegui import ui
from nicegui.events import Handler, ValueChangeEventArguments, handle_event

from nicemodel.modelfield import FieldChangeEventArguments, NmFieldsMixin, NmFieldInfo


class _ModelFormOptionInputs(typing_extensions.TypedDict, total=False):
    """
    Kwarg Options for the UiForm class.
    """
    fields: list[str] | str | None = None
    exclude: list[str] | str | None = None
    field_infos: dict[str, NmFieldInfo] | None = None
    on_change: Handler[ValueChangeEventArguments] | None = None
    """Callback to execute when value changes. To reduce the number of change events, fields like ui.input or ui.number also have to loose focus (blur)."""
    classes: str | None = None
    tailwind: str | None = None
    style: str | None = None
    props: str | None = None


class ModelForm(NmFieldsMixin):
    """
    A form class that can be used to create forms for Pydantic models.
    """

    _item_cls: type[BaseModel]
    _current_item: BaseModel | None = None
    _validated_item: BaseModel | None = None
    _widgets: dict[str, ui.element] = {}
    _change_handlers: List[Handler[FieldChangeEventArguments]] = []
    _validation_error_messages: dict[str, str] = {}

    fields: list[str] | str = '__all__'  # this is not the final list of fields, which is handled by NmFieldsMixin
    exclude: list[str] | str = []  # fields to exclude from the grid
    field_infos: dict[str, NmFieldInfo] = {} # this is not the final list of field infos, which is handled by NmFieldsMixin
    classes: str = ''
    tailwind: str = ''
    style: str = ''
    props: str = ''

    def __init__(self, item: BaseModel, **kwargs: Unpack[_ModelFormOptionInputs]) -> None:
        """
        Initialize the form with a model and optional keyword arguments.
        The model must be a subclass of BaseModel.
        The keyword arguments can be used to set the fields, field_infos, and other options.

        Binding:
        - The form keeps a reference to the model and the current model.
        - The reference to the model is updated when the form is successfully validated. 
          Therefore it is called the validated model.
        - The current model is the one that is currently being edited.
        - The current model is validated after each change.
        """
        self._item_cls = type(item)
        if not isinstance(self._item_cls, type) or not issubclass(self._item_cls, BaseModel):
            raise TypeError(f"cls must be a subclass of BaseModel, got {type(self._item_cls)}")
        self._validated_item = item
        self._current_item = self._validated_item.model_copy(deep=True)
        self._validate()

        if on_value_change := kwargs.pop('on_change', None):
            self.on_change(on_value_change)

        # Initialize the field with the remaining keyword arguments.
        for key, value in kwargs.items():
            if not key.startswith('_') and hasattr(self, key):
                # use default value if not provided, and if provided set the value
                if value is not None:
                    setattr(self, key, value)
            else:
                raise ValueError(f"Invalid field name: {key}")

        self.init_fields(self._item_cls, self.fields, self.exclude, self.field_infos)


    def on_change(self, callback: Handler[FieldChangeEventArguments]) -> Self:
        """
        Add a callback to be invoked when the form values change and 
        the new values are successfully validated.
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        # if not isinstance(callback, Handler[ValueChangeEventArguments]):
        #     raise TypeError(f"callback must be a Handler, got {type(callback)}")
        self._change_handlers.append(callback)
        return self


    def _copy_model(self, source: BaseModel, target: BaseModel) -> None:
        """
        Copy the values from the source model to the target model.
        """
        for field in self._field_names:
            if field in source.__dict__:
                setattr(target, field, getattr(source, field)) # TODO good idea to use a copy method here?
            else:
                raise ValueError(f"Field {field} not found in source model")


    def _create_widget(self, field_name: str, nm_field_info: NmFieldInfo) -> ui.element:
        """
        Create a widget for the given field name and field info.
        The widget type is determined by the field info.
        """

        def get_kwargs_from_field_info(fields: list[str]) -> dict:
            """
            Get the keyword arguments from the field info for the given fields.
            """
            return {k: v for k in fields if (v := getattr(nm_field_info, k)) is not None}

        if not nm_field_info:
            raise ValueError(f"Field info for {field_name} not found")
        widget_type = nm_field_info.widget_type
        if not widget_type:
            raise ValueError(f"Widget type for field {field_name} not found in field info")

        if widget_type == 'ui.input':
            widget = ui.input(**get_kwargs_from_field_info(['label', 'placeholder', 'password', 'password_toggle_button', 'autocomplete']))
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field=field_name: self._handle_validate(field, vce))
            widget.on('blur', lambda e, field=field_name: self._handle_blur_event(field, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'ui.number':
            widget = ui.number(**get_kwargs_from_field_info(['label', 'placeholder', 'min', 'max', 'precision', 'step', 'prefix', 'suffix', 'format']))
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate(field_name, vce))
            widget.on('blur', lambda e, field_name=field_name: self._handle_blur_event(field_name, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'datetime':
            widget = ui.input(**get_kwargs_from_field_info(['label', 'placeholder'])).props('type=datetime-local').props('step=1')
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate(field_name, vce))
            widget.on('blur', lambda e, field_name=field_name: self._handle_blur_event(field_name, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'date':
            widget = ui.input(**get_kwargs_from_field_info(['label', 'placeholder'])).props('type=date')
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate(field_name, vce))
            widget.on('blur', lambda e, field_name=field_name: self._handle_blur_event(field_name, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'time':
            widget = ui.input(**get_kwargs_from_field_info(['label', 'placeholder'])).props('type=time').props('step=1')
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate(field_name, vce))
            widget.on('blur', lambda e, field_name=field_name: self._handle_blur_event(field_name, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'ui.textarea':
            widget = ui.textarea(**get_kwargs_from_field_info(['label', 'placeholder']))
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate(field_name, vce))
            widget.on('blur', lambda e, field_name=field_name: self._handle_blur_event(field_name, e))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)

        elif widget_type == 'ui.checkbox':
            widget = ui.checkbox(text=nm_field_info.label)
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate_and_change(field_name, vce))
            # TODO: how can we render validation errors here?

        elif widget_type == 'ui.switch':
            widget = ui.switch(text=nm_field_info.label)
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate_and_change(field_name, vce))
            # TODO: how can we render validation errors here?
        
        elif widget_type == 'ui.select':
            widget = ui.select(**get_kwargs_from_field_info(['label', 'options']))
            # TODO: select options handlig 
            self._from_current_item_to_widget_value(field_name, widget_type, widget)
            widget.on_value_change(lambda vce, field_name=field_name: self._handle_validate_and_change(field_name, vce))
            widget.validation = lambda value, field_name=field_name: self._validation_errors(field_name, value)
        
        else:
            raise ValueError(f"Invalid widget class: {widget_type}")

        if not nm_field_info.editable and hasattr(widget, 'disable') and callable(widget.disable):
            widget.disable()
        if nm_field_info.tooltip and hasattr(widget, 'tooltip') and callable(widget.tooltip):
            widget.tooltip(nm_field_info.tooltip)
        widget.classes(self.classes)
        widget.tailwind(self.tailwind)
        widget.style(self.style)
        widget.props(self.props)

        return widget


    def render(self) -> Self:
        """
        Render the form. If the model is given, it will be bound to the form.
        """
        self._widgets = {}
        for field_name in self._field_names:
            field_info = self._nm_field_infos.get(field_name)
            if not field_info:
                raise ValueError(f"Field {field_name} not found in ni_field_infos")
            if field_info.hidden:
                # Skip hidden fields
                continue
            # Render an editable field based on its widget class
            self._widgets[field_name] = self._create_widget(field_name, field_info)

        self._validate()

        return self


    def _from_current_item_to_widget_value(self, field_name: str, widget_type: str, widget) -> Self:
        """
        Set the value of the widget for the given field name to the given (model) value.
        This will also update the current model and validate it.
        """
        value = getattr(self._current_item, field_name)

        if type(value) is datetime.datetime and widget_type == 'datetime':
            # timezone support for datetime fields
            local_tz = ZoneInfo("Europe/Berlin")  #TODO: remove hardcoded timezone
            value = value.astimezone(local_tz).replace(tzinfo=None).isoformat()

        widget.value = value

        return self


    def _from_widget_value_to_current_item(self, field_name: str) -> None:
        """
        Convert the value from the widget to the model value.
        """
        # determine the widget
        if field_name not in self._widgets:
            raise ValueError(f"Widget for field {field_name} not found")
        widget = self._widgets[field_name]
        widget_type = self._nm_field_infos[field_name].widget_type
        field_type = self._nm_field_infos[field_name].field_type
        value = widget.value

        # convert the value depending on the widget type
        if widget_type == 'datetime':
            dt = datetime.datetime.fromisoformat(value)
            local_tz = ZoneInfo("Europe/Berlin")  #TODO: remove hardcoded timezone
            value = dt.replace(tzinfo=local_tz)
            # Exceptions should be handled by the validation
        elif widget_type == 'ui.number':
            if field_type == int:
                value = int(value)
            else:
                value = float(value)  # convert to float for number fields
            # Exceptions should be handled by the validation

        setattr(self._current_item, field_name, value)


    def _validation_errors(self, field_name: str, value) -> str | None:
        # return validation error messages for the field
        msg = self._validation_error_messages.get(field_name, None)
        if type(msg) == list:
            msg = ', '.join(msg)
        #print(f"_validation_errors: Validation error for field {field_name}: {msg}")
        return msg


    def _validate(self, field_name: str | None = None) -> None:
        # validate the model with the new value
        self._validation_error_messages.clear()
        nonfield_errors = []
        try:
            # validate the whole model
            self._item_cls.model_validate(self._current_item.model_dump())
        except ValidationError as e:
            # print(e.errors())
            # [{'type': 'string_too_long', 'loc': ('name',), 'msg': 'String should have at most 8 characters', 'input': 'John Doex', 'ctx': {'max_length': 8}, 'url': 'https://errors.pydantic.dev/2.11/v/string_too_long'}]
            for error in e.errors():
                error_was_handled = False
                # check if the error can be attributed to a known field
                for loc in error['loc']:
                    if loc in self._field_names:
                        field_name = loc
                        if field_name not in self._validation_error_messages:
                            self._validation_error_messages[field_name] = []
                        self._validation_error_messages[field_name].append(error['msg'])
                        error_was_handled = True
                if not error_was_handled:
                    # if the error cannot be attributed to a known field, it is a non-field error
                    nonfield_errors.append(error['msg'])
            if len(nonfield_errors) > 0:
                # if there are non-field errors, add them to the validation error messages
                self._validation_error_messages['nonfield'] = nonfield_errors
                # TODO find a way to display the validation errors in the UI
            print(f"_validate: Validation error(s): {self._validation_error_messages}")


    def _handle_blur_event(self, field_name: str, event) -> None:
        """
        Handle the change event to update the model with the new value.
        """
        #print(f"change '{field_name}': {event}")
        # GenericEventArguments(sender=<nicegui.elements.number.Number object at 0x113dcec10>, client=<nicegui.client.Client object at 0x113d27cb0>, 
        #  args={'isTrusted': True, '_vts': 1747817122891, 'detail': 0, 'layerX': 0, 'layerY': 0, 'pageX': 0, 'pageY': 0, 
        #   'which': 0, 'type': 'focusout', 'currentTarget': None, 'eventPhase': 0, 'cancelBubble': False, 
        #   'bubbles': True, 'cancelable': False, 'defaultPrevented': False, 'composed': True, 'timeStamp': 8820, 
        #   'returnValue': True, 'NONE': 0, 'CAPTURING_PHASE': 1, 'AT_TARGET': 2, 'BUBBLING_PHASE': 3})
        vce = ValueChangeEventArguments(sender=event.sender, client=event.client, value=event.sender.value)
        self._handle_value_change(field_name, vce)


    def _handle_validate(self, field_name: str, value_change_event: ValueChangeEventArguments) -> None:
        old_value = getattr(self._current_item, field_name)
        new_value = value_change_event.sender.value

        if old_value != new_value:
            # update the current model from the widget & validate the current model
            #print(f"_handle_validate field_name={field_name} event={value_change_event}: old_value={old_value} new_value={new_value}")
            error_msg = None
            try:
                self._from_widget_value_to_current_item(field_name)
            except Exception as e:
                error_msg = f"Error interpreting widget value"

            self._validate()

            # reflect previous conversion errors in the validation error message
            if error_msg is not None:
                self._validation_error_messages[field_name] = [error_msg]


    def _handle_value_change(self, field_name: str, value_change_event: ValueChangeEventArguments) -> None:
        # do not handle the change event if the validation failed
        if len(self._validation_error_messages) > 0:
            # validation error, do not update the model
            print(f"_handle_value_change field_name={field_name} event={value_change_event}: change not accepted or propagated, validation error(s): {self._validation_error_messages}")
            return

        # do not handle non-changes
        old_value = getattr(self._validated_item, field_name)
        new_value = getattr(self._current_item, field_name)
        if old_value == new_value:
            return

        # change accepted, update teh validated model from the current model
        #print(f"_handle_change field_name={field_name} event={value_change_event}: old_value={old_value} new_value={new_value}")
        setattr(self._validated_item, field_name, new_value)

        # call the change handlers
        #event.args.update({'field_name': field_name, 'old_value': old_value, 'new_value': new_value})
        #value_change_event = ValueChangeEventArguments(sender=event.sender, client=event.client, value=event.value)
        fce = FieldChangeEventArguments(
            sender=value_change_event.sender,
            client=value_change_event.client,
            value=value_change_event.value,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
        for handler in self._change_handlers:
            handle_event(handler, fce)


    def _handle_validate_and_change(self, field_name: str, value_change_event: ValueChangeEventArguments) -> None:
        self._handle_validate(field_name, value_change_event)
        self._handle_value_change(field_name, value_change_event)


