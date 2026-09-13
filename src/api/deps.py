from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from core.config import Settings
from database.session import get_local_session

settings = Settings()


def get_db() -> Generator[Session]:
    db: Session = get_local_session(settings.postgres_dsn)
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]
