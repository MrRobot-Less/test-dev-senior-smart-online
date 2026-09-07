from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def insert_ignorando_conflito(session: AsyncSession, model, values: list[dict]) -> int:
    stmt = pg_insert(model).values(values).on_conflict_do_nothing(
        index_elements=[model.chave]
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def upsert(session: AsyncSession, model, values: dict) -> None:
    stmt = pg_insert(model).values(values)
    update_values = {key: value for key, value in values.items() if key != "chave"}
    stmt = stmt.on_conflict_do_update(index_elements=[model.chave], set_=update_values)
    await session.execute(stmt)