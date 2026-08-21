"""
Device / Project Files — browse, upload, download, delete, view and edit files.

Device files:  <projects_dir>/<project>/<device>/<filename>  (full read/write)
Project files: <projects_dir>/<project>/<filename>           (full read/write;
               served to devices as a fallback when no device-specific copy exists)

The device tab shows both in **one** list: the device's own files layered over the
project's, with inherited entries marked by a chip. Writes never reach the
underlay — saving an inherited file copies it to the device. The merge and the
per-entry resolution live in `overlay.py`.

Built on niceview's DrillDownWrapper over an OverlayDirectoryAdapter in all-files
mode (mixed extensions, keyed by full filename): this module is the list half —
rows, upload, new file — and `detail_ui.py` is the detail half.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anyio
from nicegui import ui
from niceview import ChromeText, DrillDownActionEventArguments, DrillDownWrapper, FormAction
from niceview.style import (
    chrome_button, chrome_dialog, chrome_dialog_buttons, chrome_dialog_title, get_chrome_style,
)
from niceview.text import get_chrome_text, text_of

from app.core.device.backend import get_device_path
from app.core.file.backend import get_file_config, load_file_state, publish_file_now
from app.core.file.detail_ui import (
    FILE_ICONS,
    download_file,
    file_detail,
    maybe_publish,
    save_text,
)
from app.core.file.overlay import FileCtx, OverlayDirectoryAdapter, OverlayFileEntry
from app.paths import project_dir as get_project_dir
from app.util import atomic_write, human_size, is_valid_upload_filename, render_datetime

log = logging.getLogger('uvicorn')


# ---------------------------------------------------------------------------
# List view (render_list_item) — one row
# ---------------------------------------------------------------------------

def _file_list_row(entry: OverlayFileEntry, select: Callable[[], None], ctx: FileCtx,
                   state: dict) -> None:
    """One list row: what identifies a file, not what can be done to it.

    Download, publish and delete are the wrapper's `chrome_actions` and live in the
    detail view's title row (see `_file_actions`) — a row that carries no buttons of
    its own can be clickable as a whole. What stays is what the generic ModelList
    rows could not show: the type icon, the `project` chip, and the publish stamp
    (which comes from `state`, not from the entry).
    """
    path = entry.read_path
    # State is keyed by basename per device, so inherited files are covered too.
    published_at = state.get(entry.name, {}).get('published_at') if ctx.mqtt_enabled else None

    with ui.row().classes('w-full items-center gap-0 q-py-xs cursor-pointer').on('click', select):
        ui.icon(FILE_ICONS.get(path.suffix.lower(), 'insert_drive_file')) \
            .classes('text-grey-7 text-sm q-mr-sm')
        with ui.column().classes('grow gap-0'):
            with ui.row().classes('items-center gap-2 no-wrap'):
                ui.label(entry.name).classes('text-body2')
                if entry.inherited:
                    ui.chip('project', icon='folder_shared') \
                        .props('dense outline size=sm color=grey-7') \
                        .tooltip('Served from the project directory — this device has no own copy')
            ui.label(f'{render_datetime(entry.mtime)}, {human_size(entry.size)}') \
                .classes('text-caption text-grey-7')
            if published_at:
                try:
                    ui.label(f'published {render_datetime(datetime.fromisoformat(published_at))}') \
                        .classes('text-caption text-grey-7')
                except (ValueError, TypeError):
                    pass


# ---------------------------------------------------------------------------
# New file / upload
# ---------------------------------------------------------------------------

def _as_json_name(raw: str) -> str:
    """'config' and 'config.json' both mean config.json."""
    name = (raw or '').strip()
    return name if name.endswith('.json') else f'{name}.json'


def _make_upload_handler(directory: Path, on_success: Callable[[], Any], ctx: FileCtx):
    """Return an upload handler that writes uploaded files to *directory* atomically.

    An upload can be several MB, so the blocking write/rename is pushed to a
    worker thread — the same treatment as the device-facing PUT /api/file path.

    *on_success* is called after a file landed. It deliberately does not refresh
    the list itself: the handler runs inside the Add dialog, which hangs in the
    same refreshable subtree as the list, so refreshing here would delete the
    dialog out from under the user mid-upload. The caller refreshes once the
    dialog is closed."""
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
            on_success()
            maybe_publish(dest, ctx)
        except OSError as exc:
            log.exception(f'Upload failed: {exc}')
            ui.notify(f'Upload failed: {exc}', type='negative')
        finally:
            e.sender.reset()
    return _handle


async def _add_file_dialog(write_dir: Path, *, ctx: FileCtx, max_upload: int) -> tuple[str | None, bool]:
    """The wrapper's Add action: one dialog for both ways to get a file in here.

    Returns `(created, uploaded)` — the name of a newly created empty file to
    drill into, and whether an upload changed the directory. Neither is acted on
    here: the caller owns the refresh, because this dialog is built in the click
    context of the wrapper's title row and therefore lives inside the refreshable
    body it would be refreshing (see `_make_upload_handler`).

    Upload comes first because it is the common case; the name field is the
    second way in. The dialog stays open after an upload so several files can be
    dropped in one go.
    """
    uploaded = False

    def _mark_uploaded() -> None:
        nonlocal uploaded
        uploaded = True

    def _taken(raw: str) -> bool:
        """A name already used in write_dir. Shadowing an underlay file is fine."""
        return (write_dir / _as_json_name(raw)).exists()

    style = get_chrome_style()
    with chrome_dialog(style) as dialog:
        chrome_dialog_title('Add File', style)
        ui.upload(
            on_upload=_make_upload_handler(write_dir, _mark_uploaded, ctx),
            max_file_size=max_upload,
            auto_upload=True,
        ).props('flat bordered label="Drop files here, or pick one"').classes('w-full')
        ui.label(f'Up to {human_size(max_upload)} per file. Several files can be dropped in a row.') \
            .classes('text-caption text-grey-7')

        ui.separator().classes('q-my-sm')
        with ui.row().classes('w-full items-start gap-2 no-wrap'):
            name = ui.input(
                label='New JSON file', placeholder='config',
                validation={
                    'Letters, digits, _ - . only, starting with a letter or digit':
                        lambda s: is_valid_upload_filename(_as_json_name(s)),
                    'Already exists — close this and open it to edit': lambda s: not _taken(s),
                },
            ).props('outlined dense').classes('grow')

            def _create() -> None:
                if not name.validate():
                    return
                dialog.submit(_as_json_name(name.value))
            chrome_button('add', text_of(get_chrome_text().create_label), 'add', '', style,
                          _create, place='dialog')

        with chrome_dialog_buttons(style):
            chrome_button('cancel', 'Done', None, '', style,
                          lambda: dialog.submit(None), place='dialog')

    created = await dialog
    return created, uploaded


# ---------------------------------------------------------------------------
# Detail-view title row: the actions on one file
# ---------------------------------------------------------------------------

def _file_actions(ctx: FileCtx, refresh: Callable[[], Any]) -> dict[str, FormAction]:
    """The wrapper's `chrome_actions` — our own buttons in the detail title row.

    niceview hides them in the list view on its own and hands each handler the item
    on screen, so they need no key of their own. Delete is *not* among them — it is
    niceview's own button, see `_build_wrapper`.

    `requires_valid` is not an option here — the wrapper raises for it, because a
    `render_detail` of ours owns the detail view and there is no form to ask.

    Publish is card-level constant, so it is simply absent where it cannot work.
    """
    def _download(e: DrillDownActionEventArguments) -> None:
        download_file(e.item.read_path)

    # Inherited files are publishable too — the watcher sends them to the device
    # anyway, so this only forces what would happen on its own.
    async def _publish(e: DrillDownActionEventArguments) -> None:
        path = e.item.read_path
        if await publish_file_now(ctx.project_name, ctx.device_name, path):
            ui.notify(f'Published {path.name} to device via MQTT', type='positive')
            refresh()
        else:
            ui.notify('MQTT publish failed (not connected?)', type='warning')

    actions = {'download': FormAction(label='', icon='download', tooltip='Download',
                                      on_click=_download)}
    if ctx.can_publish:
        actions['publish'] = FormAction(label='', icon='cloud_upload',
                                        tooltip='Force publish to device via MQTT',
                                        on_click=_publish)
    return actions


def _delete_texts(current: Callable[[], OverlayFileEntry | None]) -> ChromeText:
    """niceview's delete texts, worded for a file — and for *which* file.

    A ChromeText slot takes a callable, resolved when the text is rendered, which
    for the confirmation is the moment the button is clicked. So the one thing
    that kept Delete out of niceview's own button — that our question differs per
    entry — is expressible after all: dropping a device copy so the project file
    applies again is not the irreversible delete of a plain file, and the dialog
    renders the message as markdown either way.

    *current* reports the entry on screen; `_build_wrapper`'s render_detail keeps
    it up to date, so this needs none of the wrapper's internals.
    """
    def _message() -> str:
        entry = current()
        if entry is None:
            return 'Delete this file?'
        if entry.overrides:
            return (f'Delete this device\'s copy of **{entry.name}**? '
                    'The project file will be used again.')
        return f'Delete **{entry.name}**? This is irreversible.'

    def _deleted() -> str:
        entry = current()
        return f'Deleted {entry.name}' if entry is not None else 'File deleted'

    return ChromeText.derived(delete_item_title='Delete File',
                              delete_item_tooltip='Delete',
                              delete_item_message=_message,
                              item_deleted=_deleted,
                              delete_failed='Delete failed: {error}')


# ---------------------------------------------------------------------------
# Card = DrillDownWrapper(list <-> detail), Add via the wrapper's own button
# ---------------------------------------------------------------------------

def _build_wrapper(adapter: OverlayDirectoryAdapter, *, title: str, ctx: FileCtx,
                   refresh: Callable[[], Any], state: dict, description: str = '',
                   on_add: Callable[[], Any] | None = None) -> DrillDownWrapper:
    """The list <-> detail wrapper for one card.

    Extracted from `_files_card` so a test can drive the navigation niceview owns:
    rendering a panel only ever reaches the list view, and a mismatch in what we
    hand the wrapper used to surface in the browser rather than in CI.

    Add is the wrapper's own title-row button driving `on_add` (niceview 0.15.0+
    awaits an async handler, so it can open a dialog and act on the answer).

    Delete is niceview's own button, not one of our actions. It routes through
    `DirectoryAdapter.delete()`, which only ever touches the card's own directory
    — exactly the device copy we mean — and notifies its change listeners, so the
    list refreshes itself and the wrapper navigates back on its own. It also picks
    up the `delete` chrome role, instead of an action of ours spelling out
    `color=negative` and going around the cascade that exists to hold it.
    The per-entry wording it used to cost us is `_delete_texts` above.

    Its button is hidden for an inherited entry, which has no device copy to
    remove (deleting one would raise KeyError in the adapter — the button is not
    merely pointless there, it cannot work). That works because niceview updates
    the title row *before* it refreshes the body on every navigation (`open`,
    `_back`, `_set_detail_key`, `render`), so a visibility set from render_detail
    is the last word and holds until the next navigation decides it again.
    """
    wrapper: DrillDownWrapper | None = None
    shown: OverlayFileEntry | None = None

    def _render_detail(a: OverlayDirectoryAdapter, key: str, _set: Callable[[str], None]) -> None:
        nonlocal shown
        try:
            shown = a.read(key)
        except (KeyError, ValueError):
            shown = None
        if wrapper is not None and wrapper.delete_button is not None:
            wrapper.delete_button.set_visibility(shown is not None and not shown.inherited)
        file_detail(a, key, ctx)

    wrapper = DrillDownWrapper.from_adapter(
        OverlayFileEntry, adapter,
        title=title, description=description,
        item_title_field='name',
        chrome_actions=_file_actions(ctx, refresh),
        chrome_text=_delete_texts(lambda: shown),
        on_add=on_add,
        render_list_item=lambda _key, item, select: _file_list_row(
            item, select, ctx, state),
        render_detail=_render_detail,
    )
    return wrapper


def _files_card(write_dir: Path, *, title: str, description: str, ctx: FileCtx) -> None:
    """One Files card. Everything is written to *write_dir*; ctx.underlay_dir adds
    a read-only layer beneath it (the project dir, for a device card), which also
    serves as the fallback directory for schema sidecars."""
    write_dir.mkdir(parents=True, exist_ok=True)
    max_upload = get_file_config(ctx.project_name).max_upload_size
    wrapper: DrillDownWrapper | None = None

    @ui.refreshable
    def wrapper_body() -> None:
        nonlocal wrapper
        state: dict = {}
        if ctx.mqtt_enabled and ctx.device_name:
            state = load_file_state(ctx.project_name, ctx.device_name)
        adapter = OverlayDirectoryAdapter(write_dir, ctx.underlay_dir, suffix=None,
                                          name_filter=is_valid_upload_filename)
        wrapper = _build_wrapper(adapter, title=title, ctx=ctx, refresh=wrapper_body.refresh,
                                 state=state, description=description, on_add=_add)
        wrapper.render()
        # niceview renders the description unstyled, below the title row; the card
        # wants it as a caption. Exposed elements survive list<->detail navigation.
        if wrapper.description is not None:
            wrapper.description.classes('text-caption q-ma-none')

    async def _add() -> None:
        """Upload or create — then refresh once, with the dialog already gone."""
        created, uploaded = await _add_file_dialog(write_dir, ctx=ctx, max_upload=max_upload)
        if created is not None:
            dest = write_dir / created
            if not save_text(dest, '{}\n'):
                return
            # Creating a device file of a project file's name is allowed, but say so.
            hides = ctx.underlay_dir is not None and (ctx.underlay_dir / created).is_file()
            ui.notify(f'Created {created}' + (' — overrides the project file' if hides else ''),
                      type='positive')
            maybe_publish(dest, ctx)
        elif not uploaded:
            return  # dialog dismissed without changing anything
        wrapper_body.refresh()
        if created is not None and wrapper is not None:
            wrapper.open(created)  # straight into the editor for the new file

    wrapper_body()


# ---------------------------------------------------------------------------
# Public panel functions
# ---------------------------------------------------------------------------

_DEVICE_DESC = ('Every file this device is served — its own plus the project files '
                'it inherits, marked with a `project` chip. Editing an inherited file '
                'saves a copy for this device; the project file stays unchanged. '
                'No auto-save, **do not forget to hit the save button after editing!**')
_PROJECT_DESC = ('Shared files in the project directory. '
                 'Served to devices as a fallback when no device-specific copy exists.'
                'No auto-save, **do not forget to hit the save button after editing!**')


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
                ctx=FileCtx(project_name, device_name, mqtt_enabled,
                            underlay_dir=get_project_dir(project_name)))


async def project_files_panel(project_name: str) -> None:
    """Content of the project Files tab — the project directory on its own, with
    no underlay, so no file is ever inherited here."""
    _files_card(get_project_dir(project_name),
                title='Project Files', description=_PROJECT_DESC,
                ctx=FileCtx(project_name, None, False))
