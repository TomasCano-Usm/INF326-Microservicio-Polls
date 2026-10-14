import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Los timestamps de Polls deben incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, _dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Database:
    def __init__(self, url: str | None = None, create_schema: bool = False) -> None:
        self.url = url or os.getenv("DATABASE_URL", "")
        if not self.url:
            raise ValueError("La variable DATABASE_URL es obligatoria.")

        self.engine: AsyncEngine = create_async_engine(self.url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._create_schema = create_schema

    async def connect(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(select(1))
            if self._create_schema:
                await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()
