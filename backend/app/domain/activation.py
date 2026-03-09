from __future__ import annotations

from typing import ClassVar
from uuid import UUID

import uuid6
from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.internal import base32_crockford


__all__ = ["ActivationCode"]


class ActivationCode(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    LENGTH: ClassVar[int] = 30
    GROUP: ClassVar[int] = 5

    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        # TODO: need the proper error handling here.
        normalized = base32_crockford.normalize(v)

        if len(normalized) != cls.LENGTH:
            raise ValueError("Activation code must contain 30 symbols")

        base32_crockford.decode(normalized, checksum=True)

        return "-".join(
            normalized[i : i + cls.GROUP]
            for i in range(0, cls.LENGTH, cls.GROUP)
        )

    @computed_field
    @property
    def uuid(self) -> UUID:
        flat = base32_crockford.normalize(self.code)
        n = base32_crockford.decode(flat, checksum=True)
        return UUID(int=n)

    @classmethod
    def generate(cls, uuid: UUID | None = None) -> ActivationCode:
        if uuid is None:
            uuid = uuid6.uuid7()
        if not isinstance(uuid, UUID):
            raise TypeError(f"uuid cannot be of type {uuid.__class__.__name__}")
        if uuid.version != 7:  # noqa: PLR2004
            raise TypeError(
                f"uuid must be a UUID version 7, got {uuid.version}"
            )

        encoded = base32_crockford.encode(uuid.int, checksum=True)
        encoded = encoded.rjust(cls.LENGTH, "0")

        return cls(code=encoded)
