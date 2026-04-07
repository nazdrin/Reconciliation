from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class SupplierReconciliationSettings:
    supplier_name: str
    supplier_code: str
    supplier_aliases: list[str]
    reconciliation_folder: Path
    file_pattern_type: str
    payment_doc_prefixes: list[str]
    sale_doc_prefixes: list[str]
    return_doc_prefixes: list[str]
    payment_match_date_tolerance_days: int
    payment_match_datetime_tolerance_hours: int
    order_fetch_lookback_days: int
    order_fetch_lookforward_days: int
    order_match_date_tolerance_days: int
    order_match_amount_tolerance: float
    order_match_strategy: str
    allowed_sale_status_ids: list[int]
    balance_sign_mode: str | None
    sale_amount_column: str | None
    return_amount_column: str | None
    payment_amount_column: str | None
    return_amount_abs: bool
    opening_balance_prefixes: list[str]
    closing_balance_prefixes: list[str]
    strip_leading_zeros_for_fallback: bool
    deposit_file_patterns: list[str]
    orders_file_patterns: list[str]
    usd_to_uah_rate: float | None
    deposit_opening_label: str | None
    deposit_return_labels: list[str]
    deposit_withdrawal_labels: list[str]
    order_match_field: str
    order_amount_field: str


@dataclass(slots=True)
class ReconciliationConfig:
    suppliers: dict[str, SupplierReconciliationSettings]
    status_mapping: dict[int, str]

    @classmethod
    def from_yaml(cls, path: Path) -> "ReconciliationConfig":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        suppliers_payload = payload.get("suppliers", {})
        suppliers: dict[str, SupplierReconciliationSettings] = {}
        for supplier_name, supplier_payload in suppliers_payload.items():
            suppliers[supplier_name] = SupplierReconciliationSettings(
                supplier_name=supplier_name,
                supplier_code=str(supplier_payload.get("supplier_code")),
                supplier_aliases=[str(alias) for alias in supplier_payload.get("supplier_aliases", [])],
                reconciliation_folder=Path(str(supplier_payload.get("reconciliation_folder", ""))),
                file_pattern_type=str(supplier_payload.get("file_pattern_type", "MMYYYY")),
                payment_doc_prefixes=[str(value) for value in supplier_payload.get("payment_doc_prefixes", [])],
                sale_doc_prefixes=[str(value) for value in supplier_payload.get("sale_doc_prefixes", [])],
                return_doc_prefixes=[str(value) for value in supplier_payload.get("return_doc_prefixes", [])],
                payment_match_date_tolerance_days=int(supplier_payload.get("payment_match_date_tolerance_days", 1)),
                payment_match_datetime_tolerance_hours=int(supplier_payload.get("payment_match_datetime_tolerance_hours", 24)),
                order_fetch_lookback_days=int(supplier_payload.get("order_fetch_lookback_days", 12)),
                order_fetch_lookforward_days=int(supplier_payload.get("order_fetch_lookforward_days", 1)),
                order_match_date_tolerance_days=int(supplier_payload.get("order_match_date_tolerance_days", 3)),
                order_match_amount_tolerance=float(supplier_payload.get("order_match_amount_tolerance", 1)),
                order_match_strategy=str(supplier_payload.get("order_match_strategy", "document_then_amount_date")),
                allowed_sale_status_ids=[int(value) for value in supplier_payload.get("allowed_sale_status_ids", [])],
                balance_sign_mode=str(supplier_payload.get("balance_sign_mode")) if supplier_payload.get("balance_sign_mode") is not None else None,
                sale_amount_column=str(supplier_payload.get("sale_amount_column")) if supplier_payload.get("sale_amount_column") is not None else None,
                return_amount_column=str(supplier_payload.get("return_amount_column")) if supplier_payload.get("return_amount_column") is not None else None,
                payment_amount_column=str(supplier_payload.get("payment_amount_column")) if supplier_payload.get("payment_amount_column") is not None else None,
                return_amount_abs=bool(supplier_payload.get("return_amount_abs", False)),
                opening_balance_prefixes=[str(value) for value in supplier_payload.get("opening_balance_prefixes", [])],
                closing_balance_prefixes=[str(value) for value in supplier_payload.get("closing_balance_prefixes", [])],
                strip_leading_zeros_for_fallback=bool(supplier_payload.get("strip_leading_zeros_for_fallback", False)),
                deposit_file_patterns=[str(value) for value in supplier_payload.get("deposit_file_patterns", [])],
                orders_file_patterns=[str(value) for value in supplier_payload.get("orders_file_patterns", [])],
                usd_to_uah_rate=float(supplier_payload.get("usd_to_uah_rate")) if supplier_payload.get("usd_to_uah_rate") is not None else None,
                deposit_opening_label=str(supplier_payload.get("deposit_opening_label")) if supplier_payload.get("deposit_opening_label") is not None else None,
                deposit_return_labels=[str(value) for value in supplier_payload.get("deposit_return_labels", [])],
                deposit_withdrawal_labels=[str(value) for value in supplier_payload.get("deposit_withdrawal_labels", [])],
                order_match_field=str(supplier_payload.get("order_match_field", "number_sup")),
                order_amount_field=str(supplier_payload.get("order_amount_field", "expensesAmount")),
            )
        status_mapping = {int(key): str(value) for key, value in (payload.get("status_mapping", {}) or {}).items()}
        return cls(suppliers=suppliers, status_mapping=status_mapping)

    def get_supplier(self, supplier_name: str) -> SupplierReconciliationSettings:
        key = supplier_name.casefold()
        for name, settings in self.suppliers.items():
            if name.casefold() == key:
                return settings
        raise KeyError(f"Supplier {supplier_name!r} is not configured for reconciliation.")
