import asyncio
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal

from playwright.async_api import Locator, Page, expect
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from smart_online_automation.config import Settings
from smart_online_automation.logging_config import get_logger
from smart_online_automation.models import STATUS_DEBITO, STATUS_ERRO, STATUS_SEM_DEBITO

PREFIXO_VALOR = "R$"

logger = get_logger("portal")


class PortalIndisponivelError(RuntimeError):
    pass


@dataclass
class ConsultaResult:
    status: str
    valor_pagar: Decimal | None = None
    detalhes: str | None = None
    tentativas: int = 1


def _inteiro_valido(inteiro: str) -> bool:
    if not inteiro or not all(c.isdigit() or c == "." for c in inteiro):
        return False
    if inteiro.startswith(".") or inteiro.endswith("."):
        return False
    if "." not in inteiro:
        return True
    partes = inteiro.split(".")
    return len(partes[0]) <= 3 and all(len(parte) == 3 and parte.isdigit() for parte in partes[1:])


def _parse_valor_token(trecho: str) -> Decimal | None:
    fim = 0
    while fim < len(trecho) and (trecho[fim].isdigit() or trecho[fim] in ".,"):
        fim += 1
    token = trecho[:fim]
    if "," not in token:
        return None
    inteiro, fracao = token.rsplit(",", 1)
    if len(fracao) != 2 or not fracao.isdigit() or not _inteiro_valido(inteiro):
        return None
    return Decimal(inteiro.replace(".", "") + "." + fracao)


def _extrair_valor_brl(texto: str) -> Decimal | None:
    cursor = 0
    while True:
        inicio = texto.find(PREFIXO_VALOR, cursor)
        if inicio == -1:
            return None
        pos = inicio + len(PREFIXO_VALOR)
        while pos < len(texto) and texto[pos].isspace():
            pos += 1
        valor = _parse_valor_token(texto[pos:])
        if valor is not None:
            return valor
        cursor = pos


def classificar_consulta(texto_dialogo: str) -> ConsultaResult:
    texto = " ".join(texto_dialogo.split())
    if "não foi liberado para pagamento" in texto or "débito é inexistente" in texto:
        return ConsultaResult(status=STATUS_SEM_DEBITO)
    valor = _extrair_valor_brl(texto)
    if valor is not None:
        return ConsultaResult(status=STATUS_DEBITO, valor_pagar=valor)
    return ConsultaResult(status=STATUS_ERRO, detalhes=f"resultado_nao_reconhecido: {texto[:200]}")


def classificar_detalhes(texto: str) -> ConsultaResult:
    valor = _extrair_valor_brl(texto)
    if valor is None:
        return ConsultaResult(
            status=STATUS_ERRO,
            detalhes=f"resultado_nao_reconhecido: {' '.join(texto.split())[:200]}",
        )
    if valor == 0:
        return ConsultaResult(status=STATUS_SEM_DEBITO)
    return ConsultaResult(status=STATUS_DEBITO, valor_pagar=valor)


class PortalClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def consultar(self, page: Page, chave: str) -> ConsultaResult:
        logger.info("consulta_iniciada", chave=chave)
        await self._garantir_sem_dialogo(page)
        input_el = page.locator(
            f'input[placeholder="{self._settings.portal_input_placeholder}"]'
        )
        await input_el.fill(chave)
        await self._selecionar_filtro(page)
        await page.wait_for_timeout(self._settings.portal_filtro_espera_ms)
        await page.get_by_role("button", name=self._settings.portal_search_button).click()
        dialogo = page.locator(f"[role={self._settings.portal_dialog_role}]")
        total = page.get_by_text(self._settings.portal_total_recolher_text, exact=False)

        try:
            resultado = await self._aguardar_resultado(page, dialogo, total)
        finally:
            with suppress(Exception):
                await self._recarregar_busca(page)
        return resultado

    async def _aguardar_resultado(self, page: Page, dialogo, total) -> ConsultaResult:
        fim = (
            asyncio.get_running_loop().time()
            + self._settings.portal_result_timeout_ms / 1000
        )
        intervalo = self._settings.portal_filtro_espera_ms / 1000
        valor_anterior: Decimal | None = None
        while True:
            if await dialogo.count() and await dialogo.first.is_visible():
                texto_dialogo = await dialogo.inner_text()
                resultado = classificar_consulta(texto_dialogo)
                if resultado.valor_pagar is None:
                    logger.warning(
                        "dados_nao_extraidos",
                        status=resultado.status,
                        dialogo=" ".join(texto_dialogo.split())[:200],
                    )
                with suppress(Exception):
                    await self._fechar_dialogo_aberto(page)
                return resultado
            texto_total = await self._ler_texto_total(page, total)
            valor = _extrair_valor_brl(texto_total)
            if valor is not None and valor == valor_anterior:
                return classificar_detalhes(texto_total)
            valor_anterior = valor
            if asyncio.get_running_loop().time() >= fim:
                raise PortalIndisponivelError("portal sem resposta no tempo esperado")
            await asyncio.sleep(intervalo)

    async def _ler_texto_total(self, page: Page, total) -> str:
        celula = page.locator("td", has_text=self._settings.portal_total_recolher_text)
        if await celula.count():
            td_valor = celula.first.locator("xpath=following-sibling::td[1]")
            if await td_valor.count():
                try:
                    return (await td_valor.first.inner_text(timeout=1_000)).strip()
                except Exception:
                    pass
        try:
            texto = await total.first.inner_text(timeout=1_000)
        except Exception:
            return ""
        if texto.strip():
            return texto.strip()
        try:
            return (await total.first.locator("xpath=..").inner_text(timeout=1_000)).strip()
        except Exception:
            return ""

    async def _selecionar_filtro(self, page: Page) -> None:
        opcao = self._settings.portal_filtro_opcao_text
        seletor = self._settings.portal_filtro_debitos_select
        rotulo = self._settings.portal_filtro_debitos_label

        prime = await self._localizar_prime_select(page)
        if prime is not None and await self._selecionar_prime_select(page, prime, opcao):
            logger.info("filtro_selecionado", rotulo=rotulo, opcao=opcao)
            return

        select = page.locator(seletor)
        if await select.count() and await self._selecionar_em_select(select.first, opcao):
            logger.info("filtro_selecionado", seletor=seletor, opcao=opcao)
            return
        if await select.count() and await self._selecionar_prime_select(
            page, select.first, opcao
        ):
            logger.info("filtro_selecionado", seletor=seletor, opcao=opcao)
            return

        control = page.get_by_label(rotulo, exact=True)
        if await control.count() and await self._selecionar_em_select(
            control.first, opcao
        ):
            logger.info("filtro_selecionado", rotulo=rotulo, opcao=opcao)
            return

        rotulo_el = page.get_by_text(rotulo, exact=True)
        if await rotulo_el.count():
            selects = rotulo_el.first.locator("xpath=..").locator("select")
            if await selects.count() and await self._selecionar_em_select(
                selects.first, opcao
            ):
                logger.info("filtro_selecionado", rotulo=rotulo, opcao=opcao)
                return

        raise PortalIndisponivelError(f"filtro de débitos não encontrado: {rotulo}")

    async def _localizar_prime_select(self, page: Page) -> Locator | None:
        rotulo = self._settings.portal_filtro_debitos_label
        rotulo_el = page.get_by_text(rotulo, exact=True)
        if not await rotulo_el.count():
            return None
        selects = rotulo_el.first.locator(
            "xpath=(ancestor::*[.//p-select])[last()]//p-select"
        )
        if not await selects.count():
            return None
        return selects.first

    async def _selecionar_prime_select(
        self, page: Page, select: Locator, opcao: str
    ) -> bool:
        combobox = select.locator("[role=combobox]")
        if not await combobox.count():
            return False
        try:
            texto_atual = (await combobox.inner_text()).strip()
        except Exception:
            return False
        if texto_atual.upper() == opcao.upper():
            return True
        await select.click()
        opcoes = page.get_by_role("option", name=opcao, exact=True)
        await opcoes.first.click(timeout=self._settings.portal_result_timeout_ms)
        try:
            await expect(combobox).to_have_text(
                opcao, timeout=self._settings.portal_result_timeout_ms
            )
        except Exception as exc:
            raise PortalIndisponivelError(
                f"filtro de débitos não atualizado para {opcao}"
            ) from exc
        return True

    async def _selecionar_em_select(self, select, opcao: str) -> bool:
        opcoes = [
            opcao_texto.strip()
            for opcao_texto in await select.locator("option").all_inner_texts()
        ]
        if any(opcao_texto.upper() == opcao.upper() for opcao_texto in opcoes):
            await select.select_option(label=opcao)
            return True
        if opcoes:
            await select.select_option(index=len(opcoes) - 1)
            return True
        return False

    async def _recarregar_busca(self, page: Page) -> None:
        await page.goto(self._settings.portal_url, wait_until="load")

    async def _garantir_sem_dialogo(self, page: Page) -> None:
        dialog = page.locator(f"[role={self._settings.portal_dialog_role}]")
        if not (await dialog.count() and await dialog.first.is_visible()):
            return
        await self._fechar_dialogo_aberto(page)
        try:
            await dialog.first.wait_for(state="hidden", timeout=5_000)
        except PlaywrightTimeoutError as exc:
            raise PortalIndisponivelError("dialogo anterior nao foi fechado") from exc

    async def _fechar_dialogo_aberto(self, page: Page) -> None:
        dialog = page.locator(f"[role={self._settings.portal_dialog_role}]")
        if not (await dialog.count() and await dialog.first.is_visible()):
            return
        dismiss = page.locator(self._settings.portal_dismiss_button)
        await dismiss.first.click(force=True, timeout=5_000)
        with suppress(PlaywrightTimeoutError):
            await dialog.first.wait_for(state="hidden", timeout=5_000)