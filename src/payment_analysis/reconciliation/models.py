from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal

ReconciliationRecordType = Literal["payment", "sale", "return", "opening_balance", "closing_balance", "service", "unknown"]
ReconciliationType = Literal["payments", "orders", "returns"]
MatchStatus = Literal[
    "matched",
    "only_salesdrive",
    "only_supplier",
    "ambiguous",
    "error",
    "warning",
    "mismatch_amount",
    "mismatch_date",
    "duplicate_numberSup",
    "missing_numberSup",
]


@dataclass(slots=True)
class SupplierReconciliationRecord:
    supplier_name: str
    supplier_code: str
    period_key: str
    source_file: str
    source_sheet: str | None
    row_number: int
    accounting_date: str | None
    document_raw: str
    document_number: str | None
    document_datetime: str | None
    record_type: ReconciliationRecordType
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    amount: Decimal | None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ("debit_amount", "credit_amount", "amount"):
            value = row.get(key)
            row[key] = str(value) if value is not None else None
        row["raw_payload"] = str(self.raw_payload)
        return row


@dataclass(slots=True)
class SalesDriveOrderRecord:
    order_id: str | None
    supplier_code: str | None
    number_sup: str | None
    tracking_number: str | None
    expenses_amount: Decimal | None
    status_id: int | None
    status_name: str | None
    order_time: str | None
    updated_at: str | None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["expenses_amount"] = str(self.expenses_amount) if self.expenses_amount is not None else None
        row["raw_payload"] = str(self.raw_payload)
        return row


@dataclass(slots=True)
class ReconciliationMatchResult:
    supplier_name: str
    period_key: str
    reconciliation_type: ReconciliationType
    match_status: MatchStatus
    salesdrive_ref: str | None
    supplier_ref: str | None
    match_key: str | None
    salesdrive_date: str | None
    supplier_date: str | None
    salesdrive_amount: Decimal | None
    supplier_amount: Decimal | None
    notes: str | None = None
    warning_code: str | None = None
    warning_message: str | None = None
    salesdrive_status_id: int | None = None
    salesdrive_status_name: str | None = None
    salesdrive_order_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ("salesdrive_amount", "supplier_amount"):
            value = row.get(key)
            row[key] = str(value) if value is not None else None
        return row


@dataclass(slots=True)
class ProteinPlusDepositSummary:
    supplier_name: str
    supplier_code: str
    period_key: str
    deposit_file: str
    orders_file: str
    opening_deposit_usd: Decimal
    opening_deposit_uah: Decimal
    closing_deposit_usd: Decimal
    closing_deposit_uah: Decimal
    returns_total_usd: Decimal
    returns_total_uah: Decimal
    withdrawal_total_usd: Decimal
    withdrawal_total_uah: Decimal
    usd_to_uah_rate: Decimal
    returns_supplier_count: int
    returns_salesdrive_count: int
    returns_count_delta: int
    supplier_orders_count: int
    supplier_orders_total: Decimal
    salesdrive_orders_count: int
    salesdrive_orders_total: Decimal
    orders_total_delta: Decimal
    matched_orders_count: int
    only_salesdrive_orders_count: int
    only_supplier_orders_count: int
    amount_mismatch_count: int
    warnings_count: int
    issues_count: int
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {"metric_code": "supplier_name", "metric_name": "Поставщик", "value": self.supplier_name},
            {"metric_code": "period_key", "metric_name": "Период сверки", "value": self.period_key},
            {"metric_code": "deposit_file", "metric_name": "Депозитный файл", "value": self.deposit_file},
            {"metric_code": "orders_file", "metric_name": "Файл заказов", "value": self.orders_file},
            {"metric_code": "usd_to_uah_rate", "metric_name": "Курс USD -> UAH", "value": self.usd_to_uah_rate},
            {"metric_code": "opening_deposit_usd", "metric_name": "Начальный депозит USD", "value": self.opening_deposit_usd},
            {"metric_code": "opening_deposit_uah", "metric_name": "Начальный депозит UAH", "value": self.opening_deposit_uah},
            {"metric_code": "closing_deposit_usd", "metric_name": "Конечный депозит USD", "value": self.closing_deposit_usd},
            {"metric_code": "closing_deposit_uah", "metric_name": "Конечный депозит UAH", "value": self.closing_deposit_uah},
            {"metric_code": "returns_total_usd", "metric_name": "Возвраты USD", "value": self.returns_total_usd},
            {"metric_code": "returns_total_uah", "metric_name": "Возвраты UAH", "value": self.returns_total_uah},
            {"metric_code": "returns_supplier_count", "metric_name": "Возвраты в файле поставщика", "value": self.returns_supplier_count},
            {"metric_code": "returns_salesdrive_count", "metric_name": "Возвраты в SalesDrive", "value": self.returns_salesdrive_count},
            {"metric_code": "returns_count_delta", "metric_name": "Дельта по количеству возвратов", "value": self.returns_count_delta},
            {"metric_code": "withdrawal_total_usd", "metric_name": "Вывод с депозита USD", "value": self.withdrawal_total_usd},
            {"metric_code": "withdrawal_total_uah", "metric_name": "Вывод с депозита UAH", "value": self.withdrawal_total_uah},
            {"metric_code": "supplier_orders_count", "metric_name": "Заказы в файле поставщика", "value": self.supplier_orders_count},
            {"metric_code": "supplier_orders_total", "metric_name": "Сумма заказов в файле поставщика", "value": self.supplier_orders_total},
            {"metric_code": "salesdrive_orders_count", "metric_name": "Заказы в SalesDrive", "value": self.salesdrive_orders_count},
            {"metric_code": "salesdrive_orders_total", "metric_name": "Сумма заказов в SalesDrive", "value": self.salesdrive_orders_total},
            {"metric_code": "orders_total_delta", "metric_name": "Дельта по общей сумме заказов", "value": self.orders_total_delta},
            {"metric_code": "matched_orders_count", "metric_name": "Сопоставленные заказы", "value": self.matched_orders_count},
            {"metric_code": "only_salesdrive_orders_count", "metric_name": "Заказы только SalesDrive", "value": self.only_salesdrive_orders_count},
            {"metric_code": "only_supplier_orders_count", "metric_name": "Заказы только supplier file", "value": self.only_supplier_orders_count},
            {"metric_code": "amount_mismatch_count", "metric_name": "Расхождения по сумме", "value": self.amount_mismatch_count},
            {"metric_code": "warnings_count", "metric_name": "Количество предупреждений", "value": self.warnings_count},
            {"metric_code": "issues_count", "metric_name": "Количество проблем", "value": self.issues_count},
        ]


@dataclass(slots=True)
class SupplierReconciliationSummary:
    supplier_name: str
    period_key: str
    source_file: str
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    payments_in_salesdrive: int
    payments_amount_in_salesdrive: Decimal
    payments_in_reconciliation: int
    payments_amount_in_reconciliation: Decimal
    matched_payments: int
    only_salesdrive_payments: int
    only_supplier_payments: int
    ambiguous_payments: int
    sales_in_reconciliation: int
    orders_in_salesdrive: int
    sales_amount_in_reconciliation: Decimal
    orders_amount_in_salesdrive: Decimal
    orders_amount_delta: Decimal
    matched_orders: int
    amount_mismatches: int
    missing_orders: int
    returns_in_reconciliation: int
    returns_amount_in_reconciliation: Decimal
    returns_in_salesdrive: int
    returns_amount_in_salesdrive: Decimal
    returns_amount_delta: Decimal
    returns_linked_to_orders: int
    returns_unresolved: int
    warnings_count: int
    issues_count: int

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {"metric": "supplier_name", "value": self.supplier_name},
            {"metric": "period_key", "value": self.period_key},
            {"metric": "source_file", "value": self.source_file},
            {"metric": "opening_balance", "value": self.opening_balance},
            {"metric": "closing_balance", "value": self.closing_balance},
            {"metric": "payments_in_salesdrive", "value": self.payments_in_salesdrive},
            {"metric": "payments_amount_in_salesdrive", "value": self.payments_amount_in_salesdrive},
            {"metric": "payments_in_reconciliation", "value": self.payments_in_reconciliation},
            {"metric": "payments_amount_in_reconciliation", "value": self.payments_amount_in_reconciliation},
            {"metric": "matched_payments", "value": self.matched_payments},
            {"metric": "only_salesdrive_payments", "value": self.only_salesdrive_payments},
            {"metric": "only_supplier_payments", "value": self.only_supplier_payments},
            {"metric": "ambiguous_payments", "value": self.ambiguous_payments},
            {"metric": "sales_in_reconciliation", "value": self.sales_in_reconciliation},
            {"metric": "orders_in_salesdrive", "value": self.orders_in_salesdrive},
            {"metric": "matched_orders", "value": self.matched_orders},
            {"metric": "amount_mismatches", "value": self.amount_mismatches},
            {"metric": "missing_orders", "value": self.missing_orders},
            {"metric": "returns_in_reconciliation", "value": self.returns_in_reconciliation},
            {"metric": "returns_linked_to_orders", "value": self.returns_linked_to_orders},
            {"metric": "returns_unresolved", "value": self.returns_unresolved},
            {"metric": "warnings_count", "value": self.warnings_count},
            {"metric": "issues_count", "value": self.issues_count},
        ]


@dataclass(slots=True)
class SupplierPaymentReconciliationSnapshot:
    supplier_name: str
    period_key: str
    source_file: str
    salesdrive_payments_count: int
    salesdrive_total_amount: Decimal
    reconciliation_payments_count: int
    reconciliation_total_amount: Decimal
    amount_difference: Decimal
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    matched_count: int
    matched_amount: Decimal
    only_salesdrive_count: int
    only_supplier_count: int
    ambiguous_count: int
    mismatch_count: int
    matched_rows: list[dict[str, Any]] = field(default_factory=list)
    only_salesdrive_rows: list[dict[str, Any]] = field(default_factory=list)
    only_supplier_rows: list[dict[str, Any]] = field(default_factory=list)
    ambiguous_rows: list[dict[str, Any]] = field(default_factory=list)
    mismatch_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_summary_row(self) -> dict[str, Any]:
        return {
            "supplier_name": self.supplier_name,
            "payments_count": self.salesdrive_payments_count,
            "total_amount": self.salesdrive_total_amount,
            "reconciliation_payments_count": self.reconciliation_payments_count,
            "reconciliation_total_amount": self.reconciliation_total_amount,
            "amount_difference": self.amount_difference,
            "opening_balance": self.opening_balance,
            "closing_balance": self.closing_balance,
            "matched_count": self.matched_count,
            "only_salesdrive_count": self.only_salesdrive_count,
            "only_supplier_count": self.only_supplier_count,
            "ambiguous_count": self.ambiguous_count,
            "mismatch_count": self.mismatch_count,
        }

    def to_sheet_summary_rows(self) -> list[dict[str, Any]]:
        return [
            {"metric_code": "supplier_name", "metric_name": "Поставщик", "value": self.supplier_name},
            {"metric_code": "period_key", "metric_name": "Период", "value": self.period_key},
            {"metric_code": "source_file", "metric_name": "Файл сверки", "value": self.source_file},
            {"metric_code": "salesdrive_payments_count", "metric_name": "Оплаты в SalesDrive", "value": self.salesdrive_payments_count},
            {"metric_code": "salesdrive_total_amount", "metric_name": "Сумма оплат в SalesDrive", "value": self.salesdrive_total_amount},
            {
                "metric_code": "reconciliation_payments_count",
                "metric_name": "Оплаты в акте сверки",
                "value": self.reconciliation_payments_count,
            },
            {
                "metric_code": "reconciliation_total_amount",
                "metric_name": "Сумма оплат в акте сверки",
                "value": self.reconciliation_total_amount,
            },
            {"metric_code": "amount_difference", "metric_name": "Разница сумм", "value": self.amount_difference},
            {"metric_code": "opening_balance", "metric_name": "Начальный остаток депозита", "value": self.opening_balance},
            {"metric_code": "closing_balance", "metric_name": "Конечный остаток депозита", "value": self.closing_balance},
            {"metric_code": "matched_count", "metric_name": "Совпавшие оплаты", "value": self.matched_count},
            {"metric_code": "only_salesdrive_count", "metric_name": "Только в SalesDrive", "value": self.only_salesdrive_count},
            {"metric_code": "only_supplier_count", "metric_name": "Только в акте сверки", "value": self.only_supplier_count},
            {"metric_code": "ambiguous_count", "metric_name": "Неоднозначные оплаты", "value": self.ambiguous_count},
            {"metric_code": "mismatch_count", "metric_name": "Проблемные совпадения", "value": self.mismatch_count},
        ]
