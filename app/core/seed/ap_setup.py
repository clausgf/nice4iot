"""The AP+captive-portal deep link and its QR code (Web-Serial-Flash's sibling,
"AP + Formular" workflow). The captive portal itself runs entirely on the
device (arduino4iot's IotAp, see docs/concepts.md#first-time-provisioning-softap-captive-portal
in the arduino4iot repo) — this module only builds the URL a phone opens once
joined to the device's own setup AP, and a QR code of that URL.

Query param names (wifiSsid/wifiPassword/apiUrl/project/provisioningToken) are
that captive portal's contract and intentionally differ from the NVS key
spellings in app.core.seed.nvs (wifiPass/provToken) — do not conflate the two.
TLS trust is deliberately not part of this flow (see the same doc section):
an https:// device must already carry a build- or NVS-seeded tlsMode/caCert.
"""
import base64
import io
from urllib.parse import urlencode

import qrcode

from app.core.seed.backend import EffectiveSeed

AP_SETUP_BASE_URL = 'http://192.168.4.1/'


def build_ap_setup_url(seed: EffectiveSeed) -> str:
    """The deep-link URL a phone opens after joining the device's own setup AP.
    All params are independent/optional — nothing is written to the device
    until its form's Save is tapped."""
    params = {}
    if seed.wifi_ssid:
        params['wifiSsid'] = seed.wifi_ssid
    if seed.wifi_password:
        params['wifiPassword'] = seed.wifi_password
    if seed.api_url:
        params['apiUrl'] = seed.api_url
    if seed.project_name:
        params['project'] = seed.project_name
    if seed.provisioning_token:
        params['provisioningToken'] = seed.provisioning_token
    return AP_SETUP_BASE_URL + '?' + urlencode(params)


def qr_png_data_uri(data: str) -> str:
    """A QR code of `data`, as a data: URI PNG for ui.image()."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
