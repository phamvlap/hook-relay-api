from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.api.deps import get_event_service
from src.schemas.event import (
    EventCreateRequest,
    EventCreateResponse,
)
from src.services.event import EventService

router = APIRouter()


@router.post("", response_model=EventCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_event(
    data: EventCreateRequest,
    event_service: Annotated[EventService, Depends(get_event_service)],
) -> EventCreateResponse:
    """
    Create a new event.
    """
    return await event_service.create(data)
