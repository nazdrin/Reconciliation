from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from pathlib import Path

from pypdf import PdfReader

from payment_analysis.reconciliation.base import SupplierReconciliationProvider
from payment_analysis.reconciliation.config import SupplierReconciliationSettings
from payment_analysis.reconciliation.models import SupplierReconciliationRecord


class MonsterLabReconciliationParseError(RuntimeError):
    pass


class MonsterLabReconciliationProvider(SupplierReconciliationProvider):
    ENTRY_RE = re.compile(
        r"^(?P<date>\d{2}\.\d{2}\.\d{2})\s+"
        r"(?P<operation>Продажа|Платеж по продаже)\s+"
        r"(?P<doc>(?:ЗН|ZN)\d+)\s+"
        r"(?P<debit>-?[\d\s]+,\d{2})\s+"
        r"(?P<credit>-?[\d\s]+,\d{2})$"
    )
    MONEY_RE = re.compile(r"-?[\d\s]+,\d{2}")

    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        reader = PdfReader(str(file_path))
        page_texts = [(page.extract_text() or "") for page in reader.pages]
        full_text = "\n".join(page_texts)
        records: list[SupplierReconciliationRecord] = []

        opening_balance = self._extract_opening_balance(full_text)
        if opening_balance is not None:
            records.append(
                SupplierReconciliationRecord(
                    supplier_name=self._settings.supplier_name,
                    supplier_code=self._settings.supplier_code,
                    period_key=period_key,
                    source_file=str(file_path),
                    source_sheet=None,
                    row_number=1,
                    accounting_date=None,
                    document_raw="Сальдо начальное",
                    document_number=None,
                    document_datetime=None,
                    record_type="opening_balance",
                    debit_amount=None,
                    credit_amount=opening_balance,
                    amount=opening_balance,
                    raw_payload={"source": "pdf", "balance_type": "opening"},
                )
            )

        row_number = 2
        for text in page_texts:
            for raw_line in text.splitlines():
                line = " ".join(raw_line.split())
                if not line:
                    continue
                match = self.ENTRY_RE.match(line)
                if not match:
                    continue
                accounting_date = datetime.strptime(match.group("date"), "%d.%m.%y").strftime("%Y-%m-%d")
                operation = match.group("operation")
                document_number = match.group("doc").upper()
                debit_amount = self._to_decimal(match.group("debit"))
                credit_amount = self._to_decimal(match.group("credit"))
                record_type = "sale" if operation == "Продажа" else "payment"
                amount = debit_amount if record_type == "sale" else credit_amount
                records.append(
                    SupplierReconciliationRecord(
                        supplier_name=self._settings.supplier_name,
                        supplier_code=self._settings.supplier_code,
                        period_key=period_key,
                        source_file=str(file_path),
                        source_sheet=None,
                        row_number=row_number,
                        accounting_date=accounting_date,
                        document_raw=operation,
                        document_number=document_number,
                        document_datetime=None,
                        record_type=record_type,
                        debit_amount=debit_amount,
                        credit_amount=credit_amount,
                        amount=amount,
                        raw_payload={"line": line},
                    )
                )
                row_number += 1

        closing_balance = self._extract_closing_balance(full_text)
        if closing_balance is not None:
            records.append(
                SupplierReconciliationRecord(
                    supplier_name=self._settings.supplier_name,
                    supplier_code=self._settings.supplier_code,
                    period_key=period_key,
                    source_file=str(file_path),
                    source_sheet=None,
                    row_number=row_number + 1,
                    accounting_date=None,
                    document_raw="Конечное сальдо",
                    document_number=None,
                    document_datetime=None,
                    record_type="closing_balance",
                    debit_amount=None,
                    credit_amount=closing_balance,
                    amount=closing_balance,
                    raw_payload={"source": "pdf", "balance_type": "closing"},
                )
            )

        if not records:
            raise MonsterLabReconciliationParseError(f"Failed to parse MonsterLab reconciliation file {file_path}")
        return records

    def _extract_opening_balance(self, full_text: str) -> Decimal | None:
        match = re.search(r"Сальдо начальное:.*?(\d[\d\s]*,\d{2})", full_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return self._to_decimal(match.group(1))

    def _extract_closing_balance(self, full_text: str) -> Decimal | None:
        idx = full_text.lower().rfind("конечное сальдо")
        tail = full_text[idx:] if idx != -1 else full_text
        amounts = self.MONEY_RE.findall(tail)
        if not amounts:
            return None
        return self._to_decimal(amounts[-1])

    def _to_decimal(self, value: str) -> Decimal | None:
        normalized = value.replace(" ", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None
