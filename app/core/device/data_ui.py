"""
Device Data Tab — multi-trace time-series visualization of local telemetry.

Telemetry is stored locally in <device_dir>/.device_metrics.jsonl by
write_telemetry() (always-on alongside any configured remote backend).
Each line is: {"ts": "<ISO>", "kind": "<kind>", "v": {<metric>: <value>}}

The panel lets the user define multiple traces (each with a color, kind and
metric selector), pick a time window, and renders all traces on a shared
Plotly chart. Additional traces can be added with the "+" button; existing
ones removed with the per-row Delete button.
"""
import asyncio
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

_TRACE_COLORS = ['Blue', 'Orange', 'Green', 'Red', 'Purple', 'Brown', 'Pink', 'Gray', 'Olive', 'Teal']
_TRACE_COLOR_HEX = {
    'Blue':   '#1f77b4', 'Orange': '#ff7f0e', 'Green': '#2ca02c', 'Red':    '#d62728',
    'Purple': '#9467bd', 'Brown':  '#8c564b', 'Pink':  '#e377c2', 'Gray':   '#7f7f7f',
    'Olive':  '#bcbd22', 'Teal':   '#17becf',
}

_AUTO_REFRESH_INTERVAL = 30.0  # seconds


async def device_data_panel(project_name: str, device_name: str) -> None:
    """Content of the Data tab."""
    with ui.card().classes('w-full'):
        with ui.expansion('Telemetry Explorer', value=True).classes('w-full').props(
                'dense header-class="text-subtitle1 font-bold"'):
            explorer = _DataExplorer(project_name, device_name)
            await explorer.initialize()


class _DataExplorer:
    """Stateful UI component for the telemetry time-series explorer.

    Each trace is a dict {color, kind, metric}. UI state is stored in
    self.traces; @ui.refreshable _traces_ui() rebuilds the selector rows
    whenever traces are added/removed or a kind changes (which alters metric
    options). Color/metric changes only redraw the chart.
    """

    def __init__(self, project_name: str, device_name: str) -> None:
        self.project_name = project_name
        self.device_name = device_name
        self.window = 'Last 24 h'
        self.traces: list[dict] = [{'color': 'Blue', 'kind': None, 'metric': None}]
        self._records: list = []
        self._auto_refresh = False

        with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
            self.window_select = ui.select(
                list(_WINDOWS.keys()), value=self.window, label='Time window',
            ).props('dense outlined').classes('w-36')
            ui.button(icon='refresh').props('dense flat').tooltip('Refresh').on_click(self._refresh)
            ui.checkbox('Auto-refresh').bind_value(self, '_auto_refresh').tooltip(
                f'Reload every {int(_AUTO_REFRESH_INTERVAL)} s'
            )

        self._traces_ui()
        self.summary_row = ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap')
        self.chart = ui.plotly(go.Figure()).classes('w-full')

        self.window_select.on_value_change(lambda e: self._on_window(e.value))
        ui.timer(_AUTO_REFRESH_INTERVAL, self._auto_refresh_tick)

    @ui.refreshable
    def _traces_ui(self) -> None:
        kinds = sorted({r['kind'] for r in self._records}) if self._records else []
        only_one = len(self.traces) == 1
        for i, trace in enumerate(self.traces):
            metrics = (
                sorted({k for r in self._records if r['kind'] == trace['kind'] for k in r['v']})
                if trace['kind'] else []
            )
            with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
                ui.select(_TRACE_COLORS, value=trace['color'], label='Color').props(
                    'dense outlined').classes('w-28').on_value_change(
                    lambda e, t=trace: self._on_trace_color(t, e.value))
                ui.select(kinds, value=trace['kind'], label='Kind').props(
                    'dense outlined').classes('w-40').on_value_change(
                    lambda e, t=trace: self._on_trace_kind(t, e.value))
                ui.select(metrics, value=trace['metric'], label='Metric').props(
                    'dense outlined').classes('w-48').on_value_change(
                    lambda e, t=trace: self._on_trace_metric(t, e.value))
                ui.button(icon='delete').props(
                    f'dense flat size=sm {"color=negative" if not only_one else "disable"}',
                ).tooltip('Remove trace').on_click(lambda _, idx=i: self._remove_trace(idx))
        ui.button(icon='add').props('dense flat size=sm').tooltip('Add trace').on_click(self._add_trace).classes('q-mt-xs')

    async def initialize(self) -> None:
        await self._refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _since(self) -> datetime.datetime | None:
        delta = _WINDOWS.get(self.window)
        return datetime.datetime.now(datetime.timezone.utc) - delta if delta else None

    def _first_metric(self, kind: str | None) -> str | None:
        if not kind:
            return None
        metrics = sorted({k for r in self._records if r['kind'] == kind for k in r['v']})
        return metrics[0] if metrics else None

    async def _auto_refresh_tick(self) -> None:
        if self._auto_refresh:
            await self._refresh()

    # ------------------------------------------------------------------
    # Data loading (async IO)
    # ------------------------------------------------------------------

    async def _refresh(self, _=None) -> None:
        self._records = await asyncio.to_thread(
            read_local_metrics, self.project_name, self.device_name, since=self._since()
        )
        kinds = sorted({r['kind'] for r in self._records}) if self._records else []
        for trace in self.traces:
            if trace['kind'] not in kinds:
                trace['kind'] = kinds[0] if kinds else None
                trace['metric'] = None
            if trace['kind'] and trace['metric'] is None:
                trace['metric'] = self._first_metric(trace['kind'])
        self._traces_ui.refresh()
        self._draw_chart_ui()

    async def _on_window(self, value: str) -> None:
        self.window = value
        await self._refresh()

    # ------------------------------------------------------------------
    # Trace event handlers (sync — no IO)
    # ------------------------------------------------------------------

    def _on_trace_color(self, trace: dict, color: str) -> None:
        trace['color'] = color
        self._draw_chart_ui()

    def _on_trace_kind(self, trace: dict, kind: str | None) -> None:
        trace['kind'] = kind
        trace['metric'] = self._first_metric(kind)
        self._traces_ui.refresh()
        self._draw_chart_ui()

    def _on_trace_metric(self, trace: dict, metric: str | None) -> None:
        trace['metric'] = metric
        self._draw_chart_ui()

    def _add_trace(self) -> None:
        colors_used = {t['color'] for t in self.traces}
        color = next((c for c in _TRACE_COLORS if c not in colors_used), _TRACE_COLORS[0])
        kinds = sorted({r['kind'] for r in self._records}) if self._records else []
        kind = kinds[0] if kinds else None
        self.traces.append({'color': color, 'kind': kind, 'metric': self._first_metric(kind)})
        self._traces_ui.refresh()
        self._draw_chart_ui()

    def _remove_trace(self, idx: int) -> None:
        if len(self.traces) > 1:
            self.traces.pop(idx)
        self._traces_ui.refresh()
        self._draw_chart_ui()

    # ------------------------------------------------------------------
    # Chart rendering (sync — uses cached records)
    # ------------------------------------------------------------------

    def _draw_chart_ui(self) -> None:
        self.summary_row.clear()
        fig = go.Figure()
        has_data = False

        for trace in self.traces:
            if not trace['kind'] or not trace['metric']:
                continue
            xs, ys = [], []
            for r in self._records:
                if r['kind'] == trace['kind'] and trace['metric'] in r['v']:
                    try:
                        xs.append(datetime.datetime.fromisoformat(r['ts']))
                        ys.append(float(r['v'][trace['metric']]))
                    except (KeyError, ValueError):
                        continue
            if not xs:
                continue
            has_data = True
            color = _TRACE_COLOR_HEX.get(trace['color'], '#1f77b4')
            label = f"{trace['kind']}/{trace['metric']}"
            fig.add_trace(go.Scatter(
                x=xs, y=ys,
                mode='lines+markers',
                name=label,
                line={'width': 2, 'color': color},
                marker={'size': 4, 'color': color},
            ))
            n = len(ys)
            mn, mx, avg = min(ys), max(ys), sum(ys) / n
            with self.summary_row:
                ui.label(f'{label}:  n={n}  min={mn:.3g}  max={mx:.3g}  avg={avg:.3g}') \
                    .style(f'color: {color}').classes('text-caption')

        if has_data:
            fig.update_layout(
                margin={'l': 40, 'r': 10, 't': 10, 'b': 40},
                xaxis_title='Time',
                height=320,
                legend={'orientation': 'h', 'y': -0.25},
            )
        else:
            with self.summary_row:
                ui.label(
                    'No telemetry yet. Push data via POST /api/telemetry/{project}/{device}/{kind} '
                    'or run: python tools/device_client.py cycle …'
                ).classes('text-caption text-grey-6')

        self.chart.update_figure(fig)
