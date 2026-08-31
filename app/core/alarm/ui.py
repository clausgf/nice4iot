"""
Alarm UI components.

AlarmConfigCard       — Project/General tab: device-offline + metric rules
ProjectAlarmPanel     — Project Dashboard: alarm summary across all devices
DeviceAlarmPanel      — Device Dashboard: alarms for one device
DeviceAlarmsTab       — Device "Alarms" tab: full list + acknowledgment
"""
from typing import cast

import anyio
import niceview
from nicegui import ui
from niceview.util import confirm_dialog

from app.util import render_datetime
from app.core.alarm.backend import (
    get_alarm_adapter,
    get_alarm_rules_adapter,
    get_pending_alarms,
    get_alarm_count,
    acknowledge_alarm,
    acknowledge_all_alarms,
)
from app.core.alarm.models import AlarmEvent, MetricAlarmRule, DeviceOfflineAlarm, ProvisioningTokenExpiryAlarm
from app.core.telemetry.backend import observed_metrics
from niceview import BoundFieldAdapter, FormAction, FormActionEventArguments, ModelForm


# ---------------------------------------------------------------------------
# Project/General — alarm configuration card
# ---------------------------------------------------------------------------

async def alarm_config_card(project_name: str) -> None:
    """Content for the alarm rules card, rendered inside Project/General (caller provides the card/header)."""
    adapter = get_alarm_adapter(project_name)
    # Observed (kind -> metric names) from the local store, to seed the rule
    # editor's comboboxes with the actual normalized names. Blocking IO, so
    # wrapped per the async-IO rule.
    observed = await anyio.to_thread.run_sync(lambda: observed_metrics(project_name))

    # Built-in rules
    with ui.card().classes('w-full q-mb-sm'):
        ModelForm.from_adapter(
            DeviceOfflineAlarm, BoundFieldAdapter(adapter, 'device_offline'), autosave=True,
            layout=[['is_active:shrink', 'name', 'device_offline_threshold']],
        ).render()

    with ui.card().classes('w-full q-mb-sm'):
        ModelForm.from_adapter(
            ProvisioningTokenExpiryAlarm, BoundFieldAdapter(adapter, 'provisioning_expiry'), autosave=True,
            layout=[['is_active:shrink', 'name', 'token_expiration_threshold']],
        ).render()

    # user defined metric rules
    async def _delete_rule(e: FormActionEventArguments) -> None:
        # form.item is typed as bare BaseModel by niceview; this card is always
        # backed by a MetricAlarmRule adapter.
        item = cast(MetricAlarmRule, e.form.item)
        if not await confirm_dialog("Delete Rule", f"Delete rule '{item.name}'?", ok_label='Delete', ok_role='delete'):
            return
        rules_adapter.delete(rules_adapter.key_from_item(item))
        _rule_list.refresh()

    async def _add_rule(rules_adapter, observed) -> None:
        rules_adapter.create(MetricAlarmRule(name=f'rule_{len(list(rules_adapter))+1}'))
        _rule_list.refresh()

    def _kind_cascade(e) -> None:
        # The kind decides which metrics exist; rebuild so the metric combobox offers
        # that kind's discovered metrics. Autosave has already stored the new kind by
        # the time this fires, so the rebuilt options read it back.
        if e.field_name == 'kind':
            _rule_list.refresh()

    rules_actions = {
        'delete': FormAction(
            icon='delete', tooltip='Delete this rule', props='color=negative', on_click=lambda e: _delete_rule(e)
        )
    }
    rules_layout = [['is_active:shrink', 'name', '@delete:mb-0'],
                    ['kind', 'metric', 'comparison', 'threshold']]
    rules_adapter = get_alarm_rules_adapter(project_name)  # type: ignore

    @ui.refreshable
    def _rule_list() -> None:
        for key, rule in rules_adapter.items():
            # A ui.select always needs options, and they must include the row's own
            # value so a hand-typed kind/metric is not dropped when it is not (yet)
            # among the discovered ones.
            kind_options = sorted(set(observed.keys()) | {rule.kind})
            metric_options = sorted(set(observed.get(rule.kind, [])) | {rule.metric})
            form = ModelForm.from_adapter(
                MetricAlarmRule, rules_adapter, key, autosave=True,
                actions=rules_actions, layout=rules_layout,
                field_infos={
                    'kind': niceview.Field(options=kind_options),
                    'metric': niceview.Field(options=metric_options),
                },
                on_change=_kind_cascade,
            )
            with ui.card().classes('w-full q-mb-xs'):
                form.render()
        ui.button('Add Metric Rule', icon='add').classes('w-full').on_click(lambda: _add_rule(rules_adapter, observed))
    _rule_list()


# ---------------------------------------------------------------------------
# Alarm event list (shared by project and device panels)
# ---------------------------------------------------------------------------

def _alarm_event_row(project_name: str, event: AlarmEvent, on_ack) -> None:
    """Render a single alarm event row."""

    active_color = 'negative' if event.is_active else 'warning'
    active_text = 'active' if event.is_active else 'inactive'
    with ui.row().classes('items-center gap-2 w-full q-py-xs'):
        with ui.column().classes('gap-0 grow'):
            ui.label(f'{event.device_name} — {event.rule_name}').classes('text-body2 font-bold')
            ui.label(event.message).classes('text-caption text-grey-7')
            log = f'Since {render_datetime(event.triggered_at)}'
            if event.last_seen_at and event.last_seen_at > event.triggered_at:
                log += f', last seen at {render_datetime(event.last_seen_at)}'
            if event.last_value:
                log += f' ({event.last_value})'
            if event.is_acknowledged and event.acknowledged_at:
                log += f', acknowledged at {render_datetime(event.acknowledged_at)}'
            ui.label(log).classes('text-caption text-grey-7')
        ui.chip(active_text).props(f'dense color={active_color} text-color=white')
        if event.is_acknowledged:
            # Already acknowledged — static green icon, not interactive
            ui.icon('check').classes('text-xl') \
                .tooltip(f'Acknowledged at {render_datetime(event.acknowledged_at)}')
        else:
            # Needs acknowledgment — clickable button
            ui.button(icon='check', on_click=lambda e=event: on_ack(e.id)) \
                .tooltip('Acknowledge this alarm and remove it from the list if it is no longer active') \
                .props('dense round size=sm')


# ---------------------------------------------------------------------------
# Dashboard — alarm mini-card
# ---------------------------------------------------------------------------

async def dashboard_alarms_card(project_name: str, device_name: str | None = None) -> None:
    """Compact alarm panel for the device dashboard card."""

    @ui.refreshable
    def _content() -> None:
        events: list[AlarmEvent] = get_pending_alarms(project_name, device_name)
        count = get_alarm_count(project_name, device_name)

        with ui.card().tight().classes('w-full'):
            with ui.card_section().props('dense').classes('w-full'):
                # Row 0: title + total count + "ack all" button
                with ui.row().classes('items-center w-full'):
                    ui.label('Alarms').classes('text-subtitle1 font-bold')
                    ui.space()
                    if count:
                        ui.chip(str(count)).props('dense color=negative text-color=white')
                        async def _ack_all() -> None:
                            await anyio.to_thread.run_sync(
                                lambda: acknowledge_all_alarms(project_name, device_name)
                            )
                            _content.refresh()
                        ui.button(icon='done_all', on_click=_ack_all) \
                            .props('dense round size=sm') \
                            .tooltip('Acknowledge all alarms and remove them from the list if they are no longer active')
                    else:
                        ui.chip('OK').props('dense outline color=positive').tooltip('No active alarms')
                ui.separator()

                # Row 1-: list of events (or "no active alarms" if empty)
                if not events:
                    ui.label('No alarms.').classes('text-body2 text-grey-7 q-mt-xs')
                else:
                    async def _ack(event_id: str) -> None:
                        await anyio.to_thread.run_sync(acknowledge_alarm, project_name, event_id)
                        _content.refresh()
                    for event in events[:10]:
                        _alarm_event_row(project_name, event, _ack)
                    if len(events) > 10:
                        ui.label(f'… and {len(events) - 10} more').classes('text-caption text-grey-7')

    _content()
    ui.timer(30.0, _content.refresh)

