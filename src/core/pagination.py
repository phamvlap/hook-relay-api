from collections.abc import Sequence
from typing import TypeVar

from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.query import Query as SQLAlchemyQuery
from sqlalchemy.sql import func, select


class PageNumberPaginationParams(BaseModel):
    page: int = 1
    page_size: int = 10

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


T = TypeVar("T")


class PageNumberPaginationResponse[T](BaseModel):
    total: int
    previous: str | None = None
    next: str | None = None
    items: Sequence[T]

    @classmethod
    def build(
        cls,
        total: int,
        page: int,
        page_size: int,
        items: Sequence[T],
        request: Request,
    ) -> "PageNumberPaginationResponse[T]":
        total_pages = (total + page_size - 1) // page_size

        def _build_url(page_number: int) -> str:
            query_params = dict(request.query_params)
            query_params["page"] = str(page_number)
            query_params["page_size"] = str(page_size)
            return str(request.url.replace_query_params(**query_params))

        prev_page_url = _build_url(page - 1) if page > 1 else None
        next_page_url = _build_url(page + 1) if page < total_pages else None

        return cls(
            total=total,
            previous=prev_page_url,
            next=next_page_url,
            items=items,
        )


async def paginate(
    session: AsyncSession,
    request: Request,
    query: SQLAlchemyQuery,
    params: PageNumberPaginationParams,
) -> PageNumberPaginationResponse[object]:
    total_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(total_query)
    total = total_result.scalar() or 0

    items_result = await session.execute(query.offset(params.offset).limit(params.limit))
    items = items_result.scalars().all()

    return PageNumberPaginationResponse.build(
        total=total,
        page=params.page,
        page_size=params.page_size,
        items=items,
        request=request,
    )
