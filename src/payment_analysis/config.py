from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    salesdrive_base_url: str
    salesdrive_api_key: str
    salesdrive_order_api_key: str
    salesdrive_timeout_seconds: int = 30
    salesdrive_page_limit: int = 100
    salesdrive_rate_limit_retry_seconds: int = 65
    salesdrive_rate_limit_max_retries: int = 2
    debug_dir: Path = Path("debug")
    reports_dir: Path = Path("reports")
    docs_dir: Path = Path("docs")
    incoming_rules_path: Path = Path("config/incoming_rules.yaml")
    analysis_settings_path: Path = Path("config/analysis_settings.yaml")
    internal_transfer_rules_path: Path = Path("config/internal_transfer_rules.yaml")
    supplier_reconciliation_config_path: Path = Path("config/supplier_reconciliation.yaml")
    supplier_mapping_path: Path = Path("data/mappings/counterparty_to_supplier.yaml")
    supplier_mapping_excel_path: Path = Path("data/mappings/counterparty_supplier_mapping.xlsx")

    @property
    def payment_api_analysis_path(self) -> Path:
        return self.docs_dir / "payment_api_analysis.md"

    @property
    def order_api_analysis_path(self) -> Path:
        return self.docs_dir / "order_api_analysis.md"


def load_settings() -> Settings:
    load_dotenv()

    base_url = os.getenv("SALESDRIVE_BASE_URL", "").strip()
    api_key = os.getenv("SALESDRIVE_API_KEY", "").strip()
    order_api_key = os.getenv("SALESDRIVE_ORDER_API_KEY", "").strip()

    if not base_url:
        raise ValueError("Environment variable SALESDRIVE_BASE_URL is required.")
    if not api_key:
        raise ValueError("Environment variable SALESDRIVE_API_KEY is required.")
    if not order_api_key:
        raise ValueError("Environment variable SALESDRIVE_ORDER_API_KEY is required.")

    timeout_seconds = int(os.getenv("SALESDRIVE_TIMEOUT_SECONDS", "30"))
    page_limit = min(int(os.getenv("SALESDRIVE_PAGE_LIMIT", "100")), 100)

    settings = Settings(
        salesdrive_base_url=base_url.rstrip("/"),
        salesdrive_api_key=api_key,
        salesdrive_order_api_key=order_api_key,
        salesdrive_timeout_seconds=timeout_seconds,
        salesdrive_page_limit=page_limit,
        salesdrive_rate_limit_retry_seconds=int(os.getenv("SALESDRIVE_RATE_LIMIT_RETRY_SECONDS", "65")),
        salesdrive_rate_limit_max_retries=int(os.getenv("SALESDRIVE_RATE_LIMIT_MAX_RETRIES", "2")),
    )

    settings.debug_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    return settings
