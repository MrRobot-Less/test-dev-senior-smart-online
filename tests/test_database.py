from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from smart_online_automation.database import upsert
from smart_online_automation.models import (
    STATUS_DEBITO,
    STATUS_PENDENTE,
    STATUS_SEM_DEBITO,
    ConsultaNfe,
)
from smart_online_automation.seed import SEED_KEYS, seed_keys

CHAVE = "33260829612882000128550040000113801131657747"


async def test_seed_insere_chaves_uma_vez(session_factory) -> None:
    async with session_factory() as session:
        assert await seed_keys(session) == 7
        await session.commit()
        assert await seed_keys(session) == 0
        await session.commit()

    async with session_factory() as session:
        chaves = (await session.scalars(select(ConsultaNfe))).all()
        assert len(chaves) == 7
        assert all(c.status == STATUS_PENDENTE for c in chaves)
        assert {c.chave for c in chaves} == set(SEED_KEYS)


async def test_upsert_insere_e_atualiza_sem_duplicar(session_factory) -> None:
    async with session_factory() as session:
        await upsert(
            session,
            ConsultaNfe,
            {"chave": CHAVE, "status": STATUS_SEM_DEBITO, "tentativas": 1},
        )
        await session.commit()

    async with session_factory() as session:
        await upsert(
            session,
            ConsultaNfe,
            {
                "chave": CHAVE,
                "status": STATUS_DEBITO,
                "valor_pagar": Decimal("1234.56"),
                "tentativas": 2,
            },
        )
        await session.commit()

    async with session_factory() as session:
        registros = (await session.scalars(select(ConsultaNfe))).all()
        assert len(registros) == 1
        assert registros[0].status == STATUS_DEBITO
        assert registros[0].valor_pagar == Decimal("1234.56")
        assert registros[0].tentativas == 2


async def test_check_constraint_rejeita_status_invalido(session_factory) -> None:
    async with session_factory() as session:
        try:
            await upsert(session, ConsultaNfe, {"chave": CHAVE, "status": "INVALIDO"})
            await session.commit()
            raised = False
        except IntegrityError:
            raised = True
        assert raised is True


async def test_check_constraint_exige_valor_para_debito(session_factory) -> None:
    async with session_factory() as session:
        try:
            await upsert(session, ConsultaNfe, {"chave": CHAVE, "status": STATUS_DEBITO})
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
                ConsultaNfe,
                {
                    "chave": CHAVE,
                    "status": STATUS_SEM_DEBITO,
                    "valor_pagar": Decimal("1.00"),
                },
            )
            await session.commit()
            raised = False
        except IntegrityError:
            raised = True
        assert raised is True