from sqlalchemy.ext.asyncio import AsyncSession

from smart_online_automation.database import insert_ignorando_conflito
from smart_online_automation.models import STATUS_PENDENTE, ConsultaNfe

SEED_KEYS = [
    "33260829612882000128550040000113801131657747",
    "35260851574438000114550030000121601176163628",
    "17260407019231000358550010033237311018267145",
    "35260824634280000239550020003531001633126920",
    "31260823146734000260550030000277311642415921",
    "31260813807794000141550100004790481594957992",
    "31260861366601000107550010000403621122906367",
]


async def seed_keys(session: AsyncSession) -> int:
    rows = [{"chave": chave, "status": STATUS_PENDENTE} for chave in SEED_KEYS]
    return await insert_ignorando_conflito(session, ConsultaNfe, rows)