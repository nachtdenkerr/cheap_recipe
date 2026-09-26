"""API request/response models.

Field names are snake_case in Python and camelCase on the wire, matching
frontend/src/api/types.ts. Money is in euro cents, as the frontend expects.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )
