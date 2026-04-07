from __future__ import annotations

from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from payment_analysis.reconciliation.base import SupplierReconciliationProvider
from payment_analysis.reconciliation.config import SupplierReconciliationSettings
from payment_analysis.reconciliation.models import ProteinPlusDepositSummary, SupplierReconciliationRecord

LOGGER = logging.getLogger(__name__)


class ProteinPlusReconciliationParseError(RuntimeError):
    pass


class ProteinPlusReconciliationProvider(SupplierReconciliationProvider):
    def __init__(self, settings: SupplierReconciliationSettings) -> None:
        self._settings = settings

    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        return self.parse_orders_file(file_path, period_key)

    def parse_deposit_file(
        self,
        file_path: Path,
        period_key: str,
        usd_to_uah_rate: Decimal | None = None,
    ) -> tuple[ProteinPlusDepositSummary, list[dict[str, Any]], list[SupplierReconciliationRecord]]:
        raw = pd.read_excel(file_path, sheet_name="TDSheet", header=None, engine="xlrd" if file_path.suffix.lower() == ".xls" else None)
        header_row = self._find_header_row(raw, {"Период", "Вид движения", "Сумма", "Назначение", "Номер заказа", "Комментарий/Контрагент", "Остаток"})
        frame = raw.iloc[header_row:].reset_index(drop=True)
        frame.columns = [str(value).strip() if value not in (None, "") else f"col_{idx}" for idx, value in enumerate(frame.iloc[0].tolist())]
        frame = frame.iloc[1:].reset_index(drop=True).fillna("")

        opening_balance = None
        closing_balance = None
        returns_total = Decimal("0")
        withdrawal_total = Decimal("0")
        return_rows: list[SupplierReconciliationRecord] = []
        deposit_rows: list[dict[str, Any]] = []

        for idx, row in frame.iterrows():
            purpose = str(row.get("Назначение", "")).strip()
            comment = str(row.get("Комментарий/Контрагент", "")).strip()
            amount = self._to_decimal(row.get("Сумма"))
            balance = self._to_decimal(row.get("Остаток"))
            order_number = str(row.get("Номер заказа", "")).strip() or None
            period = str(row.get("Период", "")).strip() or None

            if comment == (self._settings.deposit_opening_label or ""):
                opening_balance = balance
            if balance is not None:
                closing_balance = balance

            row_type = "other"
            if purpose in self._settings.deposit_return_labels:
                row_type = "return"
                returns_total += amount or Decimal("0")
                return_rows.append(
                    SupplierReconciliationRecord(
                        supplier_name=self._settings.supplier_name,
                        supplier_code=self._settings.supplier_code,
                        period_key=period_key,
                        source_file=str(file_path),
                        source_sheet="TDSheet",
                        row_number=idx + 2,
                        accounting_date=(period or "")[:10] if period else None,
                        document_raw=purpose,
                        document_number=order_number,
                        document_datetime=period,
                        record_type="return",
                        debit_amount=None,
                        credit_amount=amount,
                        amount=amount,
                        raw_payload={"comment": comment, "balance": str(balance) if balance is not None else None},
                    )
                )
            elif purpose in self._settings.deposit_withdrawal_labels:
                row_type = "withdrawal"
                withdrawal_total += amount or Decimal("0")
            elif comment == (self._settings.deposit_opening_label or ""):
                row_type = "opening_balance"

            deposit_rows.append(
                {
                    "period": period,
                    "movement_type": str(row.get("Вид движения", "")).strip() or None,
                    "amount_usd": amount,
                    "purpose": purpose or None,
                    "order_number": order_number,
                    "counterparty_comment": comment or None,
                    "balance_usd": balance,
                    "row_type": row_type,
                }
            )

        if opening_balance is None:
            raise ProteinPlusReconciliationParseError(f"Opening balance not found in deposit file {file_path}")
        if closing_balance is None:
            raise ProteinPlusReconciliationParseError(f"Closing balance not found in deposit file {file_path}")
        effective_rate = usd_to_uah_rate
        if effective_rate is None and self._settings.usd_to_uah_rate is not None:
            effective_rate = Decimal(str(self._settings.usd_to_uah_rate))
        if effective_rate is None:
            raise ProteinPlusReconciliationParseError("usd_to_uah_rate is required for ProteinPlus")

        summary = ProteinPlusDepositSummary(
            supplier_name=self._settings.supplier_name,
            supplier_code=self._settings.supplier_code,
            period_key=period_key,
            deposit_file=str(file_path),
            orders_file="",
            opening_deposit_usd=opening_balance,
            opening_deposit_uah=opening_balance * effective_rate,
            closing_deposit_usd=closing_balance,
            closing_deposit_uah=closing_balance * effective_rate,
            returns_total_usd=returns_total,
            returns_total_uah=returns_total * effective_rate,
            withdrawal_total_usd=withdrawal_total,
            withdrawal_total_uah=withdrawal_total * effective_rate,
            usd_to_uah_rate=effective_rate,
            returns_supplier_count=len(return_rows),
            returns_salesdrive_count=0,
            returns_count_delta=0,
            supplier_orders_count=0,
            supplier_orders_total=Decimal("0"),
            salesdrive_orders_count=0,
            salesdrive_orders_total=Decimal("0"),
            orders_total_delta=Decimal("0"),
            matched_orders_count=0,
            only_salesdrive_orders_count=0,
            only_supplier_orders_count=0,
            amount_mismatch_count=0,
            warnings_count=0,
            issues_count=0,
            raw_payload={"returns_rows": len(return_rows)},
        )
        LOGGER.info(
            "ProteinPlus deposit parsed: opening=%s closing=%s returns_rows=%s withdrawal_total=%s",
            opening_balance,
            closing_balance,
            len(return_rows),
            withdrawal_total,
        )
        return summary, deposit_rows, return_rows

    def parse_orders_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        raw = pd.read_excel(file_path, sheet_name="TDSheet", header=None, engine="xlrd" if file_path.suffix.lower() == ".xls" else None)
        header_row = self._find_header_row(raw, {"Номер замовлення", "Дата замовлення", "Номер ТТН", "Клієнт", "Дата надходження оплати", "Сума комісії", "Сума післяплати"})
        frame = raw.iloc[header_row:].reset_index(drop=True)
        frame.columns = [str(value).strip() if value not in (None, "") else f"col_{idx}" for idx, value in enumerate(frame.iloc[0].tolist())]
        frame = frame.iloc[1:].reset_index(drop=True).fillna("")

        records: list[SupplierReconciliationRecord] = []
        for idx, row in frame.iterrows():
            tracking_number = str(row.get("Номер ТТН", "")).strip() or None
            cod_amount = self._to_decimal(row.get("Сума післяплати"))
            order_date = str(row.get("Дата замовлення", "")).strip() or None
            payment_date = str(row.get("Дата надходження оплати", "")).strip() or None
            records.append(
                SupplierReconciliationRecord(
                    supplier_name=self._settings.supplier_name,
                    supplier_code=self._settings.supplier_code,
                    period_key=period_key,
                    source_file=str(file_path),
                    source_sheet="TDSheet",
                    row_number=idx + 2,
                    accounting_date=self._normalize_date(payment_date) or self._normalize_date(order_date),
                    document_raw=tracking_number or "",
                    document_number=tracking_number,
                    document_datetime=payment_date or order_date,
                    record_type="sale",
                    debit_amount=cod_amount,
                    credit_amount=None,
                    amount=cod_amount,
                    raw_payload={
                        "supplier_order_id": str(row.get("Номер замовлення", "")).strip() or None,
                        "customer_name": str(row.get("Клієнт", "")).strip() or None,
                        "payment_received_date": payment_date or None,
                        "commission_amount": str(row.get("Сума комісії", "")).strip() or None,
                    },
                )
            )
        LOGGER.info("ProteinPlus orders parsed: supplier_orders_rows=%s", len(records))
        return records

    def _find_header_row(self, frame: pd.DataFrame, required: set[str]) -> int:
        for row_idx in range(min(len(frame), 30)):
            values = {str(value).strip() for value in frame.iloc[row_idx].tolist() if value not in (None, "") and not pd.isna(value)}
            if required.issubset(values):
                return row_idx
        raise ProteinPlusReconciliationParseError(f"Header row not found. Required columns: {sorted(required)}")

    def _normalize_date(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        for pattern in ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
            try:
                return pd.to_datetime(text, format=pattern).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                continue
        try:
            return pd.to_datetime(text).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None

    def _to_decimal(self, value: Any) -> Decimal | None:
        text = str(value).strip() if value not in (None, "") else ""
        if not text:
            return None
        normalized = text.replace(" ", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None
