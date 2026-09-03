import asyncio

from smart_online_automation.automation import BrowserAutomation
from smart_online_automation.config import Settings, get_settings
from smart_online_automation.database import Base, build_engine, build_session_factory
from smart_online_automation.logging_config import configure_logging, get_logger
from smart_online_automation.models import AutomationRun

logger = get_logger("main")


def run_automation(settings: Settings) -> None:
    with BrowserAutomation(settings) as automation:
        page = automation.open(settings.base_url)
        logger.info("page_loaded", url=settings.base_url, title=page.title())
        page.close()


async def main() -> None:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")
    logger.info(
        "starting_automation",
        app=settings.app_name,
        env=settings.app_env,
        target=settings.base_url,
    )

    engine = build_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        await asyncio.to_thread(run_automation, settings)
        status, details = "success", None
    except Exception as exc:
        logger.error("automation_failed", error=str(exc))
        status, details = "failed", str(exc)

    async with build_session_factory(engine)() as session:
        session.add(AutomationRun(scenario="smoke", status=status, details=details))
        await session.commit()
    await engine.dispose()

    logger.info("automation_finished", status=status)


def run_cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run_cli()
