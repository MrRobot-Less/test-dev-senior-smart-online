from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )

    app_name: str = "smart-online-automation"
    app_env: str = "development"
    debug: bool = False

    portal_url: str = (
        "https://portal-sitram.sefaz.ce.gov.br/sitram-internet/"
        "#/pagamento-icms/por-nota-fiscal/fiscal"
    )
    portal_input_placeholder: str = "Insira aqui uma chave de acesso (NF-e)"
    portal_search_button: str = "Pesquisar"
    portal_dialog_role: str = "dialog"
    portal_dismiss_button: str = ".modal-confirm .button-text"
    portal_total_recolher_text: str = "Total a Recolher"
    portal_filtro_debitos_label: str = "Débitos"
    portal_filtro_debitos_select: str = "#pn_id_7"
    portal_filtro_opcao_text: str = "TODOS"
    portal_filtro_espera_ms: int = 500
    portal_result_timeout_ms: int = 45_000

    browser: str = "chromium"
    headless: bool = True
    slow_mo: int = 0
    navigation_timeout_ms: int = 30_000

    retry_max_attempts: int = 3
    retry_wait_seconds: float = 2.0

    db_retry_max_attempts: int = 3
    db_retry_wait_seconds: float = 1.0

    database_url: str = "postgresql+asyncpg://automation:automation@localhost:5433/automation"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()