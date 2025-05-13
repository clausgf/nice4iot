import typing
from pydantic import BaseModel


class ForwardingModel(BaseModel):
    forward_url : str = ""
    forward_method : typing.Literal["GET","POST","PUT","HEAD","DELETE"] = "GET"


class ForwardingModelList(BaseModel):
    forwards : typing.Dict[str,ForwardingModel] = {}

