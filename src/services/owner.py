from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.repositories.owner import OwnerRepository
from src.schemas.owner import OwnerCreateResponse


class OwnerService:
    def __init__(self, *, owner_repository: OwnerRepository, session: Session) -> None:
        self.owner_repository = owner_repository
        self.session = session

    async def create(self) -> OwnerCreateResponse:
        try:
            with self.session.begin_nested():
                owner = await self.owner_repository.create()

            self.session.commit()
            return OwnerCreateResponse.model_validate(owner)

        except IntegrityError:
            self.session.rollback()
            raise

        except Exception:
            self.session.rollback()
            raise
