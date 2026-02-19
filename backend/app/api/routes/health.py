from datetime import datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, Any]:
    return {"data": {"status": "ok", "timestamp": datetime.utcnow().isoformat()}}
