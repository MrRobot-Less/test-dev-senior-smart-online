import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from smart_online_automation.database import Base, build_session_factory
from smart_online_automation.models import AutomationRun


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield build_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_automation_run(session_factory) -> None:
    async with session_factory() as session:
        session.add(AutomationRun(scenario="smoke", status="success"))
        await session.commit()

    async with session_factory() as session:
        run = await session.get(AutomationRun, 1)
        assert run is not None
        assert run.scenario == "smoke"
        assert run.status == "success"
        assert run.started_at is not None
        assert run.finished_at is None


@pytest.mark.asyncio
async def test_query_runs_by_status(session_factory) -> None:
    async with session_factory() as session:
        session.add(AutomationRun(scenario="smoke", status="success"))
        session.add(AutomationRun(scenario="smoke", status="failed", details="boom"))
        await session.commit()

    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.scalars(
            select(AutomationRun).where(AutomationRun.status == "failed")
        )
        runs = result.all()
        assert len(runs) == 1
        assert runs[0].details == "boom"
