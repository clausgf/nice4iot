"""
Device / Project Files — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

The device tab shows both in **one** list: the device's own files layered over the
project's, with inherited entries marked by a chip (see `file_overlay.py`). Writes
never reach the underlay — saving an inherited file copies it to the device.

Built on niceview's DrillDownWrapper over a DirectoryAdapter in all-files mode
(mixed extensions, keyed by full filename): the list drills down into a per-file
detail view. JSON opens in a validating CodeMirror editor, recognised text files
in a plain editor, images (png/jpg/gif/webp ≤ 2 MB) as an inline preview; SVG and
other binaries stay download-only (untrusted SVG is never rendered inline — see
docs/file-forms.md).
"""
import asyncio
import base64
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, NamedTuple

import anyio
from nicegui import ui
from niceview import DrillDownWrapper, FileEntry
from niceview.util import confirm_dialog

from app.core.device.backend import get_device_path
from app.core.device.file_form import (
    FormField,
    approve_schema,
    fields_from_schema,
    infer_flat_fields,
    is_schema_approved,
    load_schema,
    resolve_schema_path,
    validate_field,
)
from app.core.device.file_overlay import FileRef, OverlayDirectoryAdapter, resolve_ref
from app.paths import project_dir as get_project_dir
from app.util import atomic_write, is_valid_upload_filename, render_datetime

import logging
log = logging.getLogger("uvicorn")

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

_FILE_ICONS: dict[str, str] = {'.json': 'data_object'} | \
    {e: 'image' for e in _IMAGE_MIME} | {e: 'article' for e in _TEXT_EXTENSIONS}


def _human_size(n: int) -> str:
    return f'{n / 1024:.1f} KB' if n < 1024 * 1024 else f'{n / 1024 / 1024:.1f} MB'


class _Ctx(NamedTuple):
    """Per-card context: constant for the lifetime of one Files card.

    device_name is None for the project Files tab (no device to publish to), and
    underlay_dir is None wherever nothing is inherited — which is the same card.
    """
    project_name: str
    device_name: str | None
    mqtt_enabled: bool
    underlay_dir: Path | None = None

    @property
    def can_publish(self) -> bool:
        return bool(self.mqtt_enabled and self.project_name and self.device_name)


# ---------------------------------------------------------------------------
# Shared write / publish / download helpers
# ---------------------------------------------------------------------------

def _save_text(path: Path, text: str) -> bool:
    """Atomic write plus a notification when it fails. True if the file was written."""
    try:
        atomic_write(path, text)
        return True
    except OSError as exc:
        ui.notify(f'Save failed: {exc}', type='negative')
        return False


def _maybe_publish(path: Path, ctx: _Ctx) -> None:
    if ctx.can_publish:
        from app.core.file.backend import publish_file_now
        asyncio.create_task(publish_file_now(ctx.project_name, ctx.device_name, path))


def _download_file(path: Path) -> None:
    try:
        ui.download(path.read_bytes(), filename=path.name)
    except Exception as e:
        ui.notify(f'Download failed: {e}', type='negative')


# ---------------------------------------------------------------------------
# Detail view (render_detail) — one file, dispatched by type
# ---------------------------------------------------------------------------

def _render_widget(field: FormField, label: str) -> Callable[[], Any]:
    """Render the input widget for *field*; return a getter for its value.

    Only text goes into text-rendering widgets (labels, options) — schema-supplied
    strings are never passed to ui.markdown/ui.html, so a schema cannot inject markup.
    """
    if field.kind == 'boolean':
        w = ui.switch(label, value=bool(field.value))
        return lambda: bool(w.value)
    if field.kind == 'enum':
        options = [str(x) for x in (field.enum or [])]
        w = ui.select(options, label=label, value=field.value if field.value in options else None) \
            .props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'textarea':
        w = ui.textarea(label, value=field.value or '').props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'date':
        w = ui.input(label, value=field.value or '').props('outlined dense type=date').classes('w-full')
        return lambda: w.value or None
    if field.kind == 'integer':
        w = ui.number(label, value=field.value, precision=0, step=1,
                      min=field.minimum, max=field.maximum).props('outlined dense').classes('w-full')
        return lambda: int(w.value) if w.value is not None else None
    if field.kind == 'number':
        w = ui.number(label, value=field.value, min=field.minimum, max=field.maximum) \
            .props('outlined dense').classes('w-full')
        return lambda: w.value
    if field.kind == 'string_list':
        w = ui.input_chips(label, value=list(field.value or [])).props('outlined dense').classes('w-full')
        return lambda: list(w.value or [])
    w = ui.input(label, value=field.value or '').props('outlined dense').classes('w-full')
    if field.max_length:
        w.props(f'maxlength={field.max_length}')
    return lambda: w.value


def _render_form_field(field: FormField) -> Callable[[], Any]:
    label = (field.label or field.key) + (' *' if field.required else '')
    with ui.column().classes('w-full gap-0'):
        getter = _render_widget(field, label)
        if field.description:
            ui.label(field.description).classes('text-caption text-grey-7')
    return getter


def _commit(ref: FileRef, ctx: _Ctx, text: str, on_saved: Callable[[], Any]) -> None:
    """Write *text* to the file's save path and follow up.

    For an inherited file the save path is the device copy, so this is the
    copy-on-write: the project file stays untouched and the view is re-rendered
    afterwards, now showing the device's own file.
    """
    if not _save_text(ref.save_path, text):
        return
    ui.notify(f'Saved {ref.key}', type='positive')
    _maybe_publish(ref.save_path, ctx)
    if ref.save_path.name.endswith('.schema.json'):
        # Editing/creating a schema in the UI is admin provenance → auto-approved.
        approve_schema(ref.save_path, ctx.project_name)
    if ref.inherited:
        on_saved()


def _save_button(ref: FileRef, on_click: Callable[[], None]) -> None:
    """The save button. Its label spells out the copy-on-write for inherited files."""
    label = 'Save as device file' if ref.inherited else 'Save'
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


def _inherited_banner(ctx: _Ctx) -> None:
    _banner('folder_shared', 'text-blue', 'rgba(66,165,245,0.15)',
            f'Inherited from the project. Saving creates a copy for '
            f'{ctx.device_name}; the project file stays unchanged.')


def _json_form(ref: FileRef, ctx: _Ctx, original: dict, fields: list[FormField],
               on_saved: Callable[[], Any]) -> None:
    getters: dict[str, Callable[[], Any]] = {}
    with ui.column().classes('w-full gap-3'):
        if not fields:
            ui.label('Empty object — nothing to edit as a form.').classes('text-caption text-grey-7')
        for field in fields:
            getters[field.key] = _render_form_field(field)

    def _save() -> None:
        values = {f.key: getters[f.key]() for f in fields}
        for f in fields:
            if (err := validate_field(f, values[f.key])) is not None:
                ui.notify(err, type='negative')
                return
        # Merge into the existing object: overwrite only the form's keys, keep the
        # rest (a schema may cover only part of the file).
        merged = dict(original)
        merged.update(values)
        _commit(ref, ctx, json.dumps(merged, indent=2, ensure_ascii=False) + '\n', on_saved)

    _save_button(ref, _save)


def _json_raw_editor(ref: FileRef, ctx: _Ctx, content: str,
                     on_saved: Callable[[], Any]) -> None:
    editor = (
        ui.codemirror(value=content, language='JSON', line_wrapping=True)
        .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
    )

    def _save() -> None:
        try:
            parsed = json.loads(editor.value)
        except json.JSONDecodeError as exc:
            ui.notify(f'Invalid JSON: {exc}', type='negative')
            return
        _commit(ref, ctx, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n', on_saved)

    _save_button(ref, _save)


def _schema_pending_banner(schema_path: Path, ctx: _Ctx, on_approve: Callable[[], Any]) -> None:
    with _banner('warning', 'text-orange', 'rgba(255,167,38,0.15)',
                 f'The schema "{schema_path.name}" was uploaded and needs your approval '
                 'before it drives the form.'):
        def _approve() -> None:
            approve_schema(schema_path, ctx.project_name)
            ui.notify(f'Approved {schema_path.name}', type='positive')
            on_approve()
        ui.button('Approve', icon='verified', on_click=_approve).props('dense color=primary')


def _json_with_form(ref: FileRef, ctx: _Ctx, parsed: dict, pretty: str,
                    fields: list[FormField], on_saved: Callable[[], Any], *,
                    form_default: bool) -> None:
    """Form + Raw tabs; *form_default* selects which is shown first. No live sync
    between the tabs — each renders from the on-disk content read by the caller."""
    with ui.tabs().classes('w-full') as tabs:
        form_tab = ui.tab('Form')
        raw_tab = ui.tab('Raw')
    with ui.tab_panels(tabs, value=(form_tab if form_default else raw_tab)).classes('w-full'):
        with ui.tab_panel(form_tab):
            _json_form(ref, ctx, parsed, fields, on_saved)
        with ui.tab_panel(raw_tab):
            _json_raw_editor(ref, ctx, pretty, on_saved)


def _editor_view(ref: FileRef, ctx: _Ctx,
                 body: Callable[[FileRef, Callable[[], Any]], None]) -> None:
    """Render *body* inside a local refreshable that re-resolves the file first.

    Both editors need this: a copy-on-write save turns an inherited file into the
    device's own, and the view — banner and save-button label included — has to
    follow without navigating away from the detail page.
    """
    @ui.refreshable
    def detail() -> None:
        cur = resolve_ref(ref.key, ref.save_path.parent, ctx.underlay_dir)
        if cur.inherited:
            _inherited_banner(ctx)
        body(cur, detail.refresh)

    detail()


def _render_json_detail(ref: FileRef, ctx: _Ctx) -> None:
    """JSON detail. With an approved sibling schema the schema-driven form is the
    default tab; without one, a flat object still gets an inferred Form tab (raw
    default). An unapproved uploaded schema shows an approval banner and raw only."""

    def body(cur: FileRef, refresh: Callable[[], Any]) -> None:
        path = cur.read_path
        try:
            parsed = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except (OSError, json.JSONDecodeError):
            content = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '{}'
            _json_raw_editor(cur, ctx, content, refresh)
            return
        if not isinstance(parsed, dict):
            _json_raw_editor(cur, ctx, pretty, refresh)
            return

        schema_path = resolve_schema_path(path, ctx.underlay_dir)
        if schema_path is not None:
            if not is_schema_approved(schema_path, ctx.project_name):
                _schema_pending_banner(schema_path, ctx, on_approve=refresh)
                _json_raw_editor(cur, ctx, pretty, refresh)
                return
            schema = load_schema(schema_path)
            schema_fields = fields_from_schema(schema, parsed) if schema is not None else None
            if schema_fields is not None:
                _json_with_form(cur, ctx, parsed, pretty, schema_fields, refresh,
                                form_default=True)
                return
            ui.label('Schema present but not a usable flat-object schema; editing raw.') \
                .classes('text-caption text-grey-7')

        inferred = infer_flat_fields(parsed)
        if inferred is None:
            _json_raw_editor(cur, ctx, pretty, refresh)
            return
        _json_with_form(cur, ctx, parsed, pretty, inferred, refresh, form_default=False)

    _editor_view(ref, ctx, body)


def _render_text_editor(ref: FileRef, ctx: _Ctx) -> None:
    """Plain-text detail. Text is saved verbatim (no reformatting, unlike JSON)."""

    def body(cur: FileRef, refresh: Callable[[], Any]) -> None:
        try:
            content = cur.read_path.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            ui.notify(f'Cannot read file: {exc}', type='negative')
            return
        editor = (
            ui.codemirror(value=content, line_wrapping=True,
                          language=_LANG_MAP.get(cur.read_path.suffix.lower()))
            .classes('w-full border rounded').style('height: clamp(240px, 55vh, 640px)')
        )
        _save_button(cur, lambda: _commit(cur, ctx, editor.value, refresh))

    _editor_view(ref, ctx, body)


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
                  on_click=lambda: _download_file(path)).props('outline')


def _file_detail(ref: FileRef, ctx: _Ctx) -> None:
    """render_detail body for one file, dispatched on type and size."""
    path = ref.read_path
    if not path.is_file():
        ui.label(f'{ref.key!r} not found.').classes('text-negative')
        return
    ext = path.suffix.lower()
    # The editors re-resolve and draw their own banner, because a save can turn an
    # inherited file into the device's own one. The static views below cannot.
    if ext == '.json':
        _render_json_detail(ref, ctx)
        return
    size = path.stat().st_size
    if ext in _TEXT_EXTENSIONS and size <= _MAX_VIEWER_SIZE:
        _render_text_editor(ref, ctx)
        return

    if ref.inherited:
        _inherited_banner(ctx)
    if ext in _IMAGE_MIME:
        if size <= _MAX_IMAGE_SIZE:
            _render_image_preview(path)
        else:
            _render_download_only(path, f'Image too large to preview ({_human_size(size)}).')
    elif ext in _TEXT_EXTENSIONS:
        _render_download_only(path, f'File too large to edit ({_human_size(size)}).')
    else:
        _render_download_only(path, 'Binary file — download to view.')


# ---------------------------------------------------------------------------
# List view (render_list_item) — one row
# ---------------------------------------------------------------------------

def _file_list_row(ref: FileRef, item: FileEntry, select: Callable[[], None],
                   ctx: _Ctx, refresh: Callable[[], Any], state: dict) -> None:
    path = ref.read_path
    # State is keyed by basename per device, so inherited files are covered too.
    published_at = state.get(ref.key, {}).get('published_at') if ctx.mqtt_enabled else None

    with ui.row().classes('w-full items-center gap-0 q-py-xs'):
        ui.icon(_FILE_ICONS.get(path.suffix.lower(), 'insert_drive_file')) \
            .classes('text-grey-7 text-sm q-mr-sm')
        with ui.column().classes('grow gap-0 cursor-pointer').on('click', select):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.label(ref.key).classes('text-body2')
                if ref.inherited:
                    ui.chip('project', icon='folder_shared') \
                        .props('dense outline size=sm color=grey-7') \
                        .tooltip('Served from the project directory — this device has no own copy')
            ui.label(f'{render_datetime(item.mtime)}, {_human_size(item.size)}') \
                .classes('text-caption text-grey-7')
            if published_at:
                try:
                    ui.label(f'published {render_datetime(datetime.fromisoformat(published_at))}') \
                        .classes('text-caption text-grey-7')
                except (ValueError, TypeError):
                    pass
        ui.button(icon='download').props('flat dense size=sm').tooltip('Download') \
            .on_click(lambda _, p=path: _download_file(p))

        if ctx.can_publish:
            # Inherited files are publishable too — the watcher sends them to the
            # device anyway, so this only forces what would happen on its own.
            async def _publish(p=path) -> None:
                from app.core.file.backend import publish_file_now
                ok = await publish_file_now(ctx.project_name, ctx.device_name, p)
                if ok:
                    ui.notify(f'Published {p.name} to device via MQTT', type='positive')
                    refresh()
                else:
                    ui.notify('MQTT publish failed (not connected?)', type='warning')
            ui.button(icon='cloud_upload').props('flat dense size=sm') \
                .tooltip('Force publish to device via MQTT').on_click(_publish)

        # No delete for inherited files: there is no device copy to remove, and the
        # project file belongs to every other device as well.
        if not ref.inherited:
            question = (f'Delete this device\'s copy of **{ref.key}**? '
                        'The project file will be used again.'
                        if ref.overrides
                        else f'Delete **{ref.key}**? This is irreversible.')

            async def _delete(p=path, q=question) -> None:
                if not await confirm_dialog('Delete File', q,
                                            ok_label='Delete', ok_color='negative'):
                    return
                try:
                    p.unlink()
                    ui.notify(f'Deleted {p.name}', type='positive')
                    refresh()
                except OSError as e:
                    ui.notify(f'Delete failed: {e}', type='negative')
            ui.button(icon='delete').props('flat dense size=sm color=negative') \
                .tooltip('Delete').on_click(_delete)


# ---------------------------------------------------------------------------
# New file / upload
# ---------------------------------------------------------------------------

async def _new_json_dialog(directory: Path, refresh: Callable[[], Any], ctx: _Ctx) -> None:
    """Create a new JSON file using a CodeMirror editor."""
    with ui.dialog() as dialog, ui.card().style('width: min(95vw, 900px); overflow: hidden'):
        ui.label('New JSON File').classes('text-subtitle1 font-bold')
        ui.separator()
        with ui.row().classes('w-full items-center gap-2 q-mt-xs'):
            filename_input = ui.input(label='Filename', placeholder='config') \
                .props('outlined dense').classes('grow')
            filename_preview = ui.label('').classes('text-caption text-grey-7 text-no-wrap')

        def _update_preview(e) -> None:
            raw = (e.value or '').strip()
            effective = raw if raw.endswith('.json') else (f'{raw}.json' if raw else '')
            if effective and ctx.underlay_dir is not None and (ctx.underlay_dir / effective).is_file():
                # Allowed, but say so: this hides the project file for this device.
                filename_preview.text = f'→ {effective} (overrides the project file)'
            else:
                filename_preview.text = f'→ {effective}' if effective else ''

        filename_input.on_value_change(_update_preview)
        editor = ui.codemirror(value='{}', language='JSON', line_wrapping=True) \
            .classes('w-full border rounded q-mt-xs').style('height: clamp(160px, 30vh, 400px)')

        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            def _create() -> None:
                raw = (filename_input.value or '').strip()
                fname = raw if raw.endswith('.json') else f'{raw}.json'
                if not fname or fname == '.json':
                    ui.notify('Please enter a filename', type='warning')
                    return
                if not is_valid_upload_filename(fname):
                    ui.notify(f'Invalid filename: {fname!r}', type='negative')
                    return
                try:
                    parsed = json.loads(editor.value)
                except json.JSONDecodeError as exc:
                    ui.notify(f'Invalid JSON: {exc}', type='negative')
                    return
                dest = directory / fname
                if dest.exists():
                    ui.notify(f'{fname} already exists — open it to edit', type='warning')
                    return
                if _save_text(dest, json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'):
                    ui.notify(f'Created {fname}', type='positive')
                    dialog.close()
                    refresh()
                    _maybe_publish(dest, ctx)

            ui.button('Create', on_click=_create).props('color=primary')

    dialog.open()
    await dialog


def _make_upload_handler(directory: Path, refresh: Callable[[], Any], ctx: _Ctx):
    """Return an upload handler that writes uploaded files to *directory* atomically.

    An upload can be several MB, so the blocking write/rename is pushed to a
    worker thread — the same treatment as the device-facing PUT /api/file path."""
    async def _handle(e) -> None:
        # NiceGUI 3.x: the upload event carries a FileUpload (e.file) whose read()
        # is async; the earlier e.name / e.content.read() no longer exist.
        filename = e.file.name
        if not is_valid_upload_filename(filename):
            ui.notify(f'Invalid filename: {filename!r}', type='negative')
            e.sender.reset()
            return
        dest = directory / filename
        content = await e.file.read()
        try:
            await anyio.to_thread.run_sync(lambda: atomic_write(dest, content))
            ui.notify(f'Uploaded {filename}', type='positive')
            refresh()
            _maybe_publish(dest, ctx)
        except OSError as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
        finally:
            e.sender.reset()
    return _handle


# ---------------------------------------------------------------------------
# Card = DrillDownWrapper(list <-> detail) + an always-visible upload footer
# ---------------------------------------------------------------------------

def _files_card(write_dir: Path, *, title: str, description: str, ctx: _Ctx) -> None:
    """One Files card. Everything is written to *write_dir*; ctx.underlay_dir adds
    a read-only layer beneath it (the project dir, for a device card), which also
    serves as the fallback directory for schema sidecars."""
    from app.core.file.backend import get_file_config
    write_dir.mkdir(parents=True, exist_ok=True)
    max_upload = get_file_config(ctx.project_name).max_upload_size

    @ui.refreshable
    def wrapper_body() -> None:
        state: dict = {}
        if ctx.mqtt_enabled and ctx.device_name:
            from app.core.file.backend import load_file_state
            state = load_file_state(ctx.project_name, ctx.device_name)
        adapter = OverlayDirectoryAdapter(write_dir, ctx.underlay_dir, suffix=None,
                                          name_filter=is_valid_upload_filename)

        def _list_item(key: str, item: FileEntry, select: Callable[[], None]) -> None:
            _file_list_row(resolve_ref(key, write_dir, ctx.underlay_dir), item, select,
                           ctx, wrapper_body.refresh, state)

        DrillDownWrapper.from_adapter(
            FileEntry, adapter,
            list_title=title,
            item_title_field='name',
            add_button=None, delete_button=None,  # our own row/footer actions instead
            render_list_item=_list_item,
            render_detail=lambda _a, key, _set: _file_detail(
                resolve_ref(key, write_dir, ctx.underlay_dir), ctx),
        ).render()

    ui.markdown(description).classes('text-caption q-ma-none')
    wrapper_body()

    # Upload footer lives outside the wrapper so it is reachable even when the
    # directory is empty (DrillDownWrapper skips render_list_container then).
    # Uploads and new files always land in write_dir, never in the underlay.
    ui.separator().classes('q-mt-sm')
    with ui.row().classes('w-full items-center gap-2 q-mt-xs flex-wrap'):
        ui.label('Upload').classes('text-caption text-grey-7')

        async def _new_json() -> None:
            await _new_json_dialog(write_dir, wrapper_body.refresh, ctx)
        ui.button('New JSON', icon='add', on_click=_new_json).props('dense flat size=sm')

    ui.upload(
        on_upload=_make_upload_handler(write_dir, wrapper_body.refresh, ctx),
        max_file_size=max_upload,
        auto_upload=True,
    ).props('flat dense').classes('w-full q-mt-xs')


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

_DEVICE_DESC = ('Every file this device is served — its own plus the project files '
                'it inherits, marked with a `project` chip. Editing an inherited file '
                'saves a copy for this device; the project file stays unchanged.')
_PROJECT_DESC = ('Shared files in the project directory. '
                 'Served to devices as a fallback when no device-specific copy exists.')


async def device_files_panel(project_name: str, device_name: str) -> None:
    """Content of the device Files tab: the device's effective file set — its own
    files layered over the project's, exactly as the API and the MQTT publisher
    resolve them."""
    from app.core.project.backend import get_project
    try:
        mqtt_enabled = get_project(project_name, check_active=False).is_mqtt_enabled
    except Exception:
        mqtt_enabled = False
    _files_card(get_device_path(project_name, device_name),
                title='Files', description=_DEVICE_DESC,
                ctx=_Ctx(project_name, device_name, mqtt_enabled,
                         underlay_dir=get_project_dir(project_name)))


async def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab — the project directory on its own, with
    no underlay, so no file is ever inherited here."""
    _files_card(get_project_dir(project_name),
                title='Project Files', description=_PROJECT_DESC,
                ctx=_Ctx(project_name, None, False))
