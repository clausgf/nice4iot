import datetime
from typing import Annotated, Literal

import niceview
from pydantic import BaseModel, Field


class SeedSettings(BaseModel):
    """Bootstrap data an arduino4iot device needs before it can call ``/provision``:
    WiFi credentials, the server's public API URL, and (for a self-hosted/self-signed
    setup) the CA certificate to trust. Combined with the project name and a
    provisioning token (see the Provisioning section) into a device's seed data.
    Stored as ``.seed.json`` in the project directory.
    """

    wifi_ssid: Annotated[str,
            Field(title='WiFi SSID',
                  description='WiFi network name the device joins at first boot.'),
            niceview.Field()
        ] = ''

    wifi_password: Annotated[str,
            Field(title='WiFi Password'),
            niceview.Field(password=True)
        ] = ''

    api_url: Annotated[str,
            Field(title='API URL',
                  description='Public base URL devices use to reach this server '
                              '(e.g. https://iot.example.com). nice4iot cannot detect this '
                              'itself — it has no configured base_url and normally sits '
                              'behind a reverse proxy terminating TLS.'),
            niceview.Field()
        ] = ''

    tls_mode: Annotated[
            Literal['public', 'custom'],
            Field(title='TLS mode',
                  description='Whether the API URL is served with a publicly trusted '
                              'certificate or a self-hosted/self-signed one.'),
            niceview.Field(options={
                'public': 'Public CA (e.g. Let\'s Encrypt)',
                'custom': 'Self-hosted / self-signed',
            })
        ] = 'public'

    ca_cert: Annotated[str,
            Field(title='CA certificate',
                  description='PEM-encoded CA certificate the device must trust. '
                              'Only needed when TLS mode is "Self-hosted / self-signed".'),
            niceview.Field(widget_type='ui.textarea')
        ] = ''

    updated_at: Annotated[datetime.datetime | None,
            Field(description='Timestamp of the last change (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = None

    class Meta:
        description = ('Seed data for a fresh arduino4iot device — WiFi, API URL and TLS trust — '
                       'so it can reach this server and provision itself.')
        profiles = {
            'settings': [
                ['wifi_ssid', 'wifi_password'],
                'api_url',
                ['tls_mode', 'ca_cert'],
            ],
        }


class DeviceSeedOverride(BaseModel):
    """Per-device WiFi override for the project's Seed settings — for the rare
    device that needs different WiFi credentials than the rest of the project.
    Stored as ``.seed_override.json`` in the device directory.
    """

    override_enabled: Annotated[bool,
            Field(title='Override project settings',
                  description='Use this device\'s own WiFi credentials instead of the '
                              'project\'s Seed settings.'),
            niceview.Field()
        ] = False

    wifi_ssid: Annotated[str,
            Field(title='WiFi SSID'),
            niceview.Field()
        ] = ''

    wifi_password: Annotated[str,
            Field(title='WiFi Password'),
            niceview.Field(password=True)
        ] = ''

    updated_at: Annotated[datetime.datetime | None,
            Field(description='Timestamp of the last change (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = None

    class Meta:
        description = 'Override this device\'s WiFi credentials instead of inheriting the project\'s Seed settings.'
        profiles = {
            'settings': [
                'override_enabled',
                ['wifi_ssid', 'wifi_password'],
            ],
        }
