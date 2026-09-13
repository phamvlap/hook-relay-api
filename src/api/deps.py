from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from src.core.config import settings
from src.database.session import get_local_session


def get_db() -> Generator[Session]:
    db: Session = get_local_session(str(settings.postgres_dsn))
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]
