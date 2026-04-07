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


class BiotusReconciliationParseError(RuntimeError):
    pass


class BiotusReconciliationProvider(SupplierReconciliationProvider):
    REQUIRED_HEADERS = {"date": "дата", "document": "документ", "debit": "дебет", "credit": "кредит"}
    DOC_NUMBER_RE = re.compile(r"\b(BI-\d+)\b", re.IGNORECASE)
    DOC_DATETIME_RE = re.compile(r"від\s+(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}:\d{2}))?", re.IGNORECASE)
    CLOSING_BALANCE_RE = re.compile(r"заборгованість.*?([\d\s]+,\d{2})\s*грн", re.IGNORECASE)

    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        try:
            workbook = pd.read_excel(file_path, sheet_name=None, header=None, engine=self._resolve_engine(file_path))
        except Exception as exc:  # noqa: BLE001
            raise BiotusReconciliationParseError(f"Failed to read reconciliation file {file_path}: {exc}") from exc

        records: list[SupplierReconciliationRecord] = []
        for sheet_name, frame in workbook.items():
            header_row, column_map = self._find_header_row(frame)
            data_frame = frame.iloc[header_row + 1 :].reset_index(drop=True)
            for row_offset, row in data_frame.iterrows():
                record = self._parse_row(
                    row=row,
                    column_map=column_map,
                    row_number=header_row + 2 + row_offset,
                    source_file=file_path,
                    source_sheet=sheet_name,
                    period_key=period_key,
                )
                if record is not None:
                    records.append(record)
            closing_balance = self._extract_closing_balance(frame)
            if closing_balance is not None and not any(record.record_type == "closing_balance" for record in records):
                records.append(
                    SupplierReconciliationRecord(
                        supplier_name=self._settings.supplier_name,
                        supplier_code=self._settings.supplier_code,
                        period_key=period_key,
                        source_file=str(file_path),
                        source_sheet=sheet_name,
                        row_number=len(frame) + 1,
                        accounting_date=None,
                        document_raw="Сальдо кінцеве",
                        document_number=None,
                        document_datetime=None,
                        record_type="closing_balance",
                        debit_amount=None,
                        credit_amount=closing_balance,
                        amount=closing_balance,
                        raw_payload={"source": "footer"},
                    )
                )

        LOGGER.info("Parsed %s reconciliation rows from %s", len(records), file_path)
        return records

    def _resolve_engine(self, file_path: Path) -> str | None:
        if file_path.suffix.lower() == ".xls":
            return "xlrd"
        return None

    def _find_header_row(self, frame: pd.DataFrame) -> tuple[int, dict[str, int]]:
        for row_idx in range(min(len(frame), 50)):
            normalized = {col_idx: self._normalize_cell(frame.iat[row_idx, col_idx]) for col_idx in range(frame.shape[1])}
            column_map: dict[str, int] = {}
            for logical_name, expected in self.REQUIRED_HEADERS.items():
                for col_idx, value in normalized.items():
                    if value == expected:
                        column_map[logical_name] = col_idx
                        break
            if len(column_map) == len(self.REQUIRED_HEADERS):
                return row_idx, column_map
        raise BiotusReconciliationParseError("Biotus reconciliation header row was not found or required columns are missing.")

    def _parse_row(
        self,
        row: pd.Series,
        column_map: dict[str, int],
        row_number: int,
        source_file: Path,
        source_sheet: str,
        period_key: str,
    ) -> SupplierReconciliationRecord | None:
        date_raw = row.iloc[column_map["date"]] if len(row) > column_map["date"] else None
        document_raw = self._string_or_none(row.iloc[column_map["document"]] if len(row) > column_map["document"] else None)
        debit_raw = row.iloc[column_map["debit"]] if len(row) > column_map["debit"] else None
        credit_raw = row.iloc[column_map["credit"]] if len(row) > column_map["credit"] else None

        if document_raw is None and self._is_empty_amounts(debit_raw, credit_raw) and self._string_or_none(date_raw) is None:
            return None

        accounting_date = self._parse_date(date_raw)
        debit_amount = self._to_decimal(debit_raw)
        credit_amount = self._to_decimal(credit_raw)
        document_number = self._extract_document_number(document_raw)
        document_datetime = self._extract_document_datetime(document_raw)
        record_type = self._classify_record_type(document_raw)
        date_text = (self._string_or_none(date_raw) or "").casefold()
        if record_type == "service" and "сальдо початкове" in date_text:
            record_type = "opening_balance"
        if record_type == "service" and "сальдо кінцеве" in date_text:
            record_type = "closing_balance"
        amount = self._resolve_amount(record_type, debit_amount, credit_amount)

        return SupplierReconciliationRecord(
            supplier_name=self._settings.supplier_name,
            supplier_code=self._settings.supplier_code,
            period_key=period_key,
            source_file=str(source_file),
            source_sheet=source_sheet,
            row_number=row_number,
            accounting_date=accounting_date,
            document_raw=document_raw or "",
            document_number=document_number,
            document_datetime=document_datetime,
            record_type=record_type,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            amount=amount,
            raw_payload={
                "date": self._string_or_none(date_raw),
                "document": document_raw,
                "debit": self._string_or_none(debit_raw),
                "credit": self._string_or_none(credit_raw),
            },
        )

    def _classify_record_type(self, document_raw: str | None) -> str:
        normalized = (document_raw or "").strip()
        if not normalized:
            return "service"
        if any(normalized.startswith(prefix) for prefix in self._settings.payment_doc_prefixes):
            return "payment"
        if any(normalized.startswith(prefix) for prefix in self._settings.sale_doc_prefixes):
            return "sale"
        if any(normalized.startswith(prefix) for prefix in self._settings.return_doc_prefixes):
            return "return"
        lowered = normalized.casefold()
        if "сальдо" in lowered:
            return "opening_balance"
        if "оборот" in lowered or "разом" in lowered:
            return "service"
        return "unknown"

    def _resolve_amount(self, record_type: str, debit_amount: Decimal | None, credit_amount: Decimal | None) -> Decimal | None:
        if record_type == "payment":
            return credit_amount
        if record_type == "sale":
            return debit_amount
        if record_type == "return":
            return credit_amount
        if record_type in {"opening_balance", "closing_balance"}:
            return credit_amount or debit_amount
        return None

    def _extract_document_number(self, document_raw: str | None) -> str | None:
        if not document_raw:
            return None
        match = self.DOC_NUMBER_RE.search(document_raw)
        return match.group(1).upper() if match else None

    def _extract_document_datetime(self, document_raw: str | None) -> str | None:
        if not document_raw:
            return None
        match = self.DOC_DATETIME_RE.search(document_raw)
        if not match:
            return None
        date_part = match.group(1)
        time_part = match.group(2) or "00:00:00"
        try:
            return datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _parse_date(self, value: Any) -> str | None:
        if value in (None, "") or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        text = self._string_or_none(value)
        if not text:
            return None
        if any(marker in text.casefold() for marker in ("сальдо", "оборот", "разом")):
            return None
        for pattern in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _to_decimal(self, value: Any) -> Decimal | None:
        text = self._string_or_none(value)
        if text in (None, ""):
            return None
        normalized = text.replace(" ", "").replace("\xa0", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    def _normalize_cell(self, value: Any) -> str:
        return (self._string_or_none(value) or "").strip().casefold()

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _is_empty_amounts(self, debit_raw: Any, credit_raw: Any) -> bool:
        return self._to_decimal(debit_raw) is None and self._to_decimal(credit_raw) is None

    def _extract_closing_balance(self, frame: pd.DataFrame) -> Decimal | None:
        text_parts: list[str] = []
        for row_idx in range(len(frame)):
            row_values = [self._string_or_none(frame.iat[row_idx, col_idx]) for col_idx in range(frame.shape[1])]
            text_parts.append(" ".join(value for value in row_values if value))
        text = "\n".join(text_parts)
        match = self.CLOSING_BALANCE_RE.search(text)
        if not match:
            return None
        return self._to_decimal(match.group(1))
