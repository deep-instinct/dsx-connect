from fastapi import APIRouter

from dsx_connect_ng.config import settings

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/status")
async def ui_status() -> dict:
    return {
        "surface": "ui",
        "service": settings.service_name,
        "intended_callers": [
            "browser_frontend",
            "desktop_frontend",
            "operator_ui",
        ],
        "notes": "UI routes are presentation-oriented and must remain separate from control-plane and execution contracts.",
    }
