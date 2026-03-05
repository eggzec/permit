"""Auth routes — signup, login, token refresh."""

from fastapi import APIRouter, status

from app.api.deps import CursorDep, SettingsDep
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from app.schemas.response import SuccessResponse
from app.services import auth as auth_service

router = APIRouter()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessResponse[SignupResponse],
)
def signup(body: SignupRequest, cursor: CursorDep, settings: SettingsDep):
    """Create a new vendor account."""
    result = auth_service.signup(
        cursor=cursor,
        email=body.email,
        password=body.password,
        client_id=body.client_id,
        settings=settings,
    )
    return SuccessResponse(data=result)


@router.post(
    "/login",
    response_model=SuccessResponse[TokenPair],
)
def login(body: LoginRequest, cursor: CursorDep, settings: SettingsDep):
    """Authenticate a vendor and return an access/refresh token pair."""
    result = auth_service.login(
        cursor=cursor,
        email=body.email,
        password=body.password,
        client_id=body.client_id,
        settings=settings,
    )
    return SuccessResponse(data=result)


@router.post(
    "/refresh",
    response_model=SuccessResponse[TokenPair],
)
def refresh(body: RefreshRequest, cursor: CursorDep, settings: SettingsDep):
    """Issue a new token pair using a valid refresh token."""
    result = auth_service.refresh(
        refresh_token_str=body.refresh_token,
        client_id=body.client_id,
        cursor=cursor,
        settings=settings,
    )
    return SuccessResponse(data=result)
