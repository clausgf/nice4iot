import httpx, json, time

from app.core.logging.models import LokiConfig


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
        async with httpx.AsyncClient() as client:
            await client.post(
                self.config.log_url,
                data=payload,
                headers=headers,
                auth=auth,
                timeout=self.config.timeout,
            )
