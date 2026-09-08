from decimal import Decimal

from smart_online_automation.models import STATUS_DEBIT, STATUS_ERROR, STATUS_NO_DEBIT
from smart_online_automation.portal import (
    PortalUnavailableError,
    _extract_brl_value,
    classify_details,
    classify_dialog,
)

NO_DEBIT_MSG = (
    "INFORMAÇÃO "
    "O ICMS ainda não foi liberado para pagamento ou o débito é inexistente. "
    "Verifique os dados informados ou tente novamente mais tarde. OK"
)


def test_classifica_sem_debito() -> None:
    resultado = classify_dialog(NO_DEBIT_MSG)
    assert resultado.status == STATUS_NO_DEBIT
    assert resultado.valor_pagar is None


def test_classifica_debito_com_valor() -> None:
    dialogo = "ATENÇÃO Débito de ICMS identificado Valor a pagar: R$ 1.234,56 Detalhes"
    resultado = classify_dialog(dialogo)
    assert resultado.status == STATUS_DEBIT
    assert resultado.valor_pagar == Decimal("1234.56")


def test_classifica_debito_sem_centavos() -> None:
    dialogo = "Débito pendente R$ 2.000,00 referente à NF-e"
    resultado = classify_dialog(dialogo)
    assert resultado.status == STATUS_DEBIT
    assert resultado.valor_pagar == Decimal("2000.00")


def test_classifica_resultado_nao_reconhecido() -> None:
    dialogo = "ERRO Uma mensagem completamente inesperada do portal"
    resultado = classify_dialog(dialogo)
    assert resultado.status == STATUS_ERROR
    assert resultado.detalhes is not None
    assert resultado.detalhes.startswith("resultado_nao_reconhecido")


def test_portal_indisponivel_e_erro_de_negocio() -> None:
    assert issubclass(PortalUnavailableError, RuntimeError)


def test_valor_sem_espaco_apos_prefino() -> None:
    assert _extract_brl_value("Total do débito: R$0,50") == Decimal("0.50")


def test_valor_com_milhar_de_dois_digitos() -> None:
    assert _extract_brl_value("Valor R$ 12.345,67") == Decimal("12345.67")


def test_valor_com_milhar_invalido_ignorado() -> None:
    assert _extract_brl_value("R$ 1234.567,89") is None


def test_valor_sem_duas_casas_decimais_ignorado() -> None:
    assert _extract_brl_value("R$ 1.234,5") is None
    assert _extract_brl_value("R$ 1.234,567") is None


def test_valor_sem_fracao_ignorado() -> None:
    assert _extract_brl_value("R$ 1.234") is None


def test_sem_prefino_de_valor_retorna_none() -> None:
    assert _extract_brl_value("Débito identificado, total 1.234,56") is None


def test_classifica_detalhes_sem_debito() -> None:
    resultado = classify_details("Total a Recolher: R$ 0,00")
    assert resultado.status == STATUS_NO_DEBIT
    assert resultado.valor_pagar is None


def test_classifica_detalhes_com_debito() -> None:
    resultado = classify_details("Total a Recolher R$ 1.234,56")
    assert resultado.status == STATUS_DEBIT
    assert resultado.valor_pagar == Decimal("1234.56")


def test_classifica_detalhes_nao_reconhecido() -> None:
    resultado = classify_details("Nenhum valor encontrado nesta pagina")
    assert resultado.status == STATUS_ERROR
    assert resultado.detalhes is not None
    assert resultado.detalhes.startswith("resultado_nao_reconhecido")