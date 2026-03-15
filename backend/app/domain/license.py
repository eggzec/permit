from __future__ import annotations

import json
from typing import Annotated

import base58
from pydantic import (
    UUID7,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.ed25519 import load_private_ed25519_key


__all__ = ["BaseLicense", "NodeLockedLicense"]


class BaseLicense(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: UUID7
    vendor_id: UUID7
    client_id: UUID7
    expires_at: Annotated[float, Field(gt=0)]
    max_grace_secs: Annotated[int, Field(ge=0)]
    created_at: Annotated[float, Field(gt=0)]
    meta_data: Annotated[dict[str, str] | None, Field(default=None)]

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, default=str)

    @model_validator(mode="after")
    def check_expiry(self: BaseLicense) -> BaseLicense:
        if self.expires_at <= self.created_at:
            raise ValueError("expiry date cannot be before creation date")
        return self


class NodeLockedLicense(BaseLicense):
    device_fingerprint: str
    session_limit: Annotated[int, Field(gt=0)]


class LicenseFile(BaseModel):
    """Represents a signed `license.dat` file.

    Attributes:
        data: The license payload that was signed.
        signature: Base58-encoded Ed25519 signature over the canonical
            JSON representation of *data*.  Uses the standard Bitcoin
            base58 alphabet (signatures are not user-facing).
    """

    model_config = ConfigDict(validate_assignment=True)

    license_data: BaseLicense
    private_key_pem: Annotated[bytes, Field(exclude=True)]

    @computed_field
    @property
    def signature(self) -> str:
        key = load_private_ed25519_key(self.private_key_pem)
        payload = self.license_data.canonical_json()
        signature = base58.b58encode(key.sign(payload.encode())).decode()
        return signature

    @field_validator("private_key_pem")
    @classmethod
    def private_key_pem_validator(cls, v: bytes) -> bytes:
        # this should fail in case the key is not a valid Ed25519 private key
        load_private_ed25519_key(v)
        return v
