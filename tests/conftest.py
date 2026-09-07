import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from smart_online_automation.database import Base, build_session_factory

DB_HOST = "localhost:5433"
DB_USER = "automation"
DB_PASS = "automation"
ADMIN_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}/automation"
TEST_DB_NAME = "automation_test"
TEST_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return TEST_URL


@pytest.fixture(scope="session")
async def test_engine():
    try:
        admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            existe = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :nome"),
                {"nome": TEST_DB_NAME},
            )
            if not existe:
                await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        await admin.dispose()
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL indisponível em {DB_HOST}: {exc}. "
            "Rode `docker compose up -d db` antes dos testes."
        )

    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE consultas_nfe"))
    return build_session_factory(test_engine)