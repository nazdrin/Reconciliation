from __future__ import annotations

from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from payment_analysis.reconciliation.base import SupplierReconciliationProvider
from payment_analysis.reconciliation.config import SupplierReconciliationSettings
from payment_analysis.reconciliation.models import SupplierReconciliationRecord

LOGGER = logging.getLogger(__name__)


class DobavkiUAReconciliationParseError(RuntimeError):
    pass


class DobavkiUAReconciliationProvider(SupplierReconciliationProvider):
    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        try:
            frame = pd.read_excel(file_path, engine="xlrd" if file_path.suffix.lower() == ".xls" else None)
        except Exception as exc:  # noqa: BLE001
            raise DobavkiUAReconciliationParseError(f"Failed to read Dobavki.ua reconciliation file {file_path}: {exc}") from exc

        required = {"№ замовлення", "Статус", "Коментар", "Разом", "Дата"}
        missing = required.difference(frame.columns.astype(str))
        if missing:
            raise DobavkiUAReconciliationParseError(f"Dobavki.ua required columns are missing: {sorted(missing)}")

        records: list[SupplierReconciliationRecord] = []
        sale_count = 0
        return_count = 0
        other_statuses: dict[str, int] = {}

        for idx, row in frame.fillna("").iterrows():
            status = str(row.get("Статус", "")).strip()
            tracking_number = self._normalize_tracking(row.get("Коментар"))
            amount = self._to_decimal(row.get("Разом"))
            accounting_date = self._normalize_date(str(row.get("Дата", "")).strip() or None)

            if status == "Виконано":
                record_type = "sale"
                sale_count += 1
            elif status == "Повернення":
                record_type = "return"
                return_count += 1
            else:
                other_statuses[status or "<empty>"] = other_statuses.get(status or "<empty>", 0) + 1
                continue

            records.append(
                SupplierReconciliationRecord(
                    supplier_name=self._settings.supplier_name,
                    supplier_code=self._settings.supplier_code,
                    period_key=period_key,
                    source_file=str(file_path),
                    source_sheet="Sheet1",
                    row_number=idx + 2,
                    accounting_date=accounting_date,
                    document_raw=str(row.get("Коментар", "")).strip(),
                    document_number=tracking_number,
                    document_datetime=str(row.get("Дата", "")).strip() or None,
                    record_type=record_type,
                    debit_amount=amount if record_type == "sale" else None,
                    credit_amount=amount if record_type == "return" else None,
                    amount=amount,
                    raw_payload={
                        "supplier_order_id": str(row.get("№ замовлення", "")).strip() or None,
                        "status": status,
                        "paid": str(row.get("Оплачено", "")).strip() or None,
                        "balance": str(row.get("Баланс", "")).strip() or None,
                        "manager": str(row.get("Менеджер", "")).strip() or None,
                    },
                )
            )

        LOGGER.info(
            "Parsed Dobavki.ua reconciliation file %s: sales=%s returns=%s ignored_statuses=%s total_records=%s",
            file_path,
            sale_count,
            return_count,
            other_statuses,
            len(records),
        )
        return records

    def _normalize_tracking(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        return text or None

    def _normalize_date(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return pd.to_datetime(value).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        text = str(value).strip().replace(" ", "").replace(",", ".")
        if text.endswith(".0") and text.count(".") == 1:
            text = text[:-2]
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
