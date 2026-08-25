"""
Device Data Tab — a list of plots, each a multi-trace time-series visualization
of telemetry.

Data comes from read_series(): the project's configured telemetry backend
(e.g. VictoriaMetrics via the Prometheus query API) when one is set up,
falling back to the local JSONL ring buffer
(<device_dir>/.device_metrics.jsonl, written by write_telemetry() alongside
any remote backend). A chip next to the chart shows which source is active.

Each plot lets the user define multiple traces (each with a color, kind and
metric selector, rendered with niceview's Field/render_field), pick a time
window and title, and renders all traces on a shared Plotly chart. Traces are
added/removed with the row "+"/Delete buttons; whole plots with the "Add
plot" button above the list and each card's own Delete button.

The list of plots is persisted per device in ``.data_view.json`` and restored
on the next visit (see read_data_views / save_data_views).
"""
import asyncio
import datetime
from typing import Callable

import anyio
import plotly.graph_objects as go
from nicegui import ui
from niceview import Field, render_field

from app.core.telemetry.backend import label_history, read_data_views, read_series, save_data_views
from app.core.telemetry.models import DataTrace, DataView, MetricSeries

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

# Colours for label change-markers (vertical lines), distinct from the trace hues above.
_MARKER_COLORS = ['#7f7f7f', '#8c564b', '#bcbd22', '#17becf', '#e377c2', '#9467bd']


def _select_field(label: str, options: list[str], value: str | None, classes: str) -> ui.select:
    """A select box built via niceview's Field/render_field, or — when there are
    currently no options — a plain ui.select: niceview's render_field() raises on
    an empty option list (it treats that as "undefined"), but an empty Kind/Metric
    list is a real, temporary state here (before telemetry has loaded, or a kind
    with no metrics yet).

    classes must go into the Field(...) itself, not a later .classes(classes)
    call: app.main.py sets niceview's app-wide default_classes='w-full', which
    render_field() falls back to for any Field with no classes of its own —
    chaining .classes() afterward only *adds* shrink/grow on top of that
    leftover w-full rather than replacing it, leaving every field full-width
    regardless of shrink/grow."""
    if options:
        field = Field(label=label, widget_type='ui.select', field_type=str, options=options, classes=classes)
        widget = render_field(field, value)
    else:
        widget = ui.select(options, value=value, label=label).classes(classes)
    return widget.props('dense outlined')


_DASHBOARD_CHART_HEIGHT = 180


async def dashboard_plot_card(project_name: str, device_name: str, view: DataView) -> None:
    """A small, read-only rendering of one 'Show on dashboard' plot for the Device
    Dashboard tab — no controls, tight margins, sized to sit in the card grid
    alongside the status/timeline cards."""
    since = datetime.datetime.now(datetime.timezone.utc) - _WINDOWS[view.window] \
        if _WINDOWS.get(view.window) else None
    series, _source = await read_series(project_name, device_name, since=since)

    fig = go.Figure()
    has_data = False
    for trace in view.traces:
        if not trace.kind or not trace.metric:
            continue
        found = next((s for s in series if s.kind == trace.kind and s.metric == trace.metric), None)
        if found is None or not found.points:
            continue
        has_data = True
        fig.add_trace(go.Scatter(
            x=[p[0] for p in found.points], y=[p[1] for p in found.points],
            mode='lines', name=f'{trace.kind}/{trace.metric}',
            line={'width': 2, 'color': _TRACE_COLOR_HEX.get(trace.color, '#1f77b4')},
        ))
    fig.update_layout(
        title={'text': view.title, 'x': 0.02, 'font': {'size': 13}},
        margin={'l': 32, 'r': 8, 't': 28, 'b': 20},
        height=_DASHBOARD_CHART_HEIGHT,
        showlegend=len(view.traces) > 1,
        legend={'orientation': 'h', 'y': -0.3, 'font': {'size': 9}},
    )
    with ui.card().classes('w-full').style('padding: 4px'):
        if has_data:
            ui.plotly(fig).classes('w-full')
        else:
            with ui.column().classes('w-full items-center justify-center gap-1').style(
                f'height: {_DASHBOARD_CHART_HEIGHT}px'):
                ui.label(view.title).classes('text-caption text-weight-medium')
                ui.label('No data').classes('text-caption text-grey-7')


async def device_data_panel(project_name: str, device_name: str) -> None:
    """Content of the Data tab: a list of plots, each its own _DataExplorer card."""
    views = await anyio.to_thread.run_sync(lambda: read_data_views(project_name, device_name))
    explorers: list[_DataExplorer] = []

    def _persist() -> None:
        """Write every plot's current config off the event loop (fire-and-forget).
        Rapid successive saves are fine (last wins)."""
        snapshot = [e.to_view() for e in explorers]
        asyncio.create_task(anyio.to_thread.run_sync(
            lambda: save_data_views(project_name, device_name, snapshot)))

    def _remove(explorer: '_DataExplorer') -> None:
        explorers.remove(explorer)
        explorer.card.delete()
        _persist()

    async def _add_plot(_=None) -> None:
        with container:
            explorer = _DataExplorer(project_name, device_name, DataView(),
                                     on_change=_persist, on_delete=_remove)
        explorers.append(explorer)
        await explorer.initialize()
        _persist()

    with ui.row().classes('w-full'):
        ui.label('Telemetry explorer').classes('text-h6')
        ui.space()
        ui.button(icon='add').tooltip('Add plot').props('round').on_click(_add_plot)

    container = ui.column().classes('w-full gap-2')
    with container:
        for view in (views or [DataView()]):
            explorers.append(_DataExplorer(project_name, device_name, view,
                                           on_change=_persist, on_delete=_remove))
    for explorer in explorers:
        await explorer.initialize()


class _DataExplorer:
    """Stateful UI component for one plot of the telemetry time-series explorer.

    Each trace is a dict {color, kind, metric}. UI state is stored in
    self.traces; @ui.refreshable _traces_ui() rebuilds the selector rows
    whenever traces are added/removed or a kind changes (which alters metric
    options). Color/metric changes only redraw the chart.

    ``on_change`` is called after every persisted edit (trace, window, title,
    markers, dashboard flag); the container (device_data_panel) owns writing
    the whole plot list to disk. ``on_delete`` is called with self when the
    card's own Delete button is clicked.
    """

    def __init__(self, project_name: str, device_name: str, view: DataView,
                 on_change: Callable[[], None], on_delete: Callable[['_DataExplorer'], None]) -> None:
        self.project_name = project_name
        self.device_name = device_name
        self.on_change = on_change
        self.on_delete = on_delete
        # Restore the persisted config; fall back to defaults.
        self.window = view.window if view.window in _WINDOWS else 'Last 24 h'
        self.traces: list[dict] = (
            [t.model_dump() for t in view.traces] if view.traces
            else [{'color': 'Blue', 'kind': None, 'metric': None}]
        )
        self.marker_labels: list[str] = list(view.marker_labels)
        self._title: str = view.title
        self._series: list[MetricSeries] = []
        self._source: str = 'local'
        self._history: dict[str, list[tuple[datetime.datetime, str]]] = {}
        self._auto_refresh = False
        self._show_on_dashboard = view.show_on_dashboard

        self.card = ui.card().classes('w-full')
        with self.card:
            with ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap'):
                title_field = Field(label='Title', widget_type='ui.input', field_type=str, classes='grow')
                title_input = render_field(title_field, self._title)
                title_input.props('dense outlined').on_value_change(lambda e: self._on_title(e.value))

                window_field = Field(label='Time', widget_type='ui.select', field_type=str,
                                     options=list(_WINDOWS.keys()), classes='shrink')
                self.window_select = render_field(window_field, self.window)
                self.window_select.props('dense outlined')

                ui.button(icon='refresh').props('dense flat').tooltip('Refresh').on_click(self._refresh)
                ui.switch().bind_value(self, '_auto_refresh').tooltip(
                    f'Reload every {int(_AUTO_REFRESH_INTERVAL)} s'
                )
                self._markers_ui()

                dashboard_field = Field(widget_type='ui.switch', field_type=bool, classes='shrink')
                dashboard_switch = render_field(dashboard_field, self._show_on_dashboard)
                dashboard_switch.tooltip('Show on dashboard').on_value_change(
                    lambda e: self._on_show_on_dashboard(e.value))

                ui.button(icon='delete').props('dense round color=negative').tooltip('Remove plot') \
                    .on_click(lambda: self.on_delete(self))

            self._traces_ui()
            self.chart = ui.plotly(go.Figure()).classes('w-full')
            self.summary_row = ui.row().classes('w-full items-center gap-4 q-mt-xs flex-wrap')

            self.window_select.on_value_change(lambda e: self._on_window(e.value))
            ui.timer(_AUTO_REFRESH_INTERVAL, self._auto_refresh_tick)

    def to_view(self) -> DataView:
        """The current (possibly unsaved-to-disk-until-now) state as a DataView."""
        return DataView(title=self._title, window=self.window, show_on_dashboard=self._show_on_dashboard,
                        traces=[DataTrace(**t) for t in self.traces], marker_labels=self.marker_labels)

    @ui.refreshable
    def _traces_ui(self) -> None:
        """One niceview-rendered row of fields per trace — a repeating group over
        self.traces. Kind/Metric options are recomputed on every refresh (they
        depend on the currently loaded series), so the Field specs are built fresh
        each time rather than once."""
        kinds = self._kinds()
        only_one = len(self.traces) == 1
        for i, trace in enumerate(self.traces):
            metrics = self._metrics_for(trace['kind'])
            with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
                _select_field('Color', _TRACE_COLORS, trace['color'], 'shrink').on_value_change(
                    lambda e, t=trace: self._on_trace_color(t, e.value))

                # value must be a current option or NiceGUI raises — on the first
                # render (before data loads) a restored kind/metric may not be in
                # the options yet; _refresh() reloads and refreshes with valid values.
                _select_field('Kind', kinds, trace['kind'] if trace['kind'] in kinds else None, 'grow') \
                    .on_value_change(lambda e, t=trace: self._on_trace_kind(t, e.value))

                _select_field('Metric', metrics, trace['metric'] if trace['metric'] in metrics else None, 'grow') \
                    .on_value_change(lambda e, t=trace: self._on_trace_metric(t, e.value))

                ui.button(icon='delete').props(
                    f'dense round color=negative {"disable" if only_one else ""}',
                ).tooltip('Remove trace').on_click(lambda _, idx=i: self._remove_trace(idx))
                # add button in the last row only (not per-trace) to avoid confusion about which trace is added
                if i == len(self.traces) - 1:
                    ui.button(icon='add').props('dense round').tooltip('Add trace').on_click(self._add_trace)

    @ui.refreshable
    def _markers_ui(self) -> None:
        keys = self._label_keys()
        value = [k for k in self.marker_labels if k in keys]
        ui.select(
            keys, value=value, multiple=True, label='Label markers',
        ).props('dense outlined use-chips').classes('w-48').tooltip(
            'Overlay vertical markers where the selected labels change'
        ).on_value_change(lambda e: self._on_markers(e.value))

    async def initialize(self) -> None:
        await self._refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _since(self) -> datetime.datetime | None:
        delta = _WINDOWS.get(self.window)
        return datetime.datetime.now(datetime.timezone.utc) - delta if delta else None

    def _label_keys(self) -> list[str]:
        return sorted(self._history.keys())

    def _kinds(self) -> list[str]:
        return sorted({s.kind for s in self._series})

    def _metrics_for(self, kind: str | None) -> list[str]:
        if not kind:
            return []
        return sorted({s.metric for s in self._series if s.kind == kind})

    def _find_series(self, kind: str | None, metric: str | None) -> MetricSeries | None:
        return next((s for s in self._series if s.kind == kind and s.metric == metric), None)

    def _first_metric(self, kind: str | None) -> str | None:
        metrics = self._metrics_for(kind)
        return metrics[0] if metrics else None

    async def _auto_refresh_tick(self) -> None:
        if self._auto_refresh:
            await self._refresh()

    def _save_view(self) -> None:
        """Tell the container to persist every plot's current config. Called on
        explicit user changes; rapid successive saves are fine (last wins)."""
        self.on_change()

    # ------------------------------------------------------------------
    # Data loading (async IO)
    # ------------------------------------------------------------------

    async def _refresh(self, _=None) -> None:
        since = self._since()
        self._series, self._source = await read_series(
            self.project_name, self.device_name, since=since
        )
        self._history = await anyio.to_thread.run_sync(
            lambda: label_history(self.project_name, self.device_name, since=since)
        )
        kinds = self._kinds()
        for trace in self.traces:
            if trace['kind'] not in kinds:
                trace['kind'] = kinds[0] if kinds else None
                trace['metric'] = None
            if trace['kind'] and trace['metric'] is None:
                trace['metric'] = self._first_metric(trace['kind'])
        self._traces_ui.refresh()
        self._markers_ui.refresh()
        self._draw_chart_ui()

    async def _on_window(self, value: str) -> None:
        self.window = value
        self._save_view()
        await self._refresh()

    # ------------------------------------------------------------------
    # Plot-level event handlers (sync — no IO)
    # ------------------------------------------------------------------

    def _on_title(self, value: str) -> None:
        self._title = value
        self._save_view()
        self._draw_chart_ui()

    def _on_show_on_dashboard(self, value: bool) -> None:
        self._show_on_dashboard = value
        self._save_view()

    # ------------------------------------------------------------------
    # Trace event handlers (sync — no IO)
    # ------------------------------------------------------------------

    def _on_trace_color(self, trace: dict, color: str) -> None:
        trace['color'] = color
        self._save_view()
        self._draw_chart_ui()

    def _on_trace_kind(self, trace: dict, kind: str | None) -> None:
        trace['kind'] = kind
        trace['metric'] = self._first_metric(kind)
        self._save_view()
        self._traces_ui.refresh()
        self._draw_chart_ui()

    def _on_trace_metric(self, trace: dict, metric: str | None) -> None:
        trace['metric'] = metric
        self._save_view()
        self._draw_chart_ui()

    def _on_markers(self, value: list[str] | None) -> None:
        self.marker_labels = list(value or [])
        self._save_view()
        self._draw_chart_ui()

    def _add_trace(self) -> None:
        colors_used = {t['color'] for t in self.traces}
        color = next((c for c in _TRACE_COLORS if c not in colors_used), _TRACE_COLORS[0])
        kinds = self._kinds()
        kind = kinds[0] if kinds else None
        self.traces.append({'color': color, 'kind': kind, 'metric': self._first_metric(kind)})
        self._save_view()
        self._traces_ui.refresh()
        self._draw_chart_ui()

    def _remove_trace(self, idx: int) -> None:
        if len(self.traces) > 1:
            self.traces.pop(idx)
        self._save_view()
        self._traces_ui.refresh()
        self._draw_chart_ui()

    # ------------------------------------------------------------------
    # Chart rendering (sync — uses cached records)
    # ------------------------------------------------------------------

    def _draw_chart_ui(self) -> None:
        self.summary_row.clear()
        with self.summary_row:
            source_label = 'local buffer' if self._source == 'local' else self._source
            ui.chip(f'Source: {source_label}').props('dense outline square').classes('text-caption')
        fig = go.Figure()
        has_data = False

        for trace in self.traces:
            if not trace['kind'] or not trace['metric']:
                continue
            series = self._find_series(trace['kind'], trace['metric'])
            if series is None or not series.points:
                continue
            xs = [p[0] for p in series.points]
            ys = [p[1] for p in series.points]
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
            # B) Overlay a vertical marker wherever a selected label's value changed.
            for i, key in enumerate([k for k in self.marker_labels if k in self._history]):
                mcolor = _MARKER_COLORS[i % len(_MARKER_COLORS)]
                for ts, value in self._history[key]:
                    fig.add_vline(
                        x=ts, line_width=1, line_dash='dot', line_color=mcolor,
                        annotation_text=f'{key}: {value}', annotation_position='top',
                        annotation_font_size=9, annotation_font_color=mcolor,
                    )
            fig.update_layout(
                title={'text': self._title, 'x': 0.02, 'font': {'size': 14}},
                margin={'l': 40, 'r': 10, 't': 40, 'b': 40},
                xaxis_title='Time',
                height=320,
                legend={'orientation': 'h', 'y': -0.25},
            )
        else:
            with self.summary_row:
                ui.label(
                    'No telemetry yet. Push data via POST /api/telemetry/{project}/{device}/{kind}.'
                ).classes('text-caption text-grey-7')

        self.chart.update_figure(fig)
