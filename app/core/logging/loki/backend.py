import asyncio
import httpx
import json
import time

from app.core.logging.models import LokiConfig
from app.util import logger


class LokiBackend:
    def __init__(self, project_name: str, config: LokiConfig = LokiConfig()):
        self.project_name = project_name
        self.config = config

    async def write(self, device_name: str, logmsg: str) -> None:
        payload = json.dumps({"streams": [{
            "stream": {"project": self.project_name, "device": device_name},
            "values": [[str(round(time.time() * 1_000_000_000)), logmsg]],
        }]})
        headers = {"Content-Type": "application/json"}
        if self.config.tenant_id:
            headers["X-Scope-OrgID"] = self.config.tenant_id
        auth = (self.config.username, self.config.password) if self.config.username else None
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(self.config.timeout):
                    resp = await client.post(
                        self.config.log_url,
                        data=payload,
                        headers=headers,
                        auth=auth,
                    )
            if resp.status_code >= 400:
                raise RuntimeError(f"Loki returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Loki backend error for {self.project_name}/{device_name}: {e}")
            raise
