from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.pagination import PageNumberPaginationParams
from src.database.session import get_local_session
from src.repositories.endpoint import EndpointRepository
from src.services.endpoint import EndpointService


def get_db() -> Generator[Session]:
    db: Session = get_local_session(str(settings.postgres_dsn))
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]


def get_endpoint_repository(session: SessionDep) -> EndpointRepository:
    return EndpointRepository(session=session)


def get_endpoint_service(
    endpoint_repository: Annotated[EndpointRepository, Depends(get_endpoint_repository)],
) -> EndpointService:
    return EndpointService(endpoint_repository=endpoint_repository)


def get_page_number_pagination_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PageNumberPaginationParams:
    return PageNumberPaginationParams(page=page, page_size=page_size)
