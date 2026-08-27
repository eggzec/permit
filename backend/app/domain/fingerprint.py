import hashlib
import json
from functools import cached_property
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field


__all__ = ["Device"]


class Device(BaseModel):
    model_config = ConfigDict(frozen=True)

    cpu_id: Annotated[str, Field(json_schema_extra={"score": 10})]
    motherboard_id: Annotated[str, Field(json_schema_extra={"score": 10})]
    motherboard_serial: Annotated[str, Field(json_schema_extra={"score": 10})]
    machine_id: Annotated[str, Field(json_schema_extra={"score": 10})]
    primary_disk_serial: Annotated[str, Field(json_schema_extra={"score": 10})]

    @computed_field
    @cached_property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(exclude_computed_fields=True), sort_keys=True
        )
        checksum = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
        return checksum
