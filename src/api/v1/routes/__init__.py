from fastapi import APIRouter

from .endpoint import router as endpoint_router
from .event import router as event_router

router = APIRouter()

router.include_router(
    prefix="/endpoints",
    tags=["Endpoints"],
    router=endpoint_router,
)
router.include_router(
    prefix="/events",
    tags=["Events"],
    router=event_router,
)
