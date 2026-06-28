import httpx,json,time
from app.core.logging.models import LoggingBackend
from pydantic import BaseModel

class LokiConfig(BaseModel):
    log_url : str = "http://alloy:8082/loki/api/v1/push"
    timeout : int = 10

class LokiBackend(LoggingBackend):
    def __init__(self, project_name: str, config: LokiConfig = LokiConfig()):
        super().__init__(project_name)
        self.config = config
    
    async def write(self,device_name: str, logmsg: str):
        logstr = {
            "streams": [ {
                "stream": {"project": self.project_name, "device": device_name},
                "values": [[str(round(time.time() * 1_000_000_000)), logmsg]]
            }]
            }
        logstr = json.dumps(logstr)
        async with httpx.AsyncClient() as client:
            headers= {"Content-Type": "application/json"}
            r = await client.post(self.config.log_url, data=logstr, headers=headers)
