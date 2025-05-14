import typing
from pydantic import BaseModel, model_validator,Field
from app.util import is_valid_filename

class ForwardingModel(BaseModel):
    forward_url : str = Field(pattern='.*')
    forward_method : typing.Literal["GET","POST","PUT","HEAD","DELETE"] = "GET"


class ForwardingModelList(BaseModel):
    forwards : typing.Dict[str,ForwardingModel] = {}

    @model_validator(mode="after")
    def validate_nested(self) -> typing.Self:
        for k,v in self.forwards.items():
            if not is_valid_filename(k):
                raise ValueError("Invalid forwarding name")
            ForwardingModel.model_validate(dict(v),strict=True)
        return self
