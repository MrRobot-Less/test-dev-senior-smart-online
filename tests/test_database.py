from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from smart_online_automation.database import upsert
from smart_online_automation.models import (
    STATUS_DEBIT,
    STATUS_NO_DEBIT,
    STATUS_PENDING,
    NfeQuery,
)
from smart_online_automation.seed import SEED_KEYS, seed_keys

KEY = "33260829612882000128550040000113801131657747"


async def test_seed_insere_chaves_uma_vez(session_factory) -> None:
    async with session_factory() as session:
        assert await seed_keys(session) == len(SEED_KEYS)
        await session.commit()
        assert await seed_keys(session) == 0
        await session.commit()

    async with session_factory() as session:
        keys = (await session.scalars(select(NfeQuery))).all()
        assert len(keys) == len(SEED_KEYS)
        assert all(c.status == STATUS_PENDING for c in keys)
        assert {c.chave for c in keys} == set(SEED_KEYS)


async def test_upsert_insere_e_atualiza_sem_duplicar(session_factory) -> None:
    async with session_factory() as session:
        await upsert(
            session,
            NfeQuery,
            {"chave": KEY, "status": STATUS_NO_DEBIT, "tentativas": 1},
        )
        await session.commit()

    async with session_factory() as session:
        await upsert(
            session,
            NfeQuery,
            {
                "chave": KEY,
                "status": STATUS_DEBIT,
                "valor_pagar": Decimal("1234.56"),
                "tentativas": 2,
            },
        )
        await session.commit()

    async with session_factory() as session:
        records = (await session.scalars(select(NfeQuery))).all()
        assert len(records) == 1
        assert records[0].status == STATUS_DEBIT
        assert records[0].valor_pagar == Decimal("1234.56")
        assert records[0].tentativas == 2


async def test_check_constraint_rejeita_status_invalido(session_factory) -> None:
    async with session_factory() as session:
        try:
            await upsert(session, NfeQuery, {"chave": KEY, "status": "INVALIDO"})
            await session.commit()
            raised = False
        except IntegrityError:
            raised = True
        assert raised is True


async def test_check_constraint_exige_valor_para_debito(session_factory) -> None:
    async with session_factory() as session:
        try:
            await upsert(session, NfeQuery, {"chave": KEY, "status": STATUS_DEBIT})
            await session.commit()
            raised = False
        except IntegrityError:
            raised = True
        assert raised is True


async def test_check_constraint_veta_valor_sem_debito(session_factory) -> None:
    async with session_factory() as session:
        try:
            await upsert(
                session,
                NfeQuery,
                {
                    "chave": KEY,
                    "status": STATUS_NO_DEBIT,
                    "valor_pagar": Decimal("1.00"),
                },
            )
            await session.commit()
            raised = False
        except IntegrityError:
            raised = True
        assert raised is True