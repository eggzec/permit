from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import Settings

# Use bcrypt only as required by spec
password_hash = PasswordHash((BcryptHasher(),))


ALGORITHM = "HS256"


def create_access_token(
    vendor_id: str, settings: Settings, *, expires_delta: timedelta | None = None
) -> str:
    """Create a short-lived access token with vendor_id claim."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "vendor_id": str(vendor_id),
        "exp": expire,
        "token_type": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    vendor_id: str, settings: Settings, *, expires_delta: timedelta | None = None
) -> str:
    """Create a long-lived refresh token with vendor_id claim."""
    if expires_delta is None:
        expires_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "vendor_id": str(vendor_id),
        "exp": expire,
        "token_type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)
