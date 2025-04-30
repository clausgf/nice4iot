import httpx,json,time
from app.core.logging.logging import LoggingBackend
from pydantic import BaseModel
class LokiConfig(BaseModel):
    log_url : str = "http://localhost:8082/loki/api/v1/push"

class LokiBackend(LoggingBackend):
    def __init__(self, config: LokiConfig = LokiConfig()):
        self.config = config
    
    async def write(self,logmsg : str):
        logstr = {
            "streams": [ {
                "stream": {"test": "test2"},
                "values": [[str(round(time.time() * 1000)),logmsg]]
            }]
            }
        logstr = json.dumps(logstr)
        print(logstr)
        async with httpx.AsyncClient() as client:
            headers= {"Content-Type": "application/json"}
            r = await client.post(self.config.log_url,data=logstr,headers=headers)
            print(r.status_code)
            print(r.content)