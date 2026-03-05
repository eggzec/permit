from pydantic import BaseModel, EmailStr, Field


# ── Request schemas ──────────────────────────────────────────


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    client_id: str = Field(..., min_length=1, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    client_id: str = Field(..., min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str
    client_id: str = Field(..., min_length=1, max_length=256)


# ── Response schemas ─────────────────────────────────────────


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class VendorOut(BaseModel):
    id: str
    email: str


class SignupResponse(BaseModel):
    vendor: VendorOut
