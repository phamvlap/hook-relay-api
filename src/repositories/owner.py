from sqlalchemy.orm import Session

from src.models.owner import Owner


class OwnerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def create(self) -> Owner:
        owner = Owner()
        self.session.add(owner)
        self.session.flush()
        return owner
