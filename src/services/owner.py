from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.owner import OwnerRepository
from src.schemas.owner import OwnerCreateResponse


class OwnerService:
    def __init__(self, *, owner_repository: OwnerRepository, session: AsyncSession) -> None:
        self.owner_repository = owner_repository
        self.session = session

    async def create(self) -> OwnerCreateResponse:
        try:
            async with self.session.begin_nested():
                owner = await self.owner_repository.create()

            await self.session.commit()
            return OwnerCreateResponse.model_validate(owner)

        except IntegrityError:
            await self.session.rollback()
            raise

        except Exception:
            await self.session.rollback()
            raise
