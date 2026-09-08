import argparse
import asyncio
from dataclasses import replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from smart_online_automation.automation import BrowserAutomation
from smart_online_automation.config import Settings, get_settings
from smart_online_automation.database import (
    Base,
    build_engine,
    build_session_factory,
    insert_on_conflict_ignore,
    upsert,
)
from smart_online_automation.logging_config import configure_logging, get_logger
from smart_online_automation.models import STATUS_ERROR, STATUS_PENDING, NfeQuery
from smart_online_automation.portal import PortalClient, PortalUnavailableError, QueryResult
from smart_online_automation.seed import SEED_KEYS, seed_keys

logger = get_logger("main")


async def _ensure_schema(settings: Settings, reset: bool = False):
    engine = build_engine(settings.database_url)
    last_error: Exception | None = None
    for attempt in range(settings.db_retry_max_attempts):
        try:
            async with engine.begin() as conn:
                if reset:
                    await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
            return engine
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= settings.db_retry_max_attempts:
                break
            logger.warning(
                "banco_instavel", attempt=attempt + 1, error=str(exc)
            )
            await asyncio.sleep(settings.db_retry_wait_seconds)
    await engine.dispose()
    if last_error is None:
        last_error = RuntimeError("sem tentativas de conexao configuradas")
    raise last_error


async def seed(settings: Settings) -> None:
    engine = await _ensure_schema(settings)
    async with build_session_factory(engine)() as session:
        inserted = await seed_keys(session)
        await session.commit()
    await engine.dispose()
    logger.info("seed_concluido", inserted=inserted, total=len(SEED_KEYS))


async def review(settings: Settings) -> None:
    engine = await _ensure_schema(settings)
    async with build_session_factory(engine)() as session:
        records = (
            await session.scalars(select(NfeQuery).order_by(NfeQuery.chave))
        ).all()
        for record in records:
            valor = f"R$ {record.valor_pagar:.2f}" if record.valor_pagar is not None else "-"
            print(
                f"{record.chave}  {record.status:<10}  {valor:<12}  "
                f"tentativas={record.tentativas}"
            )
    await engine.dispose()
    logger.info("review_concluido", keys=len(records))


async def reset(settings: Settings) -> None:
    engine = await _ensure_schema(settings, reset=True)
    async with build_session_factory(engine)() as session:
        inserted = await seed_keys(session)
        await session.commit()
    await engine.dispose()
    logger.info("reset_concluido", keys=inserted)


async def query_with_retry(
    portal: PortalClient, page: Any, settings: Settings, key: str
) -> QueryResult:
    last_error: PortalUnavailableError | None = None
    for attempt in range(1, settings.retry_max_attempts + 1):
        try:
            result = await portal.query(page, key)
            return replace(result, attempts=attempt)
        except PortalUnavailableError as exc:
            last_error = exc
            if attempt < settings.retry_max_attempts:
                await asyncio.sleep(settings.retry_wait_seconds)
    return QueryResult(
        status=STATUS_ERROR,
        detalhes=str(last_error),
        attempts=settings.retry_max_attempts,
    )


async def _persist_with_retry(settings: Settings, session_factory, values: dict) -> None:
    for attempt in range(settings.db_retry_max_attempts):
        try:
            async with session_factory() as session:
                await upsert(session, NfeQuery, values)
                await session.commit()
            return
        except OperationalError as exc:
            if attempt + 1 >= settings.db_retry_max_attempts:
                raise
            logger.warning(
                "persistencia_instavel", attempt=attempt + 1, error=str(exc)
            )
            await asyncio.sleep(settings.db_retry_wait_seconds)


async def _define_target(
    session_factory, keys: list[str] | None, todo: bool
) -> list[str]:
    if keys:
        async with session_factory() as session:
            await insert_on_conflict_ignore(
                session,
                NfeQuery,
                [{"chave": key, "status": STATUS_PENDING} for key in keys],
            )
            await session.commit()
        return list(dict.fromkeys(keys))
    async with session_factory() as session:
        stmt = select(NfeQuery.chave).order_by(NfeQuery.chave)
        if not todo:
            stmt = stmt.where(NfeQuery.status.in_((STATUS_PENDING, STATUS_ERROR)))
        return list(await session.scalars(stmt))


async def _process_key(
    settings: Settings, session_factory, portal: PortalClient, page: Any, key: str
) -> None:
    async with session_factory() as session:
        record = await session.get(NfeQuery, key)
        base_attempts = record.tentativas if record is not None else 0
    try:
        result = await query_with_retry(portal, page, settings, key)
    except Exception as exc:
        logger.error("consulta_falhou", key=key, error=str(exc))
        result = QueryResult(
            status=STATUS_ERROR,
            detalhes=str(exc),
            attempts=settings.retry_max_attempts,
        )
    values = {
        "chave": key,
        "status": result.status,
        "valor_pagar": result.valor_pagar,
        "detalhes": result.detalhes,
        "tentativas": base_attempts + result.attempts,
        "consultada_em": func.now(),
        "atualizada_em": func.now(),
    }
    try:
        await _persist_with_retry(settings, session_factory, values)
        logger.info(
            "chave_processada",
            key=key,
            status=values["status"],
            valor=(
                str(values["valor_pagar"]) if values["valor_pagar"] is not None else None
            ),
            tentativas=values["tentativas"],
        )
    except Exception as exc:
        logger.error("persistencia_falhou", key=key, error=str(exc))


async def run(
    settings: Settings, keys: list[str] | None = None, todo: bool = False
) -> None:
    engine = await _ensure_schema(settings)
    session_factory = build_session_factory(engine)
    target = await _define_target(session_factory, keys, todo)
    if not target:
        await engine.dispose()
        logger.info("nenhuma_chave_para_consultar")
        return
    logger.info("run_iniciado", keys=len(target), all=todo)
    try:
        async with BrowserAutomation(settings) as automation:
            page = await automation.open(settings.portal_url)
            portal = PortalClient(settings)
            try:
                for key in target:
                    await _process_key(settings, session_factory, portal, page, key)
            finally:
                try:
                    await page.close()
                except Exception as exc:
                    logger.warning("page_close_falhou", error=str(exc))
    finally:
        await engine.dispose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-online-automation",
        description="Query NF-e keys on the portal and persist the result.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("seed", help="register the test keys as pending")
    sub.add_parser("review", help="list keys and their current status")
    sub.add_parser("reset", help="recreate the tables and return to the initial state")

    run_parser = sub.add_parser(
        "run", help="query PENDING/ERROR keys (or the selected ones)"
    )
    run_parser.add_argument(
        "--headless", action="store_true", help="run the browser without a window"
    )
    run_parser.add_argument(
        "--all", action="store_true", help="reprocess all keys"
    )
    run_parser.add_argument(
        "--key",
        action="append",
        metavar="KEY",
        help="reprocess a specific key (may repeat the flag)",
    )
    return parser


async def _execute(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")
    logger.info(
        "comando_iniciado",
        command=args.command,
        app=settings.app_name,
        env=settings.app_env,
    )
    if args.command == "seed":
        await seed(settings)
        return
    if args.command == "review":
        await review(settings)
        return
    if args.command == "reset":
        await reset(settings)
        return
    if args.headless:
        settings = settings.model_copy(update={"headless": True})
    await run(settings, keys=args.key, todo=args.all)


def run_cli(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    try:
        asyncio.run(_execute(args))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        logger.error("comando_falhou", command=args.command, error=str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    run_cli()
