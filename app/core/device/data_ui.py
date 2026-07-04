"""
Device Data Tab — simple time-series visualization of local telemetry.

Telemetry is stored locally in <device_dir>/.device_metrics.jsonl by
write_telemetry() (always-on alongside any configured remote backend).
Each line is: {"ts": "<ISO>", "kind": "<kind>", "v": {<metric>: <value>}}

The panel lets the user pick a time window and a metric, then renders
a Plotly line chart of the selected series.
"""
import datetime
from collections import defaultdict

import plotly.graph_objects as go
from nicegui import ui

from app.core.telemetry.backend import read_local_metrics

import logging
log = logging.getLogger("uvicorn")

_WINDOWS = {
    'Last 1 h':   datetime.timedelta(hours=1),
    'Last 6 h':   datetime.timedelta(hours=6),
    'Last 24 h':  datetime.timedelta(hours=24),
    'Last 7 d':   datetime.timedelta(days=7),
    'All':        None,
}


def device_data_panel(project_name: str, device_name: str) -> None:
    """Content of the Data tab."""
    with ui.card().classes('w-full'):
        with ui.expansion('Telemetry Explorer', value=True).classes('w-full').props(
                'dense header-class="text-subtitle1 font-bold"'):
            _data_explorer(project_name, device_name)


def _data_explorer(project_name: str, device_name: str) -> None:
    # State
    state = {
        'window': 'Last 24 h',
        'kind': None,
        'metric': None,
    }

    # --- Controls row ---
    with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
        window_select = ui.select(
            list(_WINDOWS.keys()),
            value=state['window'],
            label='Time window',
        ).props('dense outlined').classes('w-36')

        kind_select = ui.select(
            [],
            label='Kind',
        ).props('dense outlined').classes('w-40')

        metric_select = ui.select(
            [],
            label='Metric',
        ).props('dense outlined').classes('w-48')

        ui.button(icon='refresh').props('dense flat').tooltip('Refresh').on_click(
            lambda: _refresh(project_name, device_name, state, kind_select, metric_select, chart, summary_row)
        )

    summary_row = ui.row().classes('w-full items-center gap-4 q-mt-xs text-caption text-grey-7')

    # --- Chart ---
    chart = ui.plotly(go.Figure()).classes('w-full')

    # --- Wiring ---
    def on_window_change(e) -> None:
        state['window'] = e.value
        _refresh(project_name, device_name, state, kind_select, metric_select, chart, summary_row)

    def on_kind_change(e) -> None:
        state['kind'] = e.value
        _update_metrics(project_name, device_name, state, metric_select, chart, summary_row)

    def on_metric_change(e) -> None:
        state['metric'] = e.value
        _draw_chart(project_name, device_name, state, chart, summary_row)

    window_select.on_value_change(on_window_change)
    kind_select.on_value_change(on_kind_change)
    metric_select.on_value_change(on_metric_change)

    # Initial load
    _refresh(project_name, device_name, state, kind_select, metric_select, chart, summary_row)


def _since(state: dict) -> datetime.datetime | None:
    delta = _WINDOWS.get(state['window'])
    if delta is None:
        return None
    return datetime.datetime.now(datetime.timezone.utc) - delta


def _refresh(project_name, device_name, state, kind_select, metric_select, chart, summary_row) -> None:
    """Reload kinds from file and refresh selects + chart."""
    records = read_local_metrics(project_name, device_name, since=_since(state))
    kinds = sorted({r['kind'] for r in records}) if records else []

    kind_select.set_options(kinds)
    if state['kind'] not in kinds:
        state['kind'] = kinds[0] if kinds else None
    kind_select.set_value(state['kind'])

    _update_metrics(project_name, device_name, state, metric_select, chart, summary_row, records=records)


def _update_metrics(project_name, device_name, state, metric_select, chart, summary_row, records=None) -> None:
    """Update the metric select options based on selected kind."""
    if records is None:
        records = read_local_metrics(project_name, device_name, kind=state['kind'], since=_since(state))

    if state['kind']:
        metrics = sorted({k for r in records if r['kind'] == state['kind'] for k in r['v']})
    else:
        metrics = []

    metric_select.set_options(metrics)
    if state['metric'] not in metrics:
        state['metric'] = metrics[0] if metrics else None
    metric_select.set_value(state['metric'])

    _draw_chart(project_name, device_name, state, chart, summary_row, records=records)


def _draw_chart(project_name, device_name, state, chart, summary_row, records=None) -> None:
    summary_row.clear()
    if not state['kind'] or not state['metric']:
        chart.update_figure(go.Figure())
        with summary_row:
            ui.label('No data — push telemetry to see charts.').classes('text-caption text-grey-6')
        return

    if records is None:
        records = read_local_metrics(project_name, device_name, kind=state['kind'], since=_since(state))

    xs, ys = [], []
    for r in records:
        if r['kind'] == state['kind'] and state['metric'] in r['v']:
            try:
                ts = datetime.datetime.fromisoformat(r['ts'])
                xs.append(ts)
                ys.append(float(r['v'][state['metric']]))
            except (KeyError, ValueError):
                continue

    if not xs:
        chart.update_figure(go.Figure())
        with summary_row:
            ui.label('No data for the selected combination.').classes('text-caption text-grey-6')
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs,
        y=ys,
        mode='lines+markers',
        name=state['metric'],
        line={'width': 2},
        marker={'size': 4},
    ))
    fig.update_layout(
        margin={'l': 40, 'r': 10, 't': 10, 'b': 40},
        xaxis_title='Time',
        yaxis_title=state['metric'],
        height=300,
    )
    chart.update_figure(fig)

    # Summary stats
    n = len(ys)
    mn, mx, avg = min(ys), max(ys), sum(ys) / n
    with summary_row:
        ui.label(f'{n} readings').classes('text-caption text-grey-7')
        ui.label(f'min {mn:.3g}').classes('text-caption text-grey-7')
        ui.label(f'max {mx:.3g}').classes('text-caption text-grey-7')
        ui.label(f'avg {avg:.3g}').classes('text-caption text-grey-7')
