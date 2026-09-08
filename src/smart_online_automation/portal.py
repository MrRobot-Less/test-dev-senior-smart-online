import asyncio
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal

from playwright.async_api import Locator, Page, expect
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from smart_online_automation.config import Settings
from smart_online_automation.logging_config import get_logger
from smart_online_automation.models import STATUS_DEBIT, STATUS_ERROR, STATUS_NO_DEBIT

VALUE_PREFIX = "R$"

logger = get_logger("portal")


class PortalUnavailableError(RuntimeError):
    pass


@dataclass
class QueryResult:
    status: str
    valor_pagar: Decimal | None = None
    detalhes: str | None = None
    attempts: int = 1


def _is_valid_integer(integer: str) -> bool:
    if not integer or not all(c.isdigit() or c == "." for c in integer):
        return False
    if integer.startswith(".") or integer.endswith("."):
        return False
    if "." not in integer:
        return True
    partes = integer.split(".")
    return len(partes[0]) <= 3 and all(len(parte) == 3 and parte.isdigit() for parte in partes[1:])


def _parse_value_token(snippet: str) -> Decimal | None:
    deadline = 0
    while deadline < len(snippet) and (snippet[deadline].isdigit() or snippet[deadline] in ".,"):
        deadline += 1
    token = snippet[:deadline]
    if "," not in token:
        return None
    integer, fracao = token.rsplit(",", 1)
    if len(fracao) != 2 or not fracao.isdigit() or not _is_valid_integer(integer):
        return None
    return Decimal(integer.replace(".", "") + "." + fracao)


def _extract_brl_value(text: str) -> Decimal | None:
    cursor = 0
    while True:
        inicio = text.find(VALUE_PREFIX, cursor)
        if inicio == -1:
            return None
        pos = inicio + len(VALUE_PREFIX)
        while pos < len(text) and text[pos].isspace():
            pos += 1
        value = _parse_value_token(text[pos:])
        if value is not None:
            return value
        cursor = pos


def classify_dialog(dialog_text: str) -> QueryResult:
    text = " ".join(dialog_text.split())
    if "não foi liberado para pagamento" in text or "débito é inexistente" in text:
        return QueryResult(status=STATUS_NO_DEBIT)
    value = _extract_brl_value(text)
    if value is not None:
        return QueryResult(status=STATUS_DEBIT, valor_pagar=value)
    return QueryResult(status=STATUS_ERROR, detalhes=f"resultado_nao_reconhecido: {text[:200]}")


def classify_details(text: str) -> QueryResult:
    value = _extract_brl_value(text)
    if value is None:
        return QueryResult(
            status=STATUS_ERROR,
            detalhes=f"resultado_nao_reconhecido: {' '.join(text.split())[:200]}",
        )
    if value == 0:
        return QueryResult(status=STATUS_NO_DEBIT)
    return QueryResult(status=STATUS_DEBIT, valor_pagar=value)


class PortalClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def query(self, page: Page, key: str) -> QueryResult:
        logger.info("consulta_iniciada", key=key)
        await self._ensure_no_dialog(page)
        input_el = page.locator(
            f'input[placeholder="{self._settings.portal_input_placeholder}"]'
        )
        await input_el.fill(key)
        await self._select_filter(page)
        await page.wait_for_timeout(self._settings.portal_filtro_espera_ms)
        await page.get_by_role("button", name=self._settings.portal_search_button).click()
        dialog = page.locator(f"[role={self._settings.portal_dialog_role}]")
        total = page.get_by_text(self._settings.portal_total_recolher_text, exact=False)

        try:
            result = await self._wait_for_result(page, dialog, total)
        finally:
            with suppress(Exception):
                await self._reload_search(page)
        return result

    async def _wait_for_result(self, page: Page, dialog, total) -> QueryResult:
        deadline = (
            asyncio.get_running_loop().time()
            + self._settings.portal_result_timeout_ms / 1000
        )
        interval = self._settings.portal_filtro_espera_ms / 1000
        previous_value: Decimal | None = None
        while True:
            if await dialog.count() and await dialog.first.is_visible():
                dialog_text = await dialog.inner_text()
                result = classify_dialog(dialog_text)
                if result.valor_pagar is None:
                    logger.warning(
                        "dados_nao_extraidos",
                        status=result.status,
                        dialog=" ".join(dialog_text.split())[:200],
                    )
                with suppress(Exception):
                    await self._close_open_dialog(page)
                return result
            total_text = await self._read_total_text(page, total)
            value = _extract_brl_value(total_text)
            if value is not None and value == previous_value:
                return classify_details(total_text)
            previous_value = value
            if asyncio.get_running_loop().time() >= deadline:
                raise PortalUnavailableError("portal sem resposta no tempo esperado")
            await asyncio.sleep(interval)

    async def _read_total_text(self, page: Page, total) -> str:
        cell = page.locator("td", has_text=self._settings.portal_total_recolher_text)
        if await cell.count():
            value_cell = cell.first.locator("xpath=following-sibling::td[1]")
            if await value_cell.count():
                try:
                    return (await value_cell.first.inner_text(timeout=1_000)).strip()
                except Exception:
                    pass
        try:
            text = await total.first.inner_text(timeout=1_000)
        except Exception:
            return ""
        if text.strip():
            return text.strip()
        try:
            return (await total.first.locator("xpath=..").inner_text(timeout=1_000)).strip()
        except Exception:
            return ""

    async def _select_filter(self, page: Page) -> None:
        option = self._settings.portal_filtro_opcao_text
        selector = self._settings.portal_filtro_debitos_select
        label = self._settings.portal_filtro_debitos_label

        prime = await self._locate_prime_select(page)
        if prime is not None and await self._select_prime_select(page, prime, option):
            logger.info("filtro_selecionado", label=label, option=option)
            return

        select = page.locator(selector)
        if await select.count() and await self._select_option(select.first, option):
            logger.info("filtro_selecionado", selector=selector, option=option)
            return
        if await select.count() and await self._select_prime_select(
            page, select.first, option
        ):
            logger.info("filtro_selecionado", selector=selector, option=option)
            return

        control = page.get_by_label(label, exact=True)
        if await control.count() and await self._select_option(
            control.first, option
        ):
            logger.info("filtro_selecionado", label=label, option=option)
            return

        label_el = page.get_by_text(label, exact=True)
        if await label_el.count():
            selects = label_el.first.locator("xpath=..").locator("select")
            if await selects.count() and await self._select_option(
                selects.first, option
            ):
                logger.info("filtro_selecionado", label=label, option=option)
                return

        raise PortalUnavailableError(f"filtro de débitos não encontrado: {label}")

    async def _locate_prime_select(self, page: Page) -> Locator | None:
        label = self._settings.portal_filtro_debitos_label
        label_el = page.get_by_text(label, exact=True)
        if not await label_el.count():
            return None
        selects = label_el.first.locator(
            "xpath=(ancestor::*[.//p-select])[last()]//p-select"
        )
        if not await selects.count():
            return None
        return selects.first

    async def _select_prime_select(
        self, page: Page, select: Locator, option: str
    ) -> bool:
        combobox = select.locator("[role=combobox]")
        if not await combobox.count():
            return False
        try:
            current_text = (await combobox.inner_text()).strip()
        except Exception:
            return False
        if current_text.upper() == option.upper():
            return True
        await select.click()
        options = page.get_by_role("option", name=option, exact=True)
        await options.first.click(timeout=self._settings.portal_result_timeout_ms)
        try:
            await expect(combobox).to_have_text(
                option, timeout=self._settings.portal_result_timeout_ms
            )
        except Exception as exc:
            raise PortalUnavailableError(
                f"filtro de débitos não atualizado para {option}"
            ) from exc
        return True

    async def _select_option(self, select, option: str) -> bool:
        options = [
            option_text.strip()
            for option_text in await select.locator("option").all_inner_texts()
        ]
        if any(option_text.upper() == option.upper() for option_text in options):
            await select.select_option(label=option)
            return True
        if options:
            await select.select_option(index=len(options) - 1)
            return True
        return False

    async def _reload_search(self, page: Page) -> None:
        await page.goto(self._settings.portal_url, wait_until="load")

    async def _ensure_no_dialog(self, page: Page) -> None:
        dialog = page.locator(f"[role={self._settings.portal_dialog_role}]")
        if not (await dialog.count() and await dialog.first.is_visible()):
            return
        await self._close_open_dialog(page)
        try:
            await dialog.first.wait_for(state="hidden", timeout=5_000)
        except PlaywrightTimeoutError as exc:
            raise PortalUnavailableError("dialog anterior nao foi fechado") from exc

    async def _close_open_dialog(self, page: Page) -> None:
        dialog = page.locator(f"[role={self._settings.portal_dialog_role}]")
        if not (await dialog.count() and await dialog.first.is_visible()):
            return
        dismiss = page.locator(self._settings.portal_dismiss_button)
        await dismiss.first.click(force=True, timeout=5_000)
        with suppress(PlaywrightTimeoutError):
            await dialog.first.wait_for(state="hidden", timeout=5_000)