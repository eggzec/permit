from fastapi import APIRouter

from app.api.routes import health, login

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(login.router, prefix="/login", tags=["login"])
