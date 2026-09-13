from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import Settings

settings = Settings()


def get_engine(database_url: str, echo: bool = False):
    return create_engine(str(database_url), echo=False)


def get_local_session(database_url: str):
    engine = get_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()
