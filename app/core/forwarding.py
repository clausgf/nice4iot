import json,httpx,asyncio,typing

from pydantic import BaseModel
from fastapi import HTTPException

from app.core.project import get_project_path

class ForwardingModel(BaseModel):
    forward_url : str = "http://localhost:8080"
    forward_method : typing.Literal["GET","POST","PUT","HEAD","DELETE"] = "GET"

class ForwardingModelList(BaseModel):
    forwards : typing.Dict[str,ForwardingModel] = {"testforward":ForwardingModel()}

async def forward(project_name : str,forwarding_name : str,data : str,headers: dict,timeout : int):
    project_forwards_path = get_project_path(project_name) / '.forwards.json'
    #project_forwards_path.write_text(ForwardingModelList().model_dump_json())
    with open(project_forwards_path,'r') as forwards: 
        forward_dict = ForwardingModelList.model_validate_json(forwards.read())
        forwarding = forward_dict.forwards.get(forwarding_name)
    if not forwarding:
        raise HTTPException(status_code=404,details="Forwarding not found")
    async with httpx.AsyncClient() as client:
        async with asyncio.timeout(timeout):
            match forwarding.forward_method:
                case "GET":
                    return await client.get(forwarding.forward_url,headers=headers)
                case "POST":
                    return await client.post(forwarding.forward_url,headers=headers,data=data)
                case "PUT":
                    return await client.put(forwarding.forward_url,headers=headers,data=data)
                case "HEAD":
                    return await client.head(forwarding.forward_url,headers=headers)
                case "DELETE":
                    return await client.delete(forwarding.forward_url,headers=headers,data=data)



