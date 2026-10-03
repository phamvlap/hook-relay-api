from sqlalchemy.ext.asyncio import AsyncSession

from src.models.owner import Owner


class OwnerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self) -> Owner:
        owner = Owner()
        self.session.add(owner)
        await self.session.flush()
        return owner
