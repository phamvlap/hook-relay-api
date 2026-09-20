from sqlalchemy.orm import Session

from src.core.config import settings
from src.database.session import get_local_session
from src.models.owner import Owner


class OwnerRepository:
    def __init__(self, session: Session | None = None):
        if session is None:
            session = get_local_session(str(settings.postgres_dsn))
        self.session = session

    async def create(self) -> Owner:
        owner = Owner()
        self.session.add(owner)
        self.session.commit()
        self.session.refresh(owner)
        return owner
