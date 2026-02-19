from fastapi import FastAPI
from fastapi.routing import APIRoute

from permit.api.main import api_router
from permit.core.config import settings


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"

API_V1_STR = "/api/v1"

# also use the lifespan with this to do the prestart and shutdown events
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

app.include_router(api_router, prefix=API_V1_STR)
