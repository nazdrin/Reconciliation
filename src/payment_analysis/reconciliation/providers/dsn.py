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


class DSNReconciliationParseError(RuntimeError):
    pass


class DSNReconciliationProvider(SupplierReconciliationProvider):
    DOCUMENT_RE = re.compile(r"\((?P<date>\d{2}\.\d{2}\.\d{2}),\s*№\s*(?P<number>\d+)\)", re.IGNORECASE)

    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        try:
            workbook = pd.read_excel(file_path, sheet_name=None, header=None, engine=self._resolve_engine(file_path))
        except Exception as exc:  # noqa: BLE001
            raise DSNReconciliationParseError(f"Failed to read DSN reconciliation file {file_path}: {exc}") from exc

        records: list[SupplierReconciliationRecord] = []
        balance_seen = 0
        for sheet_name, frame in workbook.items():
            header_row = self._find_header_row(frame)
            for row_idx in range(header_row + 1, len(frame)):
                row = frame.iloc[row_idx]
                record = self._parse_row(
                    row=row,
                    row_number=row_idx + 1,
                    source_file=file_path,
                    source_sheet=sheet_name,
                    period_key=period_key,
                )
                if record is not None:
                    if record.record_type in {"opening_balance", "closing_balance"}:
                        balance_seen += 1
                        record.record_type = "opening_balance" if balance_seen == 1 else "closing_balance"
                    records.append(record)

        opening = len([r for r in records if r.record_type == "opening_balance"])
        closing = len([r for r in records if r.record_type == "closing_balance"])
        sales = len([r for r in records if r.record_type == "sale"])
        returns = len([r for r in records if r.record_type == "return"])
        payments = len([r for r in records if r.record_type == "payment"])
        LOGGER.info(
            "Parsed DSN reconciliation rows from %s: opening=%s closing=%s sales=%s returns=%s payments=%s total=%s",
            file_path,
            opening,
            closing,
            sales,
            returns,
            payments,
            len(records),
        )
        return records

    def _resolve_engine(self, file_path: Path) -> str | None:
        if file_path.suffix.lower() == ".xls":
            return "xlrd"
        return None

    def _find_header_row(self, frame: pd.DataFrame) -> int:
        for row_idx in range(min(len(frame), 30)):
            values = [(self._string_or_none(frame.iat[row_idx, col]) or "").strip().casefold() for col in range(frame.shape[1])]
            if len(values) >= 5 and values[2] == "назва документа" and values[3] == "дебет" and values[4] == "кредит":
                return row_idx
        raise DSNReconciliationParseError("DSN reconciliation header row was not found or required columns are missing.")

    def _parse_row(
        self,
        row: pd.Series,
        row_number: int,
        source_file: Path,
        source_sheet: str,
        period_key: str,
    ) -> SupplierReconciliationRecord | None:
        document_raw = self._string_or_none(row.iloc[2] if len(row) > 2 else None)
        debit_raw = row.iloc[3] if len(row) > 3 else None
        credit_raw = row.iloc[4] if len(row) > 4 else None

        if document_raw is None and self._to_decimal(debit_raw) is None and self._to_decimal(credit_raw) is None:
            return None

        normalized_document = (document_raw or "").strip()
        if not normalized_document:
            return None
        if normalized_document.casefold() in {"обороти за період"}:
            return None

        debit_amount = self._to_decimal(debit_raw)
        credit_amount = self._to_decimal(credit_raw)

        record_type = self._classify_record_type(normalized_document)
        document_number = self._extract_document_number(normalized_document)
        document_datetime = self._extract_document_datetime(normalized_document)
        accounting_date = document_datetime[:10] if document_datetime else self._extract_document_date(normalized_document)

        amount: Decimal | None = None
        if record_type == "sale":
            amount = debit_amount
        elif record_type in {"return", "payment"}:
            amount = credit_amount
        elif record_type in {"opening_balance", "closing_balance"}:
            amount = abs(credit_amount) if credit_amount is not None else abs(debit_amount) if debit_amount is not None else None

        return SupplierReconciliationRecord(
            supplier_name=self._settings.supplier_name,
            supplier_code=self._settings.supplier_code,
            period_key=period_key,
            source_file=str(source_file),
            source_sheet=source_sheet,
            row_number=row_number,
            accounting_date=accounting_date if record_type not in {"opening_balance", "closing_balance"} else None,
            document_raw=normalized_document,
            document_number=document_number,
            document_datetime=document_datetime,
            record_type=record_type,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            amount=amount,
            raw_payload={
                "document_number_raw": document_number,
                "document_number_normalized": self._strip_leading_zeros(document_number),
                "debit_raw": self._string_or_none(debit_raw),
                "credit_raw": self._string_or_none(credit_raw),
            },
        )

    def _classify_record_type(self, document_raw: str) -> str:
        if any(document_raw.startswith(prefix) for prefix in self._settings.payment_doc_prefixes):
            return "payment"
        if any(document_raw.startswith(prefix) for prefix in self._settings.sale_doc_prefixes):
            return "sale"
        if any(document_raw.startswith(prefix) for prefix in self._settings.return_doc_prefixes):
            return "return"
        if any(document_raw.startswith(prefix) for prefix in self._settings.opening_balance_prefixes):
            return "opening_balance"
        if any(document_raw.startswith(prefix) for prefix in self._settings.closing_balance_prefixes):
            return "closing_balance"
        return "unknown"

    def _extract_document_number(self, document_raw: str) -> str | None:
        match = self.DOCUMENT_RE.search(document_raw)
        if not match:
            return None
        return match.group("number").strip()

    def _extract_document_date(self, document_raw: str) -> str | None:
        match = self.DOCUMENT_RE.search(document_raw)
        if not match:
            balance_match = re.search(r"Сальдо на (\d{2}\.\d{2}\.\d{2})", document_raw, re.IGNORECASE)
            if not balance_match:
                return None
            text = balance_match.group(1)
        else:
            text = match.group("date")
        try:
            return datetime.strptime(text, "%d.%m.%y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _extract_document_datetime(self, document_raw: str) -> str | None:
        match = self.DOCUMENT_RE.search(document_raw)
        if not match:
            return None
        try:
            return datetime.strptime(match.group("date"), "%d.%m.%y").strftime("%Y-%m-%d 00:00:00")
        except ValueError:
            return None

    def _strip_leading_zeros(self, value: str | None) -> str | None:
        if not value:
            return None
        stripped = value.lstrip("0")
        return stripped or "0"

    def _to_decimal(self, value: Any) -> Decimal | None:
        text = self._string_or_none(value)
        if text in (None, "", " "):
            return None
        normalized = text.replace(" ", "").replace("\xa0", "").replace(",", ".")
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
