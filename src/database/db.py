from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase

metadata = MetaData()


class Base(AsyncAttrs, DeclarativeBase):
    metadata = metadata
