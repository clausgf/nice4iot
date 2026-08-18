"""
The Device Offline block of the alarm config card is one ModelForm over
DeviceOfflineAlarm: a renamed field raises only when the form renders.
Same shape as test_forwarding_card.
"""
import datetime

from nicegui import ui
from niceview import ModelForm
from niceview.dataadapter import JsonAdapter

from niceview import BoundFieldAdapter

from app.core.alarm.models import AlarmConfig, DeviceOfflineAlarm


def _form(tmp_path) -> ModelForm:
    adapter = JsonAdapter(AlarmConfig, tmp_path / '.alarm_config.json',
                          create_if_not_exist=True, lock_field='updated_at')
    form = ModelForm.from_adapter(
        DeviceOfflineAlarm, BoundFieldAdapter(adapter, 'device_offline'), autosave=True,
    )
    with ui.row():
        form.render_field('is_active', label='')
        form.render_field('device_offline_threshold')
    return form


def test_both_fields_render_in_one_form(tmp_path):
    form = _form(tmp_path)
    assert set(form.widgets) == {'is_active', 'device_offline_threshold'}


def test_the_activation_switch_has_no_label(tmp_path):
    """The block heading already says what the switch is for."""
    form = _form(tmp_path)
    assert not form.widgets['is_active']._props.get('label')
    assert form.widgets['device_offline_threshold']._props.get('label')


def test_the_threshold_round_trips_through_the_sub_adapter(tmp_path):
    adapter = JsonAdapter(AlarmConfig, tmp_path / '.alarm_config.json',
                          create_if_not_exist=True, lock_field='updated_at')
    sub = BoundFieldAdapter(adapter, 'device_offline')
    sub.save(DeviceOfflineAlarm(is_active=False, device_offline_threshold=datetime.timedelta(minutes=15)))
    assert adapter.read().device_offline.device_offline_threshold == datetime.timedelta(minutes=15)
    assert adapter.read().device_offline.is_active is False
