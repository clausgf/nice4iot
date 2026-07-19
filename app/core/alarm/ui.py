"""
Alarm UI components.

AlarmConfigCard       — Project/General tab: device-offline + metric rules
ProjectAlarmPanel     — Project Dashboard: alarm summary across all devices
DeviceAlarmPanel      — Device Dashboard: alarms for one device
DeviceAlarmsTab       — Device "Alarms" tab: full list + acknowledgment
"""
import anyio
from nicegui import ui

from app.util import render_datetime
from app.core.alarm.backend import (
    get_alarm_config_adapter,
    get_pending_alarms,
    get_project_alarm_count,
    get_device_alarm_count,
    acknowledge_alarm,
    acknowledge_all_alarms,
)
from app.core.alarm.models import AlarmConfig, MetricAlarmRule, DeviceOfflineConfig
from app.core.telemetry.backend import observed_metrics
from niceview import ModelForm


# ---------------------------------------------------------------------------
# Project/General — alarm configuration card
# ---------------------------------------------------------------------------

class _DeviceOfflineAdapter:
    """Thin adapter that reads/writes only the device_offline sub-object."""

    def __init__(self, alarm_adapter) -> None:
        self._alarm = alarm_adapter

    def read(self) -> DeviceOfflineConfig:
        return self._alarm.read().device_offline

    def save(self, item: DeviceOfflineConfig) -> DeviceOfflineConfig:
        cfg = self._alarm.read()
        cfg.device_offline = item
        self._alarm.save(cfg)
        return item


async def AlarmConfigCard(project_name: str) -> None:
    """Content for the alarm rules card, rendered inside Project/General (caller provides the card/header)."""
    adapter = get_alarm_config_adapter(project_name)
    # Observed (kind -> metric names) from the local store, to seed the rule
    # editor's comboboxes with the actual normalized names. Blocking IO, so
    # wrapped per the async-IO rule.
    observed = await anyio.to_thread.run_sync(lambda: observed_metrics(project_name))

    # Built-in: device offline — use a sub-adapter so ModelForm never
    # sees the nested DeviceOfflineConfig as an opaque widget value.
    with ui.card().classes('w-full q-mb-sm'):
        ui.label('Device Offline').classes('text-caption font-bold text-grey-7')
        du_adapter = _DeviceOfflineAdapter(adapter)
        form_builtin = ModelForm.from_adapter(
            DeviceOfflineConfig,
            du_adapter,
            autosave=True,
        )
        with ui.row().classes('items-center gap-4 w-full'):
            form_builtin.render_field('is_active')

    # Metric rules list
    ui.separator()
    ui.label('Metric Rules').classes('text-caption font-bold text-grey-7 q-mt-sm')

    @ui.refreshable
    def _rules_list() -> None:
        config = adapter.read()
        for i, rule in enumerate(config.rules):
            with ui.card().classes('w-full q-mb-xs'):
                with ui.row().classes('items-center gap-2 w-full'):
                    status_color = 'green' if rule.is_active else 'grey'
                    ui.chip('ON' if rule.is_active else 'OFF').props(
                        f'dense color={status_color} text-color=white'
                    )
                    ui.label(f'{rule.name}: {rule.kind}.{rule.metric} '
                             f'{rule.comparison} {rule.threshold}').classes('grow text-body2')
                    if rule.description:
                        ui.label(rule.description).classes('text-caption text-grey-7')

                    async def _toggle(idx: int = i) -> None:
                        cfg = adapter.read()
                        cfg.rules[idx].is_active = not cfg.rules[idx].is_active
                        adapter.save(cfg)
                        _rules_list.refresh()

                    async def _delete(idx: int = i) -> None:
                        cfg = adapter.read()
                        del cfg.rules[idx]
                        adapter.save(cfg)
                        _rules_list.refresh()

                    ui.button(icon='toggle_on' if rule.is_active else 'toggle_off') \
                        .props('flat dense').on_click(_toggle) \
                        .tooltip('Disable' if rule.is_active else 'Enable')
                    ui.button(icon='delete').props('flat dense color=negative') \
                        .on_click(_delete).tooltip('Delete rule')

        # Add new rule form. Kind/Metric are comboboxes seeded from the
        # observed telemetry (with_input + add-unique lets the user type a
        # brand-new name too); the Metric options track the selected Kind.
        with ui.card().classes('w-full q-mt-sm'):
            ui.label('New Rule').classes('text-caption font-bold text-grey-7')
            with ui.row().classes('items-center gap-2 w-full flex-wrap'):
                kinds = list(observed.keys())
                name_input = ui.input(label='Name', placeholder='e.g. low_temp') \
                    .classes('w-28').props('dense outlined')
                kind_select = ui.select(
                    kinds, label='Kind', value=(kinds[0] if kinds else None),
                    with_input=True, new_value_mode='add-unique',
                ).classes('w-32').props('dense outlined')
                metric_select = ui.select(
                    observed.get(kind_select.value, []), label='Metric',
                    with_input=True, new_value_mode='add-unique',
                ).classes('w-40').props('dense outlined')

                def _on_kind_change(e) -> None:
                    metric_select.options = observed.get(e.value, [])
                    metric_select.value = None
                    metric_select.update()
                kind_select.on_value_change(_on_kind_change)

                cmp_select = ui.select(['<', '=', '>'], label='Op', value='<') \
                    .classes('w-20').props('dense outlined')
                thr_input = ui.number(label='Threshold', value=0.0) \
                    .classes('w-28').props('dense outlined')
                desc_input = ui.input(label='Description (optional)') \
                    .classes('grow').props('dense outlined')

                async def _add_rule() -> None:
                    if not name_input.value or not metric_select.value:
                        ui.notify('Name and Metric are required', type='warning')
                        return
                    cfg = adapter.read()
                    cfg.rules.append(MetricAlarmRule(
                        name=name_input.value.strip(),
                        kind=(kind_select.value or 'sensors').strip() or 'sensors',
                        metric=metric_select.value.strip(),
                        comparison=cmp_select.value,
                        threshold=float(thr_input.value or 0),
                        description=desc_input.value.strip(),
                    ))
                    adapter.save(cfg)
                    _rules_list.refresh()

                ui.button(icon='add', on_click=_add_rule) \
                    .props('color=primary dense').tooltip('Add rule')

    _rules_list()


# ---------------------------------------------------------------------------
# Alarm event list (shared by project and device panels)
# ---------------------------------------------------------------------------

def _alarm_event_row(project_name: str, event, on_ack) -> None:
    """Render a single alarm event row."""
    active_color = 'red' if event.is_active else 'orange'
    status_text = 'ACTIVE' if event.is_active else 'RESOLVED'
    with ui.row().classes('items-center gap-2 w-full q-py-xs'):
        ui.chip(status_text).props(f'dense color={active_color} text-color=white')
        with ui.column().classes('gap-0 grow'):
            ui.label(f'{event.device_name} — {event.rule_name}').classes('text-body2 font-bold')
            ui.label(event.message).classes('text-caption text-grey-7')
            ui.label(f'Since {render_datetime(event.triggered_at)}').classes('text-caption text-grey-6')
        if event.is_acknowledged:
            # Already acknowledged — static green icon, not interactive
            ui.icon('check_circle').classes('text-positive text-xl').tooltip('Acknowledged')
        else:
            # Needs acknowledgment — clickable button
            ui.button(icon='notification_important', on_click=lambda e=event: on_ack(e.id)) \
                .props('flat dense color=negative').tooltip('Acknowledge')


# ---------------------------------------------------------------------------
# Project Dashboard — alarm summary
# ---------------------------------------------------------------------------

def ProjectAlarmPanel(project_name: str) -> None:
    """Panel showing active/pending alarms for all devices in the project."""

    @ui.refreshable
    def _content() -> None:
        events = get_pending_alarms(project_name)
        total = get_project_alarm_count(project_name)
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center w-full'):
                ui.label('Alarms').classes('text-subtitle1 font-bold')
                ui.space()
                if total:
                    ui.chip(str(total)).props('dense color=red text-color=white')
                    async def _ack_all() -> None:
                        await anyio.to_thread.run_sync(
                            lambda: acknowledge_all_alarms(project_name)
                        )
                        _content.refresh()
                    ui.button('Acknowledge All', icon='done_all', on_click=_ack_all) \
                        .props('flat dense color=positive')
                else:
                    ui.chip('OK').props('dense color=green text-color=white')
            ui.separator()
            if not events:
                ui.label('No active alarms.').classes('text-body2 text-grey-6 q-mt-xs')
            else:
                async def _ack(event_id: str) -> None:
                    await anyio.to_thread.run_sync(
                        lambda eid=event_id: acknowledge_alarm(project_name, eid)
                    )
                    _content.refresh()
                for event in events[:10]:
                    _alarm_event_row(project_name, event, _ack)
                if len(events) > 10:
                    ui.label(f'… and {len(events) - 10} more').classes('text-caption text-grey-7')

    _content()
    ui.timer(30.0, _content.refresh)


# ---------------------------------------------------------------------------
# Device Dashboard — alarm mini-panel
# ---------------------------------------------------------------------------

def DeviceAlarmPanel(project_name: str, device_name: str) -> None:
    """Compact alarm panel for the device dashboard card."""

    @ui.refreshable
    def _content() -> None:
        events = get_pending_alarms(project_name, device_name=device_name)
        count = get_device_alarm_count(project_name, device_name)
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center w-full'):
                ui.label('Alarms').classes('text-subtitle1 font-bold')
                ui.space()
                if count:
                    ui.chip(str(count)).props('dense color=red text-color=white')
                    async def _ack_all() -> None:
                        await anyio.to_thread.run_sync(
                            lambda: acknowledge_all_alarms(project_name, device_name)
                        )
                        _content.refresh()
                    ui.button('Ack All', icon='done_all', on_click=_ack_all) \
                        .props('flat dense color=positive')
                else:
                    ui.chip('OK').props('dense color=green text-color=white')
            ui.separator()
            if not events:
                ui.label('No alarms.').classes('text-body2 text-grey-6 q-mt-xs')
            else:
                async def _ack(event_id: str) -> None:
                    await anyio.to_thread.run_sync(
                        lambda eid=event_id: acknowledge_alarm(project_name, eid)
                    )
                    _content.refresh()
                for event in events[:5]:
                    _alarm_event_row(project_name, event, _ack)

    _content()
    ui.timer(30.0, _content.refresh)


# ---------------------------------------------------------------------------
# Device Alarms Tab — full list
# ---------------------------------------------------------------------------

def DeviceAlarmsTab(project_name: str, device_name: str) -> None:
    """Full alarm panel shown in the Device 'Alarms' tab."""

    @ui.refreshable
    def _content() -> None:
        events = get_pending_alarms(project_name, device_name=device_name)
        count = get_device_alarm_count(project_name, device_name)

        with ui.row().classes('items-center w-full gap-2 q-mb-sm'):
            if count:
                ui.chip(f'{count} unacknowledged').props('dense color=red text-color=white')
                async def _ack_all() -> None:
                    await anyio.to_thread.run_sync(
                        lambda: acknowledge_all_alarms(project_name, device_name)
                    )
                    _content.refresh()
                ui.button('Acknowledge All', icon='done_all', on_click=_ack_all) \
                    .props('flat dense color=positive')
            else:
                ui.chip('No active alarms').props('dense color=green text-color=white')

        if not events:
            ui.label('No alarm events for this device.').classes('text-body2 text-grey-6')
        else:
            async def _ack(event_id: str) -> None:
                await anyio.to_thread.run_sync(
                    lambda eid=event_id: acknowledge_alarm(project_name, eid)
                )
                _content.refresh()
            for event in events:
                with ui.card().classes('w-full q-mb-xs'):
                    _alarm_event_row(project_name, event, _ack)

    _content()
    ui.timer(30.0, _content.refresh)
