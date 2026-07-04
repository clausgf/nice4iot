"""
Device Data Tab — simple time-series visualization of local telemetry.

Telemetry is stored locally in <device_dir>/.device_metrics.jsonl by
write_telemetry() (always-on alongside any configured remote backend).
Each line is: {"ts": "<ISO>", "kind": "<kind>", "v": {<metric>: <value>}}

The panel lets the user pick a time window and a metric, then renders
a Plotly line chart of the selected series.
"""
import datetime

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
            _DataExplorer(project_name, device_name)


class _DataExplorer:
    """Stateful UI component for the telemetry time-series explorer."""

    def __init__(self, project_name: str, device_name: str) -> None:
        self.project_name = project_name
        self.device_name = device_name
        self.window = 'Last 24 h'
        self.kind: str | None = None
        self.metric: str | None = None

        with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
            self.window_select = ui.select(
                list(_WINDOWS.keys()), value=self.window, label='Time window',
            ).props('dense outlined').classes('w-36')
            self.kind_select = ui.select([], label='Kind').props('dense outlined').classes('w-40')
            self.metric_select = ui.select([], label='Metric').props('dense outlined').classes('w-48')
            ui.button(icon='refresh').props('dense flat').tooltip('Refresh').on_click(self._refresh)

        self.summary_row = ui.row().classes('w-full items-center gap-4 q-mt-xs text-caption text-grey-7')
        self.chart = ui.plotly(go.Figure()).classes('w-full')

        self.window_select.on_value_change(lambda e: self._on_window(e.value))
        self.kind_select.on_value_change(lambda e: self._on_kind(e.value))
        self.metric_select.on_value_change(lambda e: self._on_metric(e.value))

        self._refresh()

    def _since(self) -> datetime.datetime | None:
        delta = _WINDOWS.get(self.window)
        return datetime.datetime.now(datetime.timezone.utc) - delta if delta else None

    def _refresh(self, _=None) -> None:
        records = read_local_metrics(self.project_name, self.device_name, since=self._since())
        kinds = sorted({r['kind'] for r in records}) if records else []
        self.kind_select.set_options(kinds)
        if self.kind not in kinds:
            self.kind = kinds[0] if kinds else None
        self.kind_select.set_value(self.kind)
        self._update_metrics(records)

    def _on_window(self, value: str) -> None:
        self.window = value
        self._refresh()

    def _on_kind(self, value: str | None) -> None:
        self.kind = value
        self._update_metrics()

    def _on_metric(self, value: str | None) -> None:
        self.metric = value
        self._draw_chart()

    def _update_metrics(self, records: list | None = None) -> None:
        if records is None:
            records = read_local_metrics(
                self.project_name, self.device_name, kind=self.kind, since=self._since()
            )
        metrics = (
            sorted({k for r in records if r['kind'] == self.kind for k in r['v']})
            if self.kind else []
        )
        self.metric_select.set_options(metrics)
        if self.metric not in metrics:
            self.metric = metrics[0] if metrics else None
        self.metric_select.set_value(self.metric)
        self._draw_chart(records)

    def _draw_chart(self, records: list | None = None) -> None:
        self.summary_row.clear()
        if not self.kind or not self.metric:
            self.chart.update_figure(go.Figure())
            with self.summary_row:
                ui.label(
                    'No telemetry yet. Push data via POST /api/telemetry/{project}/{device}/{kind} '
                    'or run: python tools/device_client.py cycle …'
                ).classes('text-caption text-grey-6')
            return

        if records is None:
            records = read_local_metrics(
                self.project_name, self.device_name, kind=self.kind, since=self._since()
            )
        xs, ys = [], []
        for r in records:
            if r['kind'] == self.kind and self.metric in r['v']:
                try:
                    xs.append(datetime.datetime.fromisoformat(r['ts']))
                    ys.append(float(r['v'][self.metric]))
                except (KeyError, ValueError):
                    continue

        if not xs:
            self.chart.update_figure(go.Figure())
            with self.summary_row:
                ui.label('No data for the selected combination.').classes('text-caption text-grey-6')
            return

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode='lines+markers',
            name=self.metric,
            line={'width': 2},
            marker={'size': 4},
        ))
        fig.update_layout(
            margin={'l': 40, 'r': 10, 't': 10, 'b': 40},
            xaxis_title='Time',
            yaxis_title=self.metric,
            height=300,
        )
        self.chart.update_figure(fig)

        n = len(ys)
        mn, mx, avg = min(ys), max(ys), sum(ys) / n
        with self.summary_row:
            ui.label(f'{n} readings').classes('text-caption text-grey-7')
            ui.label(f'min {mn:.3g}').classes('text-caption text-grey-7')
            ui.label(f'max {mx:.3g}').classes('text-caption text-grey-7')
            ui.label(f'avg {avg:.3g}').classes('text-caption text-grey-7')
