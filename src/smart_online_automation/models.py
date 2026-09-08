from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from smart_online_automation.database import Base

STATUS_PENDENTE = "PENDENTE"
STATUS_DEBITO = "DEBITO"
STATUS_SEM_DEBITO = "SEM_DEBITO"
STATUS_ERRO = "ERRO"

class ConsultaNfe(Base):
    __tablename__ = "consultas_nfe"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDENTE', 'DEBITO', 'SEM_DEBITO', 'ERRO')",
            name="ck_consultas_nfe_status",
        ),
        CheckConstraint(
            "(status = 'DEBITO') = (valor_pagar IS NOT NULL)",
            name="ck_consultas_nfe_status_valor",
        ),
    )

    chave: Mapped[str] = mapped_column(String(44), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    valor_pagar: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    detalhes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tentativas: Mapped[int] = mapped_column(default=0)
    consultada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )