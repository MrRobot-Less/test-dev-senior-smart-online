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
    insert_ignorando_conflito,
    upsert,
)
from smart_online_automation.logging_config import configure_logging, get_logger
from smart_online_automation.models import STATUS_ERRO, STATUS_PENDENTE, ConsultaNfe
from smart_online_automation.portal import ConsultaResult, PortalClient, PortalIndisponivelError
from smart_online_automation.seed import SEED_KEYS, seed_keys

logger = get_logger("main")


async def _garantir_esquema(settings: Settings, resetar: bool = False):
    engine = build_engine(settings.database_url)
    ultimo_erro: Exception | None = None
    for tentativa in range(settings.db_retry_max_attempts):
        try:
            async with engine.begin() as conn:
                if resetar:
                    await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
            return engine
        except Exception as exc:
            ultimo_erro = exc
            if tentativa + 1 >= settings.db_retry_max_attempts:
                break
            logger.warning(
                "banco_instavel", tentativa=tentativa + 1, error=str(exc)
            )
            await asyncio.sleep(settings.db_retry_wait_seconds)
    await engine.dispose()
    if ultimo_erro is None:
        ultimo_erro = RuntimeError("sem tentativas de conexao configuradas")
    raise ultimo_erro


async def seed(settings: Settings) -> None:
    engine = await _garantir_esquema(settings)
    async with build_session_factory(engine)() as session:
        inseridas = await seed_keys(session)
        await session.commit()
    await engine.dispose()
    logger.info("seed_concluido", inseridas=inseridas, total=len(SEED_KEYS))


async def review(settings: Settings) -> None:
    engine = await _garantir_esquema(settings)
    async with build_session_factory(engine)() as session:
        registros = (await session.scalars(select(ConsultaNfe).order_by(ConsultaNfe.chave))).all()
        for registro in registros:
            valor = f"R$ {registro.valor_pagar:.2f}" if registro.valor_pagar is not None else "-"
            print(
                f"{registro.chave}  {registro.status:<10}  {valor:<12}  "
                f"tentativas={registro.tentativas}"
            )
    await engine.dispose()
    logger.info("review_concluido", chaves=len(registros))


async def reset(settings: Settings) -> None:
    engine = await _garantir_esquema(settings, resetar=True)
    async with build_session_factory(engine)() as session:
        inseridas = await seed_keys(session)
        await session.commit()
    await engine.dispose()
    logger.info("reset_concluido", chaves=inseridas)


async def consultar_com_retry(
    portal: PortalClient, page: Any, settings: Settings, chave: str
) -> ConsultaResult:
    ultimo_erro: PortalIndisponivelError | None = None
    for tentativa in range(1, settings.retry_max_attempts + 1):
        try:
            resultado = await portal.consultar(page, chave)
            return replace(resultado, tentativas=tentativa)
        except PortalIndisponivelError as exc:
            ultimo_erro = exc
            if tentativa < settings.retry_max_attempts:
                await asyncio.sleep(settings.retry_wait_seconds)
    return ConsultaResult(
        status=STATUS_ERRO,
        detalhes=str(ultimo_erro),
        tentativas=settings.retry_max_attempts,
    )


async def _persistir_com_retry(settings: Settings, session_factory, valores: dict) -> None:
    for tentativa in range(settings.db_retry_max_attempts):
        try:
            async with session_factory() as session:
                await upsert(session, ConsultaNfe, valores)
                await session.commit()
            return
        except OperationalError as exc:
            if tentativa + 1 >= settings.db_retry_max_attempts:
                raise
            logger.warning(
                "persistencia_instavel", tentativa=tentativa + 1, error=str(exc)
            )
            await asyncio.sleep(settings.db_retry_wait_seconds)


async def _definir_alvo(
    session_factory, chaves: list[str] | None, todo: bool
) -> list[str]:
    if chaves:
        async with session_factory() as session:
            await insert_ignorando_conflito(
                session,
                ConsultaNfe,
                [{"chave": chave, "status": STATUS_PENDENTE} for chave in chaves],
            )
            await session.commit()
        return list(dict.fromkeys(chaves))
    async with session_factory() as session:
        stmt = select(ConsultaNfe.chave).order_by(ConsultaNfe.chave)
        if not todo:
            stmt = stmt.where(ConsultaNfe.status.in_((STATUS_PENDENTE, STATUS_ERRO)))
        return list(await session.scalars(stmt))


async def _processar_chave(
    settings: Settings, session_factory, portal: PortalClient, page: Any, chave: str
) -> None:
    async with session_factory() as session:
        registro = await session.get(ConsultaNfe, chave)
        tentativas_base = registro.tentativas if registro is not None else 0
    try:
        resultado = await consultar_com_retry(portal, page, settings, chave)
    except Exception as exc:
        logger.error("consulta_falhou", chave=chave, error=str(exc))
        resultado = ConsultaResult(
            status=STATUS_ERRO,
            detalhes=str(exc),
            tentativas=settings.retry_max_attempts,
        )
    valores = {
        "chave": chave,
        "status": resultado.status,
        "valor_pagar": resultado.valor_pagar,
        "detalhes": resultado.detalhes,
        "tentativas": tentativas_base + resultado.tentativas,
        "consultada_em": func.now(),
        "atualizada_em": func.now(),
    }
    try:
        await _persistir_com_retry(settings, session_factory, valores)
        logger.info(
            "chave_processada",
            chave=chave,
            status=valores["status"],
            valor=(
                str(valores["valor_pagar"]) if valores["valor_pagar"] is not None else None
            ),
            tentativas=valores["tentativas"],
        )
    except Exception as exc:
        logger.error("persistencia_falhou", chave=chave, error=str(exc))


async def run(
    settings: Settings, chaves: list[str] | None = None, todo: bool = False
) -> None:
    engine = await _garantir_esquema(settings)
    session_factory = build_session_factory(engine)
    alvo = await _definir_alvo(session_factory, chaves, todo)
    if not alvo:
        await engine.dispose()
        logger.info("nenhuma_chave_para_consultar")
        return
    logger.info("run_iniciado", chaves=len(alvo), all=todo)
    try:
        async with BrowserAutomation(settings) as automation:
            page = await automation.open(settings.portal_url)
            portal = PortalClient(settings)
            try:
                for chave in alvo:
                    await _processar_chave(settings, session_factory, portal, page, chave)
            finally:
                try:
                    await page.close()
                except Exception as exc:
                    logger.warning("page_close_falhou", error=str(exc))
    finally:
        await engine.dispose()


def _montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-online-automation",
        description="Consulta NF-e no portal e registra o resultado no banco.",
    )
    sub = parser.add_subparsers(dest="comando", metavar="comando")

    sub.add_parser("seed", help="cadastra as chaves do teste como pendentes")
    sub.add_parser("review", help="lista as chaves e o status atual")
    sub.add_parser("reset", help="recria as tabelas e volta ao estado inicial")

    run_parser = sub.add_parser(
        "run", help="consulta as chaves PENDENTE/ERRO (ou as escolhidas)"
    )
    run_parser.add_argument(
        "--headless", action="store_true", help="roda o navegador sem janela"
    )
    run_parser.add_argument(
        "--all", action="store_true", help="reprocessa todas as chaves"
    )
    run_parser.add_argument(
        "--key",
        action="append",
        metavar="KEY",
        help="reprocessa uma chave especifica (pode repetir o flag)",
    )
    return parser


async def _executar(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")
    logger.info(
        "comando_iniciado",
        comando=args.comando,
        app=settings.app_name,
        env=settings.app_env,
    )
    if args.comando == "seed":
        await seed(settings)
        return
    if args.comando == "review":
        await review(settings)
        return
    if args.comando == "reset":
        await reset(settings)
        return
    if args.headless:
        settings = settings.model_copy(update={"headless": True})
    await run(settings, chaves=args.key, todo=args.all)


def run_cli(argv: list[str] | None = None) -> None:
    parser = _montar_parser()
    args = parser.parse_args(argv)
    if args.comando is None:
        parser.print_help()
        return
    try:
        asyncio.run(_executar(args))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        logger.error("comando_falhou", comando=args.comando, error=str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    run_cli()
