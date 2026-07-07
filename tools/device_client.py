#!/usr/bin/env python3
"""
device_client.py — Python simulation of an arduino4iot device.

Implements the same HTTP flow as the arduino4iot C++ library:
  1. POST /api/provision          — obtain a device bearer token
  2. GET  /api/file/.../config.json  — config download (ETag caching)
  3. HEAD /api/file/.../firmware.bin — firmware OTA check (ETag caching)
  4. POST /api/telemetry/.../{kind}  — push numeric measurements
  5. POST /api/log/...               — push plain-text log lines
  6. PUT  /api/file/.../{filename}   — upload a file
  7. GET  /api/file/.../{filename}   — download any file

State (device token + ETag cache) is persisted in a JSON file so token
re-use across CLI invocations works exactly like NV-RAM on hardware.

Usage
-----
# Provision then run a full wake-up cycle:
  python tools/device_client.py cycle \\
      --url http://localhost:8000 \\
      --project myproject --device mydevice \\
      --token <provisioning_token>

# Push telemetry only:
  python tools/device_client.py telemetry sensors '{"temperature": 22.4}' \\
      --url http://localhost:8000 --project myproject --device mydevice \\
      --token <provisioning_token>

# Run a long-running loop (simulates periodic wake-ups):
  python tools/device_client.py loop --interval 30 ...

See --help for all options.
"""

import argparse
import json
import logging
import random
import time
from pathlib import Path

import httpx

log = logging.getLogger("device_client")


# ---------------------------------------------------------------------------
# DeviceClient
# ---------------------------------------------------------------------------

class DeviceClient:
    """
    Python simulation of an arduino4iot device.

    State (device token, ETag cache) is persisted in *state_file* so the
    client behaves like hardware with NV-RAM: token is reused across runs
    and only a new provisioning request is sent after a 401 / 403.
    """

    def __init__(
        self,
        base_url: str,
        project_name: str,
        device_name: str,
        provisioning_token: str,
        state_file: str | None = None,
        timeout: float = 10.0,
        verbose: bool = False,
    ):
        self.base_url = base_url.rstrip("/") + "/api"
        self.project_name = project_name
        self.device_name = device_name
        self.provisioning_token = provisioning_token
        self.state_file = Path(state_file or f".{device_name}.state.json")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

        # Persistent state
        self._device_token: str | None = None  # full "Bearer <value>"
        self._etags: dict[str, str] = {}       # resource-key → ETag
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence (mirrors NV-RAM on hardware)
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text())
                self._device_token = data.get("device_token")
                self._etags = data.get("etags", {})
                log.debug("Loaded state from %s", self.state_file)
            except Exception as e:
                log.warning("Could not load state: %s", e)

    def _save_state(self) -> None:
        data = {"device_token": self._device_token, "etags": self._etags}
        self.state_file.write_text(json.dumps(data, indent=2))
        log.debug("Saved state to %s", self.state_file)

    def clear_token(self) -> None:
        """Clear the stored device token (triggered by 401 / 403 response)."""
        log.info("Clearing device token — will re-provision on next cycle")
        self._device_token = None
        self._save_state()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self, override: dict | None = None) -> dict:
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._device_token:
            h["Authorization"] = self._device_token
        if override:
            h.update(override)
        return h

    def _check_auth(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            log.warning("Got %d — clearing device token", response.status_code)
            self.clear_token()

    def _url(self, path: str) -> str:
        return (
            f"{self.base_url}/{path}"
            .replace("{project}", self.project_name)
            .replace("{device}", self.device_name)
        )

    # ------------------------------------------------------------------
    # 1. Provisioning
    # ------------------------------------------------------------------

    def provision(self, force: bool = False) -> bool:
        """
        Obtain a device bearer token via POST /api/provision.

        Skipped (returns False) if a token is already stored, unless *force*
        is True. Returns True if a new token was obtained.
        """
        if self._device_token and not force:
            log.debug("Already provisioned — skipping")
            return False

        url = self._url("provision")
        body = {
            "projectName": self.project_name,
            "deviceName": self.device_name,
            "provisioningToken": self.provisioning_token,
        }
        log.info("POST %s", url)
        resp = self._client.post(url, json=body, headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        log.info("  → %d", resp.status_code)

        if resp.status_code == 200:
            data = resp.json()
            token_type = data.get("tokenType", "bearer")
            access_token = data.get("accessToken", "")
            self._device_token = f"{token_type} {access_token}"
            if "expiresIn" in data:
                log.info("  Token expires in %ds", data["expiresIn"])
            self._save_state()
            return True
        else:
            log.error("Provisioning failed: %d %s", resp.status_code, resp.text[:200])
            return False

    # ------------------------------------------------------------------
    # 2. Config download
    # ------------------------------------------------------------------

    def download_config(self, filename: str = "config.json") -> tuple[dict | None, bool]:
        """
        GET /api/file/{project}/{device}/{filename} with ETag caching.

        Returns (config_dict, was_updated).
        Returns (None, False) on error.
        Returns (None, False) on 304 Not Modified (use your cached copy).
        """
        url = self._url(f"file/{{project}}/{{device}}/{filename}")
        etag_key = f"file:{filename}"
        headers = self._auth_headers()
        if etag_key in self._etags:
            headers["If-None-Match"] = self._etags[etag_key]

        log.info("GET %s", url)
        resp = self._client.get(url, headers=headers)
        log.info("  → %d", resp.status_code)
        self._check_auth(resp)

        if resp.status_code == 304:
            log.info("  Config not modified")
            return None, False
        if resp.status_code == 200:
            if "ETag" in resp.headers:
                self._etags[etag_key] = resp.headers["ETag"]
                self._save_state()
            try:
                return resp.json(), True
            except Exception:
                return None, True
        if resp.status_code == 404:
            log.info("  Config file not found on server")
            return None, False
        log.error("  Config download failed: %d", resp.status_code)
        return None, False

    # ------------------------------------------------------------------
    # 3. Firmware OTA check
    # ------------------------------------------------------------------

    def check_firmware(self, filename: str = "firmware.bin") -> bool:
        """
        HEAD /api/file/{project}/{device}/{filename}.

        Returns True if a new firmware is available (ETag changed).
        Updates the stored ETag on success.
        """
        url = self._url(f"file/{{project}}/{{device}}/{filename}")
        etag_key = f"file:{filename}"
        headers = self._auth_headers()
        if etag_key in self._etags:
            headers["If-None-Match"] = self._etags[etag_key]

        log.info("HEAD %s", url)
        resp = self._client.head(url, headers=headers)
        log.info("  → %d", resp.status_code)
        self._check_auth(resp)

        if resp.status_code == 304:
            log.info("  Firmware up to date")
            return False
        if resp.status_code == 200:
            new_etag = resp.headers.get("ETag", "")
            old_etag = self._etags.get(etag_key, "")
            if new_etag and new_etag != old_etag:
                log.info("  New firmware available! ETag: %s", new_etag)
                self._etags[etag_key] = new_etag
                self._save_state()
                return True
            return False
        if resp.status_code == 404:
            log.info("  No firmware file on server")
            return False
        log.error("  Firmware check failed: %d", resp.status_code)
        return False

    # ------------------------------------------------------------------
    # 4. Telemetry push
    # ------------------------------------------------------------------

    def push_telemetry(self, kind: str, values: dict) -> int:
        """
        POST /api/telemetry/{project}/{device}/{kind}.

        *values* must be a flat dict of numeric metric names → values.
        Returns the HTTP status code.
        """
        url = self._url(f"telemetry/{{project}}/{{device}}/{kind}")
        log.info("POST %s  %s", url, values)
        resp = self._client.post(url, json=values, headers=self._auth_headers())
        log.info("  → %d", resp.status_code)
        self._check_auth(resp)
        return resp.status_code

    def push_system_telemetry(self, kind: str = "system", **extra) -> int:
        """
        Push a system-telemetry payload analogous to postSystemTelemetry() in arduino4iot.

        Values include simulated battery voltage, WiFi RSSI, boot count etc.
        """
        values = {
            "battery_V": round(random.uniform(3.5, 4.2), 3),
            "wifi_rssi": random.randint(-80, -40),
            "boot_count": random.randint(1, 1000),
            "active_ms": random.randint(200, 5000),
            "firmware_version": "python-sim-1.0.0",
        }
        values.update(extra)
        return self.push_telemetry(kind, values)

    # ------------------------------------------------------------------
    # 5. Log push
    # ------------------------------------------------------------------

    def push_log(self, message: str) -> int:
        """
        POST /api/log/{project}/{device} with Content-Type: text/plain.

        Returns the HTTP status code.
        """
        url = self._url("log/{project}/{device}")
        log.info("POST %s  %d chars", url, len(message))
        headers = self._auth_headers({"Content-Type": "text/plain"})
        resp = self._client.post(url, content=message.encode(), headers=headers)
        log.info("  → %d", resp.status_code)
        self._check_auth(resp)
        return resp.status_code

    # ------------------------------------------------------------------
    # 6. File upload
    # ------------------------------------------------------------------

    def upload_file(self, filename: str, content: bytes) -> int:
        """
        PUT /api/file/{project}/{device}/{filename}.

        Returns the HTTP status code.
        """
        url = self._url(f"file/{{project}}/{{device}}/{filename}")
        log.info("PUT %s  %d bytes", url, len(content))
        headers = self._auth_headers({"Content-Type": "application/octet-stream"})
        resp = self._client.put(url, content=content, headers=headers)
        log.info("  → %d", resp.status_code)
        self._check_auth(resp)
        return resp.status_code

    # ------------------------------------------------------------------
    # 7. File download
    # ------------------------------------------------------------------

    def download_file(self, filename: str) -> tuple[bytes | None, bool]:
        """
        GET /api/file/{project}/{device}/{filename} with ETag caching.

        Returns (content_bytes, was_updated).
        """
        url = self._url(f"file/{{project}}/{{device}}/{filename}")
        etag_key = f"file:{filename}"
        headers = self._auth_headers({"Accept": "*/*"})
        if etag_key in self._etags:
            headers["If-None-Match"] = self._etags[etag_key]

        log.info("GET %s", url)
        resp = self._client.get(url, headers=headers)
        log.info("  → %d  %d bytes", resp.status_code, len(resp.content))
        self._check_auth(resp)

        if resp.status_code == 304:
            return None, False
        if resp.status_code == 200:
            if "ETag" in resp.headers:
                self._etags[etag_key] = resp.headers["ETag"]
                self._save_state()
            return resp.content, True
        log.error("  Download failed: %d", resp.status_code)
        return None, False

    # ------------------------------------------------------------------
    # Full device wake-up cycle
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        telemetry: dict[str, dict] | None = None,
        log_message: str | None = None,
        check_config: bool = True,
        check_firmware: bool = True,
    ) -> dict:
        """
        Run a complete device wake-up cycle, mirroring arduino4iot's loop():

          1. Provision (skipped if token already stored)
          2. Config download (conditional, ETag)
          3. Firmware OTA check (HEAD, ETag)
          4. Telemetry push (system + application)
          5. Log push (optional)

        Returns a summary dict with per-step results.
        """
        results: dict = {}

        # 1. Provision
        results["provisioned"] = self.provision()

        if not self._device_token:
            log.error("No device token — aborting cycle")
            results["error"] = "no_token"
            return results

        # 2. Config
        if check_config:
            cfg, updated = self.download_config()
            results["config_updated"] = updated
            results["config"] = cfg

        # 3. Firmware
        if check_firmware:
            results["firmware_update_available"] = self.check_firmware()

        # 4. System telemetry (always)
        results["system_telemetry_status"] = self.push_system_telemetry()

        # 5. Application telemetry
        if telemetry:
            results["telemetry"] = {}
            for kind, values in telemetry.items():
                results["telemetry"][kind] = self.push_telemetry(kind, values)

        # 6. Log
        if log_message:
            results["log_status"] = self.push_log(log_message)

        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_client(args: argparse.Namespace) -> DeviceClient:
    return DeviceClient(
        base_url=args.url,
        project_name=args.project,
        device_name=args.device,
        provisioning_token=args.token,
        state_file=args.state,
        verbose=args.verbose,
    )


def cmd_cycle(args: argparse.Namespace) -> None:
    client = _build_client(args)
    telemetry = {}
    if args.sensors:
        telemetry["sensors"] = json.loads(args.sensors)
    result = client.run_cycle(
        telemetry=telemetry or None,
        log_message=args.log,
        check_config=not args.no_config,
        check_firmware=not args.no_firmware,
    )
    print(json.dumps(result, indent=2, default=str))


def cmd_provision(args: argparse.Namespace) -> None:
    client = _build_client(args)
    ok = client.provision(force=args.force)
    print("provisioned" if ok else "skipped (token already stored)")


def cmd_telemetry(args: argparse.Namespace) -> None:
    client = _build_client(args)
    client.provision()
    values = json.loads(args.values)
    status = client.push_telemetry(args.kind, values)
    print(f"HTTP {status}")


def cmd_log(args: argparse.Namespace) -> None:
    client = _build_client(args)
    client.provision()
    status = client.push_log(args.message)
    print(f"HTTP {status}")


def cmd_upload(args: argparse.Namespace) -> None:
    client = _build_client(args)
    client.provision()
    content = Path(args.local_path).read_bytes()
    filename = args.filename or Path(args.local_path).name
    status = client.upload_file(filename, content)
    print(f"HTTP {status}")


def cmd_download(args: argparse.Namespace) -> None:
    client = _build_client(args)
    client.provision()
    data, updated = client.download_file(args.filename)
    if data is None:
        print("Not modified or not found")
    else:
        dest = Path(args.output or args.filename)
        dest.write_bytes(data)
        print(f"Saved {len(data)} bytes to {dest}")


def cmd_loop(args: argparse.Namespace) -> None:
    """Simulate a device that wakes up periodically."""
    client = _build_client(args)
    boot = 0
    while True:
        boot += 1
        log.info("=== Boot %d ===", boot)
        temp = round(20 + random.gauss(0, 2), 2)
        humidity = round(60 + random.gauss(0, 5), 1)
        try:
            client.run_cycle(
                telemetry={"sensors": {"temperature": temp, "humidity": humidity}},
                log_message=f"Boot {boot}: temp={temp}°C humidity={humidity}%",
            )
        except httpx.ConnectError as e:
            log.error("Server unreachable: %s — retrying in %ds", e, args.interval)
        except httpx.TimeoutException as e:
            log.error("Request timed out: %s — retrying in %ds", e, args.interval)
        except Exception as e:
            log.error("Cycle failed: %s — retrying in %ds", e, args.interval)
        log.info("Sleeping %ds", args.interval)
        time.sleep(args.interval)


def main() -> None:
    p = argparse.ArgumentParser(
        description="arduino4iot device simulator for nice4iot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default="http://localhost:8000", help="nice4iot base URL")
    p.add_argument("--project", required=True, help="Project name")
    p.add_argument("--device", required=True, help="Device name")
    p.add_argument("--token", required=True, help="Provisioning token")
    p.add_argument("--state", default=None, help="State file path (default: .<device>.state.json)")
    p.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    sub = p.add_subparsers(dest="command", required=True)

    # cycle
    c_cycle = sub.add_parser("cycle", help="Run a full device wake-up cycle")
    c_cycle.add_argument("--sensors", metavar="JSON", help='Sensor payload, e.g. \'{"temp":22.4}\'')
    c_cycle.add_argument("--log", metavar="MSG", help="Log message to push")
    c_cycle.add_argument("--no-config", action="store_true", help="Skip config download")
    c_cycle.add_argument("--no-firmware", action="store_true", help="Skip firmware OTA check")
    c_cycle.set_defaults(func=cmd_cycle)

    # provision
    c_prov = sub.add_parser("provision", help="Obtain a device token (no-op if already stored)")
    c_prov.add_argument("--force", action="store_true", help="Re-provision even if token exists")
    c_prov.set_defaults(func=cmd_provision)

    # telemetry
    c_tel = sub.add_parser("telemetry", help="Push telemetry measurements")
    c_tel.add_argument("kind", help='Measurement kind, e.g. "sensors"')
    c_tel.add_argument("values", help='JSON dict, e.g. \'{"temperature": 22.4}\'')
    c_tel.set_defaults(func=cmd_telemetry)

    # log
    c_log = sub.add_parser("log", help="Push a plain-text log message")
    c_log.add_argument("message", help="Log text to push")
    c_log.set_defaults(func=cmd_log)

    # upload
    c_up = sub.add_parser("upload", help="Upload a local file to the device")
    c_up.add_argument("local_path", help="Local file path")
    c_up.add_argument("--filename", help="Remote filename (default: basename of local_path)")
    c_up.set_defaults(func=cmd_upload)

    # download
    c_dl = sub.add_parser("download", help="Download a file from the device")
    c_dl.add_argument("filename", help="Remote filename")
    c_dl.add_argument("--output", help="Local destination path (default: filename)")
    c_dl.set_defaults(func=cmd_download)

    # loop
    c_loop = sub.add_parser("loop", help="Simulate periodic wake-ups (runs forever)")
    c_loop.add_argument("--interval", type=float, default=30, metavar="SECONDS",
                        help="Wake-up interval in seconds (default: 30)")
    c_loop.set_defaults(func=cmd_loop)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
