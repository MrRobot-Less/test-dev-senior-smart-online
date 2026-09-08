from decimal import Decimal

from smart_online_automation.models import STATUS_DEBITO, STATUS_ERRO, STATUS_SEM_DEBITO
from smart_online_automation.portal import (
    PortalIndisponivelError,
    _extrair_valor_brl,
    classificar_consulta,
    classificar_detalhes,
)

SEM_DEBITO_MSG = (
    "INFORMAÇÃO "
    "O ICMS ainda não foi liberado para pagamento ou o débito é inexistente. "
    "Verifique os dados informados ou tente novamente mais tarde. OK"
)


def test_classifica_sem_debito() -> None:
    resultado = classificar_consulta(SEM_DEBITO_MSG)
    assert resultado.status == STATUS_SEM_DEBITO
    assert resultado.valor_pagar is None


def test_classifica_debito_com_valor() -> None:
    dialogo = "ATENÇÃO Débito de ICMS identificado Valor a pagar: R$ 1.234,56 Detalhes"
    resultado = classificar_consulta(dialogo)
    assert resultado.status == STATUS_DEBITO
    assert resultado.valor_pagar == Decimal("1234.56")


def test_classifica_debito_sem_centavos() -> None:
    dialogo = "Débito pendente R$ 2.000,00 referente à NF-e"
    resultado = classificar_consulta(dialogo)
    assert resultado.status == STATUS_DEBITO
    assert resultado.valor_pagar == Decimal("2000.00")


def test_classifica_resultado_nao_reconhecido() -> None:
    dialogo = "ERRO Uma mensagem completamente inesperada do portal"
    resultado = classificar_consulta(dialogo)
    assert resultado.status == STATUS_ERRO
    assert resultado.detalhes is not None
    assert resultado.detalhes.startswith("resultado_nao_reconhecido")


def test_portal_indisponivel_e_erro_de_negocio() -> None:
    assert issubclass(PortalIndisponivelError, RuntimeError)


def test_valor_sem_espaco_apos_prefino() -> None:
    assert _extrair_valor_brl("Total do débito: R$0,50") == Decimal("0.50")


def test_valor_com_milhar_de_dois_digitos() -> None:
    assert _extrair_valor_brl("Valor R$ 12.345,67") == Decimal("12345.67")


def test_valor_com_milhar_invalido_ignorado() -> None:
    assert _extrair_valor_brl("R$ 1234.567,89") is None


def test_valor_sem_duas_casas_decimais_ignorado() -> None:
    assert _extrair_valor_brl("R$ 1.234,5") is None
    assert _extrair_valor_brl("R$ 1.234,567") is None


def test_valor_sem_fracao_ignorado() -> None:
    assert _extrair_valor_brl("R$ 1.234") is None


def test_sem_prefino_de_valor_retorna_none() -> None:
    assert _extrair_valor_brl("Débito identificado, total 1.234,56") is None


def test_classifica_detalhes_sem_debito() -> None:
    resultado = classificar_detalhes("Total a Recolher: R$ 0,00")
    assert resultado.status == STATUS_SEM_DEBITO
    assert resultado.valor_pagar is None


def test_classifica_detalhes_com_debito() -> None:
    resultado = classificar_detalhes("Total a Recolher R$ 1.234,56")
    assert resultado.status == STATUS_DEBITO
    assert resultado.valor_pagar == Decimal("1234.56")


def test_classifica_detalhes_nao_reconhecido() -> None:
    resultado = classificar_detalhes("Nenhum valor encontrado nesta pagina")
    assert resultado.status == STATUS_ERRO
    assert resultado.detalhes is not None
    assert resultado.detalhes.startswith("resultado_nao_reconhecido")