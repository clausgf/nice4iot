from typing import List, Self, Unpack
import typing_extensions
from pydantic import BaseModel, ValidationError
from nicegui import ui
from nicegui.events import Handler, ValueChangeEventArguments, handle_event

from nicemodel.modelfield import NmFieldsMixin, NmFieldInfo


class _ModelFormOptionInputs(typing_extensions.TypedDict, total=False):
    """
    Kwarg Options for the UiForm class.
    """
    fields: list[str] | str | None = None
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

    _model_cls: type[BaseModel]
    _current_model: BaseModel | None = None
    _validated_model: BaseModel | None = None
    _widgets: dict[str, ui.element] = {}
    _widget_lookup: dict[type, str] = {
        str: 'ui.input',
        int: 'ui.number',
        float: 'ui.number',
        bool: 'ui.switch',
    }
    _change_handlers: List[Handler[ValueChangeEventArguments]] = []
    _validation_error_messages: dict[str, str] = {}

    fields: list[str] = []  # this is not the final list of fields, which is found in _fields
    field_infos: dict[str, NmFieldInfo] = {} # this is not the final list of field infos, which is found in _ui_field_infos
    classes: str = ''
    tailwind: str = ''
    style: str = ''
    props: str = ''

    def __init__(self, model: BaseModel, **kwargs: Unpack[_ModelFormOptionInputs]) -> None:
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
        self._model_cls = type(model)
        if not isinstance(self._model_cls, type) or not issubclass(self._model_cls, BaseModel):
            raise TypeError(f"cls must be a subclass of BaseModel, got {type(self._model_cls)}")
        self._validated_model = model
        self._current_model = self._validated_model.model_copy(deep=True)
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

        self._create_field_names(self._model_cls, self.fields)
        self._create_field_infos(self._model_cls, self.field_infos)


    def on_change(self, callback: Handler[ValueChangeEventArguments]) -> Self:
        """
        Add a callback to be invoked when the form values change and 
        the new values are successfully validated.
        """
        if not callable(callback):
            raise TypeError(f"callback must be callable, got {type(callback)}")
        if not isinstance(callback, Handler):
            raise TypeError(f"callback must be a Handler, got {type(callback)}")
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


    def _get_field_widget_cls_from_type(self, ui_field_type: type) -> str:
        """
        Get the widget type for a field based field type.
        """
        return self._widget_lookup.get(ui_field_type, 'ui.input')


    def render(self) -> Self:
        """
        Render the form. If the model is given, it will be bound to the form.
        """
        self._widgets = {}
        for field_name in self._field_names:
            field_info = self._ui_field_infos.get(field_name)
            if not field_info:
                raise ValueError(f"Field {field_name} not found in ui_field_infos")
            if field_info.hidden:
                # Skip hidden fields
                continue
            if not field_info.editable:
                # Render a non-editable field
                self._widgets[field_name] = ui.label(field_info.label)
                continue
            # Render an editable field based on its widget class
            widget_cls = field_info.form_widget_cls
            if not widget_cls:
                raise ValueError(f"Widget class not found for field {field_name}")
            if widget_cls == 'ui.input':
                # Render an input field
                kwargs = {k: v for k in ['label', 'placeholder', 'password', 'password_toggle_button', 'autocomplete']
                          if ( v := getattr(field_info, k)) is not None}
                self._widgets[field_name] = ui.input(**kwargs)
                #self._widgets[field_name].bind_value(self._current_model, field_name)
                self._widgets[field_name].on_value_change(lambda vce, field=field_name: self._handle_validate(field, vce))
                self._widgets[field_name].on('blur', lambda e, field=field_name: self._handle_blur_event(field, e))
                self._widgets[field_name].validation = lambda value, field=field_name: self._validation_errors(field, value)
            elif widget_cls == 'ui.number':
                # Render a number field
                kwargs = { k: v for k in ['label', 'placeholder', 'min', 'max', 'precision', 'step', 'prefix', 'suffix', 'format']
                           if ( v := getattr(field_info, k)) is not None }
                self._widgets[field_name] = ui.number(**kwargs)
                #self._widgets[field_name].bind_value(self._current_model, field_name)
                self._widgets[field_name].on_value_change(lambda vce, field=field_name: self._handle_validate(field, vce))
                self._widgets[field_name].on('blur', lambda e, field=field_name: self._handle_blur_event(field, e))
                self._widgets[field_name].validation = lambda value, field=field_name: self._validation_errors(field, value)
            elif widget_cls == 'ui.textarea':
                # Render a number field
                kwargs = { k: v for k in ['label', 'placeholder']
                           if ( v := getattr(field_info, k)) is not None }
                self._widgets[field_name] = ui.textarea(**kwargs)
                #self._widgets[field_name].bind_value(self._current_model, field_name)
                self._widgets[field_name].on_value_change(lambda vce, field=field_name: self._handle_validate(field, vce))
                self._widgets[field_name].on('blur', lambda e, field=field_name: self._handle_blur_event(field, e))
                self._widgets[field_name].validation = lambda value, field=field_name: self._validation_errors(field, value)
            elif widget_cls == 'ui.checkbox':
                # Render a checkbox
                self._widgets[field_name] = ui.checkbox(text=field_info.label)
                #self._widgets[field_name].bind_value(self._current_model, field_name)
                self._widgets[field_name].on_value_change(lambda vce, field=field_name: self._handle_validate_and_change(field, vce))
                # TODO: how can we render validation errors here?
            elif widget_cls == 'ui.switch':
                # Render a switch
                self._widgets[field_name] = ui.switch(text=field_info.label)
                #self._widgets[field_name].bind_value(self._current_model, field_name)
                self._widgets[field_name].on_value_change(lambda vce, field=field_name: self._handle_validate_and_change(field, vce))
                # TODO: how can we render validation errors here?
            else:
                raise ValueError(f"Invalid widget class: {widget_cls}")
            self._widgets[field_name].value = getattr(self._current_model, field_name)
            self._widgets[field_name].classes(self.classes)
            self._widgets[field_name].tailwind(self.tailwind)
            self._widgets[field_name].style(self.style)
            self._widgets[field_name].props(self.props)

        return self


    def _validation_errors(self, field_name: str, value) -> str | None:
        # return validation error messages for the field
        msg = self._validation_error_messages.get(field_name, None)
        if type(msg) == list:
            msg = ', '.join(msg)
        #print(f"_validation_errors: Validation error for field {field_name}: {msg}")
        return msg


    def _validate(self) -> None:
        # validate the model with the new value
        self._validation_error_messages.clear()
        nonfield_errors = []
        try:
            # validate the whole model
            self._model_cls.model_validate(self._current_model.model_dump())
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
        old_value = getattr(self._current_model, field_name)
        new_value = value_change_event.sender.value

        if old_value != new_value:
            # update the current model from the widget & validate the current model
            print(f"_handle_validate field_name={field_name} event={value_change_event}: old_value={old_value} new_value={new_value}")
            setattr(self._current_model, field_name, new_value)
            self._validate()


    def _handle_value_change(self, field_name: str, value_change_event: ValueChangeEventArguments) -> None:
        # do not handle the change event if the validation failed
        if len(self._validation_error_messages) > 0:
            # validation error, do not update the model
            print(f"_handle_value_change field_name={field_name} event={value_change_event}: change not accepted or propagated, validation error(s): {self._validation_error_messages}")
            return

        # do not handle non-changes
        old_value = getattr(self._validated_model, field_name)
        new_value = getattr(self._current_model, field_name)
        if old_value == new_value:
            return

        # change accepted, update teh validated model from the current model
        print(f"_handle_change field_name={field_name} event={value_change_event}: old_value={old_value} new_value={new_value}")
        setattr(self._validated_model, field_name, new_value)

        # call the change handlers
        #event.args.update({'field_name': field_name, 'old_value': old_value, 'new_value': new_value})
        #value_change_event = ValueChangeEventArguments(sender=event.sender, client=event.client, value=event.value)
        for handler in self._change_handlers:
            handle_event(handler, value_change_event)


    def _handle_validate_and_change(self, field_name: str, value_change_event: ValueChangeEventArguments) -> None:
        self._handle_validate(field_name, value_change_event)
        self._handle_value_change(field_name, value_change_event)
