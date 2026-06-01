from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
import re
from typing import Any

import pandas as pd

from payment_analysis.reconciliation.base import SupplierReconciliationProvider
from payment_analysis.reconciliation.config import SupplierReconciliationSettings
from payment_analysis.reconciliation.models import SupplierReconciliationRecord

LOGGER = logging.getLogger(__name__)


class SportAtletReconciliationParseError(RuntimeError):
    pass


class SportAtletReconciliationProvider(SupplierReconciliationProvider):
    DOCUMENT_RE = re.compile(
        r"(?P<prefix>Реализация товаров и услуг|Возврат товаров от покупателя|Приходный кассовый ордер)\s+"
        r"(?P<number>SA\d+)\s+(?:от|від)\s+(?P<date>\d{2}\.\d{2}\.\d{4})(?:\s+(?P<time>\d{2}:\d{2}:\d{2}))?",
        re.IGNORECASE,
    )

    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        engine = "openpyxl" if file_path.suffix.lower() == ".xlsx" else "xlrd"
        sheet_name = "TDSheet"
        try:
            frame = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
        except ValueError as exc:
            if "Worksheet named 'TDSheet' not found" not in str(exc):
                raise SportAtletReconciliationParseError(f"Failed to read Sport-atlet reconciliation file {file_path}: {exc}") from exc
            sheet_name = 0
            try:
                frame = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
            except Exception as fallback_exc:  # noqa: BLE001
                raise SportAtletReconciliationParseError(f"Failed to read Sport-atlet reconciliation file {file_path}: {fallback_exc}") from fallback_exc
        except Exception as exc:  # noqa: BLE001
            raise SportAtletReconciliationParseError(f"Failed to read Sport-atlet reconciliation file {file_path}: {exc}") from exc

        header_row = self._find_header_row(frame)
        document_col = 0 if self._is_new_layout(frame, header_row) else 1
        opening_col = document_col + 1
        income_col = document_col + 2
        expense_col = document_col + 3
        closing_col = document_col + 4
        records: list[SupplierReconciliationRecord] = []
        opening_record: SupplierReconciliationRecord | None = None
        closing_record: SupplierReconciliationRecord | None = None

        for row_index in range(header_row + 1, len(frame)):
            row = frame.iloc[row_index]
            document_raw = self._string_or_none(row.iloc[document_col] if len(row) > document_col else None)
            opening_raw = self._to_decimal(row.iloc[opening_col] if len(row) > opening_col else None)
            income_raw = self._to_decimal(row.iloc[income_col] if len(row) > income_col else None)
            expense_raw = self._to_decimal(row.iloc[expense_col] if len(row) > expense_col else None)
            closing_raw = self._to_decimal(row.iloc[closing_col] if len(row) > closing_col else None)

            if not document_raw and all(value is None for value in (opening_raw, income_raw, expense_raw, closing_raw)):
                continue

            normalized_document = (document_raw or "").strip()
            if normalized_document.casefold() == "итог":
                continue

            if self._is_balance_owner_row(normalized_document):
                opening_record = self._build_balance_record(
                    file_path=file_path,
                    source_sheet=str(sheet_name),
                    period_key=period_key,
                    row_number=row_index + 1,
                    record_type="opening_balance",
                    document_raw=normalized_document,
                    raw_value=opening_raw,
                )
                closing_record = self._build_balance_record(
                    file_path=file_path,
                    source_sheet=str(sheet_name),
                    period_key=period_key,
                    row_number=row_index + 1,
                    record_type="closing_balance",
                    document_raw=normalized_document,
                    raw_value=closing_raw,
                )
                continue

            if self._is_service_row(normalized_document):
                continue

            parsed = self._parse_document(normalized_document)
            if parsed is None:
                records.append(
                    SupplierReconciliationRecord(
                        supplier_name=self._settings.supplier_name,
                        supplier_code=self._settings.supplier_code,
                        period_key=period_key,
                        source_file=str(file_path),
                        source_sheet=str(sheet_name),
                        row_number=row_index + 1,
                        accounting_date=None,
                        document_raw=normalized_document,
                        document_number=None,
                        document_datetime=None,
                        record_type="unknown",
                        debit_amount=None,
                        credit_amount=None,
                        amount=None,
                        raw_payload={
                            "opening_raw": self._string_or_none(row.iloc[opening_col] if len(row) > opening_col else None),
                            "income_raw": self._string_or_none(row.iloc[income_col] if len(row) > income_col else None),
                            "expense_raw": self._string_or_none(row.iloc[expense_col] if len(row) > expense_col else None),
                            "closing_raw": self._string_or_none(row.iloc[closing_col] if len(row) > closing_col else None),
                        },
                    )
                )
                continue

            record_type, document_number, document_datetime, accounting_date = parsed
            debit_amount: Decimal | None = None
            credit_amount: Decimal | None = None
            amount: Decimal | None = None

            if record_type == "sale":
                debit_amount = income_raw
                amount = income_raw
            elif record_type == "return":
                business_amount = abs(income_raw) if income_raw is not None else None
                credit_amount = business_amount
                amount = business_amount
            elif record_type == "payment":
                credit_amount = expense_raw
                amount = expense_raw

            records.append(
                SupplierReconciliationRecord(
                    supplier_name=self._settings.supplier_name,
                    supplier_code=self._settings.supplier_code,
                    period_key=period_key,
                    source_file=str(file_path),
                    source_sheet=str(sheet_name),
                    row_number=row_index + 1,
                    accounting_date=accounting_date,
                    document_raw=normalized_document,
                    document_number=document_number,
                    document_datetime=document_datetime,
                    record_type=record_type,
                    debit_amount=debit_amount,
                    credit_amount=credit_amount,
                    amount=amount,
                    raw_payload={
                        "opening_raw": self._string_or_none(row.iloc[opening_col] if len(row) > opening_col else None),
                        "income_raw": self._string_or_none(row.iloc[income_col] if len(row) > income_col else None),
                        "expense_raw": self._string_or_none(row.iloc[expense_col] if len(row) > expense_col else None),
                        "closing_raw": self._string_or_none(row.iloc[closing_col] if len(row) > closing_col else None),
                    },
                )
            )

        if opening_record is not None:
            records.insert(0, opening_record)
        if closing_record is not None:
            records.append(closing_record)

        LOGGER.info("Parsed %s Sport-atlet reconciliation rows from %s", len(records), file_path)
        return records

    def _find_header_row(self, frame: pd.DataFrame) -> int:
        for row_idx in range(min(len(frame), 30)):
            values = [(self._string_or_none(frame.iat[row_idx, col]) or "").strip().casefold() for col in range(frame.shape[1])]
            if len(values) >= 6 and values[1] == "договор контрагента, валюта взаиморасчетов" and values[2] == "нач. остаток" and values[3] == "приход" and values[4] == "расход" and values[5] == "кон. остаток":
                return row_idx
            if len(values) >= 5 and values[0] == "договор контрагента, валюта взаиморасчетов" and values[1] == "нач. остаток" and values[2] == "приход" and values[3] == "расход" and values[4] == "кон. остаток":
                return row_idx
        raise SportAtletReconciliationParseError("Sport-atlet reconciliation header row was not found.")

    def _is_new_layout(self, frame: pd.DataFrame, header_row: int) -> bool:
        first_cell = (self._string_or_none(frame.iat[header_row, 0]) or "").strip().casefold()
        return first_cell == "договор контрагента, валюта взаиморасчетов"

    def _is_balance_owner_row(self, document_raw: str) -> bool:
        normalized = document_raw.casefold()
        return normalized in {"фоп петренко і.а (дропшипінг)", "без договору, грн"}

    def _is_service_row(self, document_raw: str) -> bool:
        if not document_raw:
            return True
        normalized = document_raw.casefold()
        return normalized in {"документ движения (регистратор)", "контрагент", "итог"} or "відомість" in normalized

    def _build_balance_record(
        self,
        file_path: Path,
        source_sheet: str,
        period_key: str,
        row_number: int,
        record_type: str,
        document_raw: str,
        raw_value: Decimal | None,
    ) -> SupplierReconciliationRecord:
        amount = abs(raw_value) if raw_value is not None else None
        return SupplierReconciliationRecord(
            supplier_name=self._settings.supplier_name,
            supplier_code=self._settings.supplier_code,
            period_key=period_key,
            source_file=str(file_path),
            source_sheet=source_sheet,
            row_number=row_number,
            accounting_date=None,
            document_raw=document_raw,
            document_number=None,
            document_datetime=None,
            record_type=record_type,  # type: ignore[arg-type]
            debit_amount=None,
            credit_amount=amount,
            amount=amount,
            raw_payload={"raw_balance": str(raw_value) if raw_value is not None else None},
        )

    def _parse_document(self, document_raw: str) -> tuple[str, str, str | None, str | None] | None:
        match = self.DOCUMENT_RE.search(document_raw)
        if not match:
            return None
        prefix = match.group("prefix").casefold()
        document_number = match.group("number").upper()
        time_part = match.group("time") or "00:00:00"
        date_part = match.group("date")
        document_datetime = datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        accounting_date = document_datetime[:10]
        if prefix.startswith("реализация"):
            return "sale", document_number, document_datetime, accounting_date
        if prefix.startswith("возврат"):
            return "return", document_number, document_datetime, accounting_date
        if prefix.startswith("приходный кассовый ордер"):
            return "payment", document_number, document_datetime, accounting_date
        return None

    def _to_decimal(self, value: Any) -> Decimal | None:
        text = self._string_or_none(value)
        if text in (None, ""):
            return None
        normalized = text.replace(" ", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None
