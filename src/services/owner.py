from src.repositories.owner import OwnerRepository
from src.schemas.owner import OwnerCreateResponse


class OwnerService:
    def __init__(self, *, owner_repository: OwnerRepository | None = None):
        self.owner_repository = owner_repository or OwnerRepository()

    async def create(self) -> OwnerCreateResponse:
        owner = await self.owner_repository.create()
        return OwnerCreateResponse.model_validate(owner)
