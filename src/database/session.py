from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings

# Create a SQLAlchemy engine and session factory for the local database connection
engine = create_engine(
    settings.postgres_dsn_str,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

# Session factory for creating new sessions
LocalSession = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_local_session() -> Session:
    return LocalSession()
