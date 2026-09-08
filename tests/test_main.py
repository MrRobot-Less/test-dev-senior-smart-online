from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import smart_online_automation.main as main_module
from smart_online_automation.config import Settings
from smart_online_automation.database import upsert
from smart_online_automation.models import (
    STATUS_DEBITO,
    STATUS_ERRO,
    STATUS_PENDENTE,
    STATUS_SEM_DEBITO,
    ConsultaNfe,
)
from smart_online_automation.portal import ConsultaResult
from smart_online_automation.seed import SEED_KEYS, seed_keys


class FakePage:
    async def close(self) -> None:
        pass


class FakeAutomation:
    def __init__(self, settings) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass

    async def open(self, url: str) -> FakePage:
        return FakePage()


@pytest.mark.asyncio
async def test_fluxo_completo_com_rerun_idempotente(
    monkeypatch, test_db_url, session_factory
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=test_db_url,
        retry_max_attempts=1,
    )

    monkeypatch.setattr(main_module, "BrowserAutomation", FakeAutomation)

    sem_debito = SEED_KEYS[:3]
    debitos = SEED_KEYS[3:-1]
    erro = SEED_KEYS[-1]

    chamadas = {}

    async def resultado_fake(portal, page, settings, chave: str) -> ConsultaResult:
        chamadas[chave] = chamadas.get(chave, 0) + 1
        if chave in sem_debito:
            return ConsultaResult(status=STATUS_SEM_DEBITO)
        if chave == erro and chamadas[chave] == 1:
            return ConsultaResult(status=STATUS_ERRO, detalhes="portal fora do ar")
        return ConsultaResult(status=STATUS_DEBITO, valor_pagar=Decimal("1500.75"))

    monkeypatch.setattr(main_module, "consultar_com_retry", resultado_fake)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()

    await main_module.run(settings)

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
    assert len(registros) == len(SEED_KEYS)
    assert sum(1 for r in registros if r.status == STATUS_SEM_DEBITO) == len(sem_debito)
    assert sum(1 for r in registros if r.status == STATUS_DEBITO) == len(debitos)
    assert sum(1 for r in registros if r.status == STATUS_ERRO) == 1
    debitos = [r for r in registros if r.status == STATUS_DEBITO]
    assert all(r.valor_pagar == Decimal("1500.75") for r in debitos)
    assert all(r.tentativas == 1 for r in registros)

    await main_module.run(settings)

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
    assert len(registros) == len(SEED_KEYS)
    assert all(r.status != STATUS_ERRO for r in registros)
    reprocessado = {r.chave: r for r in registros}[erro]
    assert reprocessado.status == STATUS_DEBITO
    assert reprocessado.tentativas == 2
    sem_debito = [r for r in registros if r.status == STATUS_SEM_DEBITO]
    assert all(r.tentativas == 1 for r in sem_debito)


@pytest.mark.asyncio
async def test_falha_de_banco_nao_impede_demais_chaves(
    monkeypatch, test_db_url, session_factory
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=test_db_url,
        retry_max_attempts=1,
        db_retry_max_attempts=1,
    )

    monkeypatch.setattr(main_module, "BrowserAutomation", FakeAutomation)

    async def resultado_fake(portal, page, settings, chave: str) -> ConsultaResult:
        return ConsultaResult(status=STATUS_SEM_DEBITO)

    monkeypatch.setattr(main_module, "consultar_com_retry", resultado_fake)

    upsert_real = main_module.upsert
    falhas = {"restantes": 3}

    async def upsert_instavel(session, model, values):
        if falhas["restantes"] > 0:
            falhas["restantes"] -= 1
            raise OperationalError("upsert", {}, Exception("connection lost"))
        await upsert_real(session, model, values)

    monkeypatch.setattr(main_module, "upsert", upsert_instavel)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()

    await main_module.run(settings)

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
    assert len(registros) == len(SEED_KEYS)
    assert sum(1 for r in registros if r.status == STATUS_PENDENTE) == 3
    assert sum(1 for r in registros if r.status == STATUS_SEM_DEBITO) == len(SEED_KEYS) - 3

    await main_module.run(settings)

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
    assert len(registros) == len(SEED_KEYS)
    assert all(r.status == STATUS_SEM_DEBITO for r in registros)


async def test_review_mostra_chaves_e_status(test_db_url, session_factory, capsys) -> None:
    settings = Settings(_env_file=None, database_url=test_db_url)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()

    await main_module.review(settings)

    saida = capsys.readouterr().out
    assert SEED_KEYS[0] in saida
    assert "PENDENTE" in saida


def test_run_cli_traduz_falha_em_saida_limpa(monkeypatch) -> None:
    async def executar_falho(args) -> None:
        raise RuntimeError("portal sem conexao")

    monkeypatch.setattr(main_module, "_executar", executar_falho)

    with pytest.raises(SystemExit) as exc_info:
        main_module.run_cli(["run"])

    assert exc_info.value.code == 1


@pytest.mark.asyncio
async def test_reset_recria_tabela_e_volta_ao_estado_inicial(
    test_db_url, session_factory
) -> None:
    settings = Settings(_env_file=None, database_url=test_db_url)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()
    async with session_factory() as session:
        await upsert(
            session,
            ConsultaNfe,
            {
                "chave": SEED_KEYS[0],
                "status": STATUS_DEBITO,
                "valor_pagar": Decimal("10.00"),
            },
        )
        await session.commit()

    await main_module.reset(settings)

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
    assert len(registros) == len(SEED_KEYS)
    assert all(r.status == STATUS_PENDENTE for r in registros)
    assert all(r.valor_pagar is None for r in registros)
    assert all(r.tentativas == 0 for r in registros)