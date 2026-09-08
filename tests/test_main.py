from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import smart_online_automation.main as main_module
from smart_online_automation.config import Settings
from smart_online_automation.database import upsert
from smart_online_automation.models import (
    STATUS_DEBIT,
    STATUS_ERROR,
    STATUS_NO_DEBIT,
    STATUS_PENDING,
    NfeQuery,
)
from smart_online_automation.portal import QueryResult
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

    no_debit = SEED_KEYS[:3]
    debits = SEED_KEYS[3:-1]
    error = SEED_KEYS[-1]

    calls = {}

    async def fake_result(portal, page, settings, chave: str) -> QueryResult:
        calls[chave] = calls.get(chave, 0) + 1
        if chave in no_debit:
            return QueryResult(status=STATUS_NO_DEBIT)
        if chave == error and calls[chave] == 1:
            return QueryResult(status=STATUS_ERROR, detalhes="portal fora do ar")
        return QueryResult(status=STATUS_DEBIT, valor_pagar=Decimal("1500.75"))

    monkeypatch.setattr(main_module, "query_with_retry", fake_result)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()

    await main_module.run(settings)

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
    assert len(records) == len(SEED_KEYS)
    assert sum(1 for r in records if r.status == STATUS_NO_DEBIT) == len(no_debit)
    assert sum(1 for r in records if r.status == STATUS_DEBIT) == len(debits)
    assert sum(1 for r in records if r.status == STATUS_ERROR) == 1
    debits = [r for r in records if r.status == STATUS_DEBIT]
    assert all(r.valor_pagar == Decimal("1500.75") for r in debits)
    assert all(r.tentativas == 1 for r in records)

    await main_module.run(settings)

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
    assert len(records) == len(SEED_KEYS)
    assert all(r.status != STATUS_ERROR for r in records)
    reprocessed = {r.chave: r for r in records}[error]
    assert reprocessed.status == STATUS_DEBIT
    assert reprocessed.tentativas == 2
    no_debit = [r for r in records if r.status == STATUS_NO_DEBIT]
    assert all(r.tentativas == 1 for r in no_debit)


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

    async def fake_result(portal, page, settings, chave: str) -> QueryResult:
        return QueryResult(status=STATUS_NO_DEBIT)

    monkeypatch.setattr(main_module, "query_with_retry", fake_result)

    real_upsert = main_module.upsert
    failures = {"restantes": 3}

    async def unstable_upsert(session, model, values):
        if failures["restantes"] > 0:
            failures["restantes"] -= 1
            raise OperationalError("upsert", {}, Exception("connection lost"))
        await real_upsert(session, model, values)

    monkeypatch.setattr(main_module, "upsert", unstable_upsert)

    async with session_factory() as session:
        await seed_keys(session)
        await session.commit()

    await main_module.run(settings)

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
    assert len(records) == len(SEED_KEYS)
    assert sum(1 for r in records if r.status == STATUS_PENDING) == 3
    assert sum(1 for r in records if r.status == STATUS_NO_DEBIT) == len(SEED_KEYS) - 3

    await main_module.run(settings)

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
    assert len(records) == len(SEED_KEYS)
    assert all(r.status == STATUS_NO_DEBIT for r in records)


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

    monkeypatch.setattr(main_module, "_execute", executar_falho)

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
            NfeQuery,
            {
                "chave": SEED_KEYS[0],
                "status": STATUS_DEBIT,
                "valor_pagar": Decimal("10.00"),
            },
        )
        await session.commit()

    await main_module.reset(settings)

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
    assert len(records) == len(SEED_KEYS)
    assert all(r.status == STATUS_PENDING for r in records)
    assert all(r.valor_pagar is None for r in records)
    assert all(r.tentativas == 0 for r in records)