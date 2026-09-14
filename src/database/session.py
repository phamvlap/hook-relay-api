from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_engine(database_url: str, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo)


def get_local_session(database_url: str) -> Session:
    engine = get_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()
