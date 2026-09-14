from fastapi import APIRouter

from .endpoint import router as endpoint_router

router = APIRouter()

router.include_router(
    prefix="/endpoints",
    tags=["Endpoints"],
    router=endpoint_router,
)
