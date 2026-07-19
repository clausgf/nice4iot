"""
MQTT integration backend.

Manages a single persistent MQTT connection shared across all projects.
Routes incoming messages to telemetry, log, and upload handlers.
Exposes publish_file() for server-to-device file delivery.

Circular-import avoidance: this module must NOT import from
app.core.file.backend. The file state callback is registered externally
via register_file_publish_callback().
"""
import asyncio
import datetime
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import anyio
import aiomqtt

from app.config import app_config
from app.exceptions import NotFoundError
from app.mqtt.models import MqttGlobalConfig
from app.util import logger, is_valid_filename, is_valid_upload_filename

from niceview.dataadapter import JsonAdapter

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

connection_status: str = "disconnected"
_client: aiomqtt.Client | None = None

_file_publish_callback: Callable | None = None

# Extensions (see docs/extensions.md): (extension_name, suffix, handler, qos).
# Actual topic is ext/<extension_name>/<project>/<suffix> — see
# register_topic_handler() and _extension_topic_pattern() below.
_extension_topic_handlers: list[tuple[str, str, Callable[[str, str, bytes], Awaitable[None]], int]] = []


def register_file_publish_callback(callback: Callable) -> None:
    """Register a callback invoked when a device uploads a file via MQTT.

    The callback is NOT currently called (uploads go device → server, no
    re-publish needed). The hook is reserved for future state-tracking use.
    """
    global _file_publish_callback
    _file_publish_callback = callback


def register_topic_handler(suffix: str, handler: Callable[[str, str, bytes], Awaitable[None]],
                            qos: int = 0) -> None:
    """Register an extension handler for messages under ext/<extension_name>/<project>/<suffix>.

    The extension_name is taken from the current app.extensions.registering()
    context. suffix may use MQTT wildcards ('+' one level, '#' the rest) for
    its own sub-hierarchy. handler(project_name, topic, payload) is awaited
    for every matching message, but only when the extension is enabled for
    that project — nice4iot checks this centrally, the handler never has to.
    qos is the MQTT subscription QoS (0, 1, or 2) used for this topic filter.

    Invalid suffix/qos values raise ValueError here, at registration time —
    they would otherwise only surface (or silently misbehave) at broker
    subscribe time, long after the extension author's mistake.
    """
    from app.extensions import _extension_name
    if not suffix or suffix.startswith('/'):
        raise ValueError(f"invalid topic suffix {suffix!r} (must be non-empty and not start with '/')")
    if qos not in (0, 1, 2):
        raise ValueError(f"invalid qos {qos!r} (must be 0, 1, or 2)")
    _extension_topic_handlers.append((_extension_name(), suffix, handler, qos))


def _extension_topic_pattern(extension_name: str, suffix: str) -> re.Pattern:
    """Compile ext/<extension_name>/<project>/<suffix> into a regex with a 'project' group."""
    suffix_pattern = re.escape(suffix).replace(r'\+', '[^/]+').replace(r'\#', '.*')
    return re.compile(rf'^ext/{re.escape(extension_name)}/(?P<project>[^/]+)/{suffix_pattern}$')


async def _dispatch_extension_topic(topic: str, payload: bytes) -> bool:
    """Try registered extension handlers for *topic*.

    Returns True if any handler's pattern matched (regardless of whether
    the extension was enabled for that project), so callers can tell "no
    extension claims this topic" apart from "claimed but disabled".
    """
    from app.extensions import is_extension_enabled

    matched = False
    for extension_name, suffix, handler, _qos in _extension_topic_handlers:
        m = _extension_topic_pattern(extension_name, suffix).match(topic)
        if not m:
            continue
        matched = True
        project_name = m.group('project')
        enabled = await anyio.to_thread.run_sync(
            lambda: is_extension_enabled(project_name, extension_name)
        )
        if not enabled:
            continue
        try:
            await handler(project_name, topic, payload)
        except Exception as e:
            logger.error(f"MQTT extension handler {extension_name!r}/{suffix!r} "
                         f"failed on {topic!r}: {e}")
    return matched


# ---------------------------------------------------------------------------
# Config adapter
# ---------------------------------------------------------------------------

def get_mqtt_adapter() -> JsonAdapter:
    """Return a JsonAdapter for the global MQTT broker configuration."""
    config_path = Path(app_config.projects_dir).resolve().parent / '.mqtt.json'
    return JsonAdapter(MqttGlobalConfig, config_path,
                              create_if_not_exist=True, lock_field='updated_at')


# ---------------------------------------------------------------------------
# Topic helpers
# ---------------------------------------------------------------------------

def _subscription_prefix(topic_base: str, project_name: str) -> str:
    """Return the MQTT subscription prefix for a project.

    Replaces {project} with the project name and {device} with the MQTT
    single-level wildcard '+'. Strips leading slash.
    """
    result = topic_base.replace('{project}', project_name).replace('{device}', '+')
    while '//' in result:
        result = result.replace('//', '/')
    return result.lstrip('/')


def build_topic(topic_base: str, project_name: str, device_name: str, suffix: str) -> str:
    """Build a full MQTT topic by substituting project/device placeholders.

    Normalises double slashes and strips any leading slash (bare MQTT topics).
    """
    topic = topic_base.replace('{project}', project_name).replace('{device}', device_name)
    topic = f"{topic}/{suffix}"
    while '//' in topic:
        topic = topic.replace('//', '/')
    return topic.lstrip('/')


def _route_topic(topic: str) -> dict | None:
    """Match an incoming MQTT topic against all MQTT-enabled projects.

    Returns a dict with keys: project, device, type, and (for telemetry)
    kind or (for upload) filename. Returns None if no project matches.
    """
    from app.core.project.backend import get_projects

    for project in get_projects():
        if not project.is_mqtt_enabled:
            continue
        topic_base = project.mqtt_topic_base.lstrip('/')
        if '{device}' not in topic_base:
            logger.warning(f"Project {project.name!r}: mqtt_topic_base has no {{device}} "
                           f"placeholder — cannot route incoming messages, skipping")
            continue
        # Build a regex with named capture groups so group count is always known.
        pattern = re.escape(topic_base)
        pattern = pattern.replace(r'\{project\}', re.escape(project.name))
        pattern = pattern.replace(r'\{device\}', r'(?P<device>[^/]+)')
        full_pattern = rf'^{pattern}/(?P<suffix>.+)$'
        m = re.match(full_pattern, topic)
        if not m:
            continue
        device_name = m.group('device')
        suffix = m.group('suffix')
        if suffix == 'log':
            return {'project': project.name, 'device': device_name, 'type': 'log'}
        if suffix.startswith('telemetry/'):
            kind = suffix[len('telemetry/'):]
            if kind and is_valid_filename(kind):
                return {'project': project.name, 'device': device_name,
                        'type': 'telemetry', 'kind': kind}
        elif suffix.startswith('upload/'):
            filename = suffix[len('upload/'):]
            if is_valid_upload_filename(filename):
                return {'project': project.name, 'device': device_name,
                        'type': 'upload', 'filename': filename}
    return None


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def _handle_upload(project_name: str, device_name: str, filename: str,
                         payload: bytes) -> None:
    """Save a device-uploaded file to the device directory atomically."""
    from app.core.device.backend import get_device_path
    from app.core.file.backend import get_file_config

    config = await anyio.to_thread.run_sync(lambda: get_file_config(project_name))
    if len(payload) > config.max_upload_size:
        logger.warning(
            f"MQTT upload from {project_name}/{device_name}/{filename} "
            f"too large ({len(payload)} bytes, limit {config.max_upload_size})"
        )
        return

    try:
        device_path = await anyio.to_thread.run_sync(
            lambda: get_device_path(project_name, device_name)
        )
    except Exception as e:
        logger.error(f"MQTT upload: cannot resolve device path for "
                     f"{project_name}/{device_name}: {e}")
        return

    dest = device_path / filename
    tmp = dest.with_name(filename + '.mqtt.tmp')
    try:
        await anyio.to_thread.run_sync(lambda: tmp.write_bytes(payload))
        await anyio.to_thread.run_sync(lambda: tmp.rename(dest))
        logger.debug(f"MQTT upload saved: {dest} ({len(payload)} bytes)")
    except OSError as e:
        await anyio.to_thread.run_sync(lambda: tmp.unlink(missing_ok=True))
        logger.error(f"MQTT upload write failed for {dest}: {e}")


async def _handle_message(topic: str, payload: bytes) -> None:
    """Route an incoming MQTT message to the appropriate handler."""
    from app.core.project.backend import get_project
    from app.core.device.backend import get_device, create_device, write_last_seen
    from app.core.device.models import Device
    from app.core.telemetry.backend import write_telemetry
    from app.core.logging.backend import write_log

    route = await anyio.to_thread.run_sync(lambda: _route_topic(topic))
    if route is None:
        matched = await _dispatch_extension_topic(topic, payload)
        if not matched:
            logger.debug(f"MQTT: no route for topic {topic!r}")
        return

    project_name = route['project']
    device_name = route['device']
    msg_type = route['type']

    # Resolve project (needed for autocreate flag)
    try:
        project = await anyio.to_thread.run_sync(
            lambda: get_project(project_name, check_active=False)
        )
    except Exception as e:
        logger.error(f"MQTT: cannot load project {project_name}: {e}")
        return

    # Auto-create device if configured and not yet present
    device_exists = True
    try:
        await anyio.to_thread.run_sync(lambda: get_device(project_name, device_name))
    except NotFoundError:
        device_exists = False

    if not device_exists:
        if project.is_autocreate_devices:
            try:
                new_device = Device(
                    name=device_name,
                    project_name=project_name,
                    is_provisioning_approved=project.is_provisioning_autoapproval,
                )
                await anyio.to_thread.run_sync(lambda: create_device(new_device))
                logger.info(f"MQTT: auto-created device {project_name}/{device_name}")
            except Exception as e:
                logger.error(f"MQTT: failed to auto-create device "
                             f"{project_name}/{device_name}: {e}")
                return
        else:
            logger.debug(f"MQTT: device {project_name}/{device_name} not found "
                         f"and autocreate disabled")
            return

    # Dispatch by message type
    try:
        if msg_type == 'telemetry':
            kind = route['kind']
            try:
                values = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"MQTT telemetry: invalid JSON from "
                               f"{project_name}/{device_name}: {e}")
                return
            await write_telemetry(project_name, device_name, values=values, kind=kind)

        elif msg_type == 'log':
            try:
                logmsg = payload.decode('utf-8', errors='replace')
            except Exception:
                logmsg = repr(payload)
            await write_log(project_name, device_name, logmsg)

        elif msg_type == 'upload':
            filename = route['filename']
            await _handle_upload(project_name, device_name, filename, payload)

    except Exception as e:
        logger.exception(f"MQTT: error handling {msg_type} message from "
                         f"{project_name}/{device_name}: {e}")
        return

    # Update last_seen after successful message handling
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        await anyio.to_thread.run_sync(
            lambda: write_last_seen(project_name, device_name, now)
        )
    except Exception as e:
        logger.error(f"MQTT: failed to write last_seen for "
                     f"{project_name}/{device_name}: {e}")


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

async def publish_file(project_name: str, device_name: str, topic_base: str,
                       filename: str, content: bytes, qos: int,
                       retain: bool) -> bool:
    """Publish a file to a device via MQTT.

    Returns False if the client is not connected or on error.
    """
    global _client
    if _client is None:
        logger.debug(f"MQTT publish_file: not connected, skipping {filename}")
        return False
    topic = build_topic(topic_base, project_name, device_name, f'download/{filename}')
    try:
        await _client.publish(topic, payload=content, qos=qos, retain=retain)
        logger.debug(f"MQTT published {filename} to {topic} "
                     f"({len(content)} bytes, qos={qos}, retain={retain})")
        return True
    except Exception as e:
        logger.error(f"MQTT publish_file failed for {topic}: {e}")
        return False


async def mqtt_publish(topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
    """Publish an arbitrary message for extensions (see docs/extensions.md).

    Logs a warning and drops the message if there is no active connection,
    same behavior as publish_file().
    """
    if _client is None:
        logger.warning(f"mqtt_publish: no active MQTT connection, dropping message for {topic!r}")
        return
    try:
        await _client.publish(topic, payload=payload, qos=qos, retain=retain)
    except Exception as e:
        logger.error(f"mqtt_publish failed for {topic}: {e}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def mqtt_main_loop() -> None:
    """Persistent MQTT client loop with automatic reconnection.

    Connects using the global config, subscribes to all MQTT-enabled project
    topics, and dispatches incoming messages via asyncio tasks.
    Retries with a 5-second delay on any error.
    """
    global connection_status, _client

    while True:
        try:
            config = await anyio.to_thread.run_sync(lambda: get_mqtt_adapter().read())

            if not config.is_enabled:
                if connection_status != "disabled":
                    _client = None
                    connection_status = "disabled"
                    logger.info("MQTT broker disabled — connection suspended")
                await asyncio.sleep(30)
                continue

            connect_kwargs: dict = {
                'hostname': config.server,
                'port': config.port,
                'identifier': config.client_id,
            }
            if config.username:
                connect_kwargs['username'] = config.username
            if config.password:
                connect_kwargs['password'] = config.password

            async with aiomqtt.Client(**connect_kwargs) as client:
                _client = client
                connection_status = "connected"
                logger.info(f"MQTT connected to {config.server}:{config.port}")

                # Subscribe to all MQTT-enabled projects.
                # Use specific topic patterns rather than # to avoid receiving
                # our own retained download messages back from the broker.
                from app.core.project.backend import get_projects
                projects = await anyio.to_thread.run_sync(get_projects)
                for project in projects:
                    if not project.is_mqtt_enabled:
                        continue
                    prefix = _subscription_prefix(project.mqtt_topic_base, project.name)
                    for suffix in ('telemetry/+', 'log', 'upload/+'):
                        sub_topic = f"{prefix}/{suffix}"
                        await client.subscribe(sub_topic)
                        logger.info(f"MQTT subscribed to {sub_topic} [{project.name!r}]")

                # Subscribe to extension-registered topics (docs/extensions.md):
                # ext/<extension_name>/<project>/<suffix>, project wildcarded.
                for extension_name, suffix, _, qos in _extension_topic_handlers:
                    sub_topic = f"ext/{extension_name}/+/{suffix}"
                    await client.subscribe(sub_topic, qos=qos)
                    logger.info(f"MQTT subscribed to {sub_topic!r} [extension {extension_name!r}] (qos={qos})")

                # Process incoming messages
                async for message in client.messages:
                    topic_str = str(message.topic)
                    payload = bytes(message.payload)
                    asyncio.create_task(_handle_message(topic_str, payload))

            # Clean disconnect: broker closed the connection without raising.
            _client = None
            connection_status = "disconnected"
            logger.info("MQTT broker disconnected cleanly, reconnecting in 5 s")

        except aiomqtt.MqttError as e:
            _client = None
            connection_status = f"error: {e}"
            logger.warning(f"MQTT connection error: {e} — retrying in 5 s")
        except Exception as e:
            _client = None
            connection_status = f"error: {e}"
            logger.exception(f"MQTT unexpected error: {e} — retrying in 5 s")

        await asyncio.sleep(5)
