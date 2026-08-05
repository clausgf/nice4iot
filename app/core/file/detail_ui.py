"""
The detail half of the Files card: one file, dispatched by type and size.

JSON opens in a validating CodeMirror editor — with a Form tab whenever the file
is a flat object or an approved schema describes it; recognised text files open
in a plain editor; images (png/jpg/gif/webp ≤ 2 MB) render as an inline preview.
SVG and other binaries stay download-only: untrusted SVG is never rendered inline
(see docs/file-forms.md).

Also home to the three actions every part of the card needs — save, publish,
download — because they all operate on a single file.
"""
import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any, Callable

from nicegui import ui

from app.core.file.backend import publish_file_now
from app.core.file.form import JsonView, approve_schema, plan_json_view
from app.core.file.form_ui import render_form_fields
from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter, OverlayFileEntry
from app.util import atomic_write, human_size

log = logging.getLogger('uvicorn')

# ---------------------------------------------------------------------------
# File-type constants
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str] = {
    '.yaml': 'YAML',  '.yml':  'YAML',
    '.toml': 'TOML',  '.xml':  'XML',
    '.html': 'HTML',  '.md':   'Markdown',
    '.py':   'Python', '.sh':  'Shell',
    '.css':  'CSS',   '.js':   'JavaScript',
}
_TEXT_EXTENSIONS: set[str] = {'.txt', '.log', '.csv', '.ini', '.cfg', '.conf'} | set(_LANG_MAP)
_MAX_VIEWER_SIZE: int = 100 * 1024  # 100 KB — larger text stays download-only

# Images rendered inline as a data: URI. SVG is deliberately excluded — scripts in
# an inline-rendered SVG would execute; larger images stay download-only.
_IMAGE_MIME: dict[str, str] = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp',
}
_MAX_IMAGE_SIZE: int = 2 * 1024 * 1024  # 2 MB

FILE_ICONS: dict[str, str] = {'.json': 'data_object'} | \
    {e: 'image' for e in _IMAGE_MIME} | {e: 'article' for e in _TEXT_EXTENSIONS}

_EDITOR_HEIGHT = 'height: clamp(240px, 55vh, 640px)'


# ---------------------------------------------------------------------------
# Shared write / publish / download actions
# ---------------------------------------------------------------------------

def save_text(path: Path, text: str) -> bool:
    """Atomic write plus a notification when it fails. True if the file was written."""
    try:
        atomic_write(path, text)
        return True
    except OSError as exc:
        ui.notify(f'Save failed: {exc}', type='negative')
        return False


def maybe_publish(path: Path, ctx: FileCtx) -> None:
    if ctx.can_publish:
        asyncio.create_task(publish_file_now(ctx.project_name, ctx.device_name, path))


def download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Chrome shared by the editors
# ---------------------------------------------------------------------------

def _commit(entry: OverlayFileEntry, ctx: FileCtx, text: str, on_saved: Callable[[], Any]) -> None:
    """Write *text* to the file's save path and follow up.

    For an inherited file the save path is the device copy, so this is the
    copy-on-write: the project file stays untouched and the view is re-rendered
    afterwards, now showing the device's own file.
    """
    if not save_text(entry.save_path, text):
        return
    ui.notify(f'Saved {entry.name}', type='positive')
    maybe_publish(entry.save_path, ctx)
    if entry.save_path.name.endswith('.schema.json'):
        # Editing/creating a schema in the UI is admin provenance → auto-approved.
        approve_schema(entry.save_path, ctx.project_name)
    if entry.inherited:
        on_saved()


def _save_button(entry: OverlayFileEntry, on_click: Callable[[], None]) -> None:
    """The save button. Its label spells out the copy-on-write for inherited files."""
    label = 'Save as device file' if entry.inherited else 'Save'
    with ui.row().classes('w-full justify-end q-mt-sm'):
        ui.button(label, on_click=on_click).props('color=primary')


def _banner(icon: str, colour: str, tint: str, text: str):
    """A tinted notice strip above a detail view. Returns the row, so a caller can
    reopen it to append an action button."""
    row = ui.row().classes('w-full items-center gap-2 q-pa-sm rounded-borders') \
        .style(f'background: {tint}')
    with row:
        ui.icon(icon).classes(colour)
        ui.label(text).classes('grow text-body2')
    return row


def _inherited_banner(ctx: FileCtx) -> None:
    _banner('folder_shared', 'text-blue', 'rgba(66,165,245,0.15)',
            f'Inherited from the project. Saving creates a copy for '
            f'{ctx.device_name}; the project file stays unchanged.')


def _schema_pending_banner(schema_path: Path, ctx: FileCtx, on_approve: Callable[[], Any]) -> None:
    with _banner('warning', 'text-orange', 'rgba(255,167,38,0.15)',
                 f'The schema "{schema_path.name}" was uploaded and needs your approval '
                 'before it drives the form.'):
        def _approve() -> None:
            approve_schema(schema_path, ctx.project_name)
            ui.notify(f'Approved {schema_path.name}', type='positive')
            on_approve()
        ui.button('Approve', icon='verified', on_click=_approve).props('dense color=primary')


def _editor_view(adapter: OverlayDirectoryAdapter, key: str, ctx: FileCtx,
                 body: Callable[[OverlayFileEntry, Callable[[], Any]], None]) -> None:
    """Render *body* inside a local refreshable that re-reads the entry first.

    Both editors need this: a copy-on-write save turns an inherited file into the
    device's own, and the view — banner and save-button label included — has to
    follow without navigating away from the detail page.
    """
    @ui.refreshable
    def detail() -> None:
        try:
            cur = adapter.read(key)
        except (KeyError, ValueError):
            ui.label(f'{key!r} not found.').classes('text-negative')
            return
        if cur.inherited:
            _inherited_banner(ctx)
        body(cur, detail.refresh)

    detail()


# ---------------------------------------------------------------------------
# JSON detail — form and raw editor
# ---------------------------------------------------------------------------

def _json_form(entry: OverlayFileEntry, ctx: FileCtx, view: JsonView,
               on_saved: Callable[[], Any]) -> None:
    assert view.fields is not None  # only called for a view that has a Form tab
    collect = render_form_fields(view.fields)

    def _save() -> None:
        if (values := collect()) is None:
            return
        # Merge into the existing object: overwrite only the form's keys, keep the
        # rest (a schema may cover only part of the file).
        merged = dict(view.data)
        merged.update(values)
        _commit(entry, ctx, json.dumps(merged, indent=2, ensure_ascii=False) + '\n', on_saved)

    _save_button(entry, _save)


def _json_raw_editor(entry: OverlayFileEntry, ctx: FileCtx, content: str,
                     on_saved: Callable[[], Any]) -> None:
    editor = (
        ui.codemirror(value=content, language='JSON', line_wrapping=True)
        .classes('w-full border rounded').style(_EDITOR_HEIGHT)
    )

    def _save() -> None:
        try:
            parsed = json.loads(editor.value)
        except json.JSONDecodeError as exc:
            ui.notify(f'Invalid JSON: {exc}', type='negative')
            return
        _commit(entry, ctx, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n', on_saved)

    _save_button(entry, _save)


def _render_json_detail(entry: OverlayFileEntry, ctx: FileCtx, view: JsonView,
                        refresh: Callable[[], Any]) -> None:
    """Render the plan `plan_json_view()` produced. No live sync between the tabs —
    each renders from the on-disk content the plan was built from."""
    if view.pending_schema is not None:
        _schema_pending_banner(view.pending_schema, ctx, on_approve=refresh)
    if view.note:
        ui.label(view.note).classes('text-caption text-grey-7')

    if view.fields is None:
        _json_raw_editor(entry, ctx, view.text, refresh)
        return

    with ui.tabs().classes('w-full') as tabs:
        form_tab = ui.tab('Form')
        raw_tab = ui.tab('Raw')
    with ui.tab_panels(tabs, value=(form_tab if view.form_default else raw_tab)).classes('w-full'):
        with ui.tab_panel(form_tab):
            _json_form(entry, ctx, view, refresh)
        with ui.tab_panel(raw_tab):
            _json_raw_editor(entry, ctx, view.text, refresh)


# ---------------------------------------------------------------------------
# Text, image and download-only detail
# ---------------------------------------------------------------------------

def _render_text_editor(entry: OverlayFileEntry, ctx: FileCtx,
                        refresh: Callable[[], Any]) -> None:
    """Plain-text detail. Text is saved verbatim (no reformatting, unlike JSON)."""
    try:
        content = entry.read_path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return
    editor = (
        ui.codemirror(value=content, line_wrapping=True,
                      language=_LANG_MAP.get(entry.read_path.suffix.lower()))
        .classes('w-full border rounded').style(_EDITOR_HEIGHT)
    )
    _save_button(entry, lambda: _commit(entry, ctx, editor.value, refresh))


def _render_image_preview(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        ui.notify(f'Cannot read file: {exc}', type='negative')
        return
    mime = _IMAGE_MIME.get(path.suffix.lower(), 'application/octet-stream')
    b64 = base64.b64encode(data).decode('ascii')
    ui.image(f'data:{mime};base64,{b64}').classes('w-full') \
        .style('max-height: 70vh; object-fit: contain')


def _render_download_only(path: Path, reason: str) -> None:
    with ui.column().classes('items-start gap-2 q-mt-sm'):
        ui.label(reason).classes('text-body2 text-grey-7')
        ui.button('Download', icon='download',
                  on_click=lambda: download_file(path)).props('outline')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def file_detail(adapter: OverlayDirectoryAdapter, key: str, ctx: FileCtx) -> None:
    """render_detail body for one file, dispatched on type and size."""
    try:
        entry = adapter.read(key)
    except (KeyError, ValueError):
        ui.label(f'{key!r} not found.').classes('text-negative')
        return

    ext = entry.read_path.suffix.lower()
    # The editors re-read the entry and draw their own banner, because a save can
    # turn an inherited file into the device's own one. The static views below cannot.
    if ext == '.json':
        _editor_view(adapter, key, ctx, lambda cur, refresh: _render_json_detail(
            cur, ctx, plan_json_view(cur.read_path, ctx.project_name, ctx.underlay_dir), refresh))
        return
    if ext in _TEXT_EXTENSIONS and entry.size <= _MAX_VIEWER_SIZE:
        _editor_view(adapter, key, ctx, lambda cur, refresh: _render_text_editor(cur, ctx, refresh))
        return

    if entry.inherited:
        _inherited_banner(ctx)
    if ext in _IMAGE_MIME:
        if entry.size <= _MAX_IMAGE_SIZE:
            _render_image_preview(entry.read_path)
        else:
            _render_download_only(entry.read_path,
                                  f'Image too large to preview ({human_size(entry.size)}).')
    elif ext in _TEXT_EXTENSIONS:
        _render_download_only(entry.read_path,
                              f'File too large to edit ({human_size(entry.size)}).')
    else:
        _render_download_only(entry.read_path, 'Binary file — download to view.')
