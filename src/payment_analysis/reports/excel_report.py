from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re
from typing import Any

import pandas as pd

from payment_analysis.models.payments import PaymentRecord
from payment_analysis.reconciliation.matchers import OrderMatchArtifacts, PaymentMatchArtifacts
from payment_analysis.reconciliation.models import (
    ProteinPlusDepositSummary,
    ReconciliationMatchResult,
    SupplierPaymentReconciliationSnapshot,
    SupplierReconciliationSummary,
)


class ExcelReportBuilder:
    HEADER_LABELS = {
        "metric": "metric_code / код",
        "metric_name_ru": "metric_name_ru / показатель",
        "count": "count / количество",
        "amount": "amount / сумма",
        "period": "period / период",
        "value": "value / значение",
        "payment_id": "payment_id / ID платежа",
        "payment_type": "payment_type / тип",
        "payment_date": "payment_date / дата",
        "amount_value": "amount / сумма",
        "currency": "currency / валюта",
        "counterparty_name": "counterparty_name / контрагент",
        "counterparty_tax_id": "counterparty_tax_id / ЕГРПОУ контрагента",
        "comment": "comment / комментарий",
        "purpose": "purpose / назначение",
        "organization_name": "organization_name / организация",
        "organization_tax_id": "organization_tax_id / ЕГРПОУ организации",
        "account_reference": "account_reference / счет",
        "raw_status": "raw_status / статус",
        "supplier_name": "supplier_name / поставщик",
        "incoming_category": "incoming_category / категория",
        "is_internal_transfer": "is_internal_transfer / внутреннее перемещение",
        "internal_transfer_pair_id": "internal_transfer_pair_id / ID пары",
        "internal_transfer_reason": "internal_transfer_reason / причина",
        "mapping_source": "mapping_source / источник мапинга",
        "source_system": "source_system / источник",
        "raw_payload": "raw_payload / сырой payload",
        "payments_count": "payments_count / количество платежей",
        "total_amount": "total_amount / общая сумма",
        "pair_id": "pair_id / ID пары",
        "outcoming_payment_id": "outcoming_payment_id / ID исходящего",
        "outcoming_date": "outcoming_date / дата исходящего",
        "outcoming_account": "outcoming_account / счет исходящего",
        "incoming_payment_id": "incoming_payment_id / ID входящего",
        "incoming_date": "incoming_date / дата входящего",
        "incoming_account": "incoming_account / счет входящего",
        "reason": "reason / причина",
        "occurrences": "occurrences / вхождений",
        "example_comment": "example_comment / пример назначения",
        "payment_day": "payment_day / день",
        "metric_code": "metric_code / код",
        "metric_name": "metric_name / показатель",
        "salesdrive_ref": "salesdrive_ref / SalesDrive ссылка",
        "supplier_ref": "supplier_ref / строка сверки",
        "match_key": "match_key / ключ сверки",
        "salesdrive_date": "salesdrive_date / дата SalesDrive",
        "supplier_date": "supplier_date / дата акта",
        "salesdrive_amount": "salesdrive_amount / сумма SalesDrive",
        "supplier_amount": "supplier_amount / сумма акта",
        "notes": "notes / примечание",
        "warning_code": "warning_code / код предупреждения",
        "warning_message": "warning_message / текст предупреждения",
        "salesdrive_status_id": "salesdrive_status_id / statusId",
        "salesdrive_status_name": "salesdrive_status_name / статус",
        "salesdrive_order_id": "salesdrive_order_id / ID заказа",
        "issue_type": "issue_type / тип проблемы",
        "message": "message / сообщение",
        "reconciliation_payments_count": "reconciliation_payments_count / оплат в сверке",
        "reconciliation_total_amount": "reconciliation_total_amount / сумма в сверке",
        "payments_amount_in_salesdrive": "payments_amount_in_salesdrive / сумма оплат SalesDrive",
        "payments_amount_in_reconciliation": "payments_amount_in_reconciliation / сумма оплат акта",
        "amount_difference": "amount_difference / разница",
        "matched_count": "matched_count / совпало",
        "only_salesdrive_count": "only_salesdrive_count / только SalesDrive",
        "only_supplier_count": "only_supplier_count / только сверка",
        "ambiguous_count": "ambiguous_count / неоднозначно",
        "mismatch_count": "mismatch_count / проблемные",
        "opening_balance": "opening_balance / начальный остаток",
        "closing_balance": "closing_balance / конечный остаток",
        "deposit_file": "deposit_file / депозитный файл",
        "orders_file": "orders_file / файл заказов",
        "usd_to_uah_rate": "usd_to_uah_rate / курс USD-UAH",
        "opening_deposit_usd": "opening_deposit_usd / начальный депозит USD",
        "opening_deposit_uah": "opening_deposit_uah / начальный депозит UAH",
        "closing_deposit_usd": "closing_deposit_usd / конечный депозит USD",
        "closing_deposit_uah": "closing_deposit_uah / конечный депозит UAH",
        "returns_total_usd": "returns_total_usd / возвраты USD",
        "returns_total_uah": "returns_total_uah / возвраты UAH",
        "withdrawal_total_usd": "withdrawal_total_usd / вывод USD",
        "withdrawal_total_uah": "withdrawal_total_uah / вывод UAH",
        "supplier_orders_count": "supplier_orders_count / заказов supplier file",
        "matched_orders_count": "matched_orders_count / совпавших заказов",
        "only_salesdrive_orders_count": "only_salesdrive_orders_count / только SalesDrive",
        "only_supplier_orders_count": "only_supplier_orders_count / только supplier file",
        "amount_mismatch_count": "amount_mismatch_count / расхождений по сумме",
        "movement_type": "movement_type / вид движения",
        "amount_usd": "amount_usd / сумма USD",
        "purpose": "purpose / назначение",
        "order_number": "order_number / номер заказа",
        "counterparty_comment": "counterparty_comment / комментарий/контрагент",
        "balance_usd": "balance_usd / остаток USD",
        "row_type": "row_type / тип строки",
    }

    SHEET_NAMES = {
        "summary": "summary_Сводка",
        "receipts_all": "receipts_Все",
        "receipts_customer": "receipts_Клиенты",
        "receipts_excluded": "receipts_Искл",
        "incoming_all": "incoming_Все",
        "incoming_internal": "incoming_Внутр",
        "outcoming_all": "outgoing_Все",
        "out_external": "outgoing_Внешн",
        "out_internal": "outgoing_Внутр",
        "internal_pairs": "internal_Пары",
        "out_by_counterparty": "out_Контрагенты",
        "out_by_supplier": "out_Поставщики",
        "unmapped": "unmapped_НеНайдено",
        "errors": "errors_Ошибки",
    }

    SUMMARY_LABELS = {
        "period": "Период отчета",
        "incoming_total": "Входящие всего",
        "incoming_internal_transfers": "Входящие внутренние перемещения",
        "incoming_receipts_excluding_internal": "Поступления без внутренних перемещений",
        "incoming_customer_receipts": "Поступления от клиентов",
        "incoming_excluded_receipts": "Исключенные поступления",
        "outcoming_total": "Исходящие всего",
        "outcoming_internal_transfers": "Исходящие внутренние перемещения",
        "outcoming_external": "Исходящие внешние",
        "outcoming_mapped_to_suppliers": "Исходящие, сопоставленные с поставщиками",
        "outcoming_unmapped": "Исходящие без сопоставления",
    }

    def build(
        self,
        output_path: Path,
        incoming: list[PaymentRecord],
        outcoming: list[PaymentRecord],
        internal_transfer_pairs: list[dict[str, Any]],
        grouped_by_counterparty: list[dict[str, Any]],
        grouped_by_supplier: list[dict[str, Any]],
        unmapped_counterparties: list[dict[str, Any]],
        errors: list[dict[str, str]],
        period_label: str,
        supplier_payment_reconciliations: list[SupplierPaymentReconciliationSnapshot] | None = None,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        supplier_payment_reconciliations = supplier_payment_reconciliations or []

        incoming_all_rows = [self._report_row(payment) for payment in incoming]
        outcoming_all_rows = [self._report_row(payment) for payment in outcoming]

        receipts_all = [row for row in incoming_all_rows if row["incoming_category"] != "internal_transfer"]
        incoming_customer = [row for row in incoming_all_rows if row["incoming_category"] == "customer_receipt"]
        incoming_excluded = [row for row in incoming_all_rows if row["incoming_category"] == "excluded_receipt"]
        incoming_internal = [row for row in incoming_all_rows if row["incoming_category"] == "internal_transfer"]
        outcoming_external = [row for row in outcoming_all_rows if not row["is_internal_transfer"]]
        outcoming_internal = [row for row in outcoming_all_rows if row["is_internal_transfer"]]
        mapped_external = [payment for payment in outcoming if payment.supplier_name and not payment.is_internal_transfer]

        summary_rows = [
            {"metric": "period", "metric_name_ru": self.SUMMARY_LABELS["period"], "count": None, "amount": None, "value": period_label},
            {"metric": "incoming_total", "metric_name_ru": self.SUMMARY_LABELS["incoming_total"], "count": len(incoming), "amount": self._sum_amount(incoming)},
            {
                "metric": "incoming_internal_transfers",
                "metric_name_ru": self.SUMMARY_LABELS["incoming_internal_transfers"],
                "count": len(incoming_internal),
                "amount": self._sum_amount_rows(incoming_internal),
            },
            {
                "metric": "incoming_receipts_excluding_internal",
                "metric_name_ru": self.SUMMARY_LABELS["incoming_receipts_excluding_internal"],
                "count": len(receipts_all),
                "amount": self._sum_amount_rows(receipts_all),
            },
            {
                "metric": "incoming_customer_receipts",
                "metric_name_ru": self.SUMMARY_LABELS["incoming_customer_receipts"],
                "count": len(incoming_customer),
                "amount": self._sum_amount_rows(incoming_customer),
            },
            {
                "metric": "incoming_excluded_receipts",
                "metric_name_ru": self.SUMMARY_LABELS["incoming_excluded_receipts"],
                "count": len(incoming_excluded),
                "amount": self._sum_amount_rows(incoming_excluded),
            },
            {"metric": "outcoming_total", "metric_name_ru": self.SUMMARY_LABELS["outcoming_total"], "count": len(outcoming), "amount": self._sum_amount(outcoming)},
            {
                "metric": "outcoming_internal_transfers",
                "metric_name_ru": self.SUMMARY_LABELS["outcoming_internal_transfers"],
                "count": len(outcoming_internal),
                "amount": self._sum_amount_rows(outcoming_internal),
            },
            {
                "metric": "outcoming_external",
                "metric_name_ru": self.SUMMARY_LABELS["outcoming_external"],
                "count": len(outcoming_external),
                "amount": self._sum_amount_rows(outcoming_external),
            },
            {
                "metric": "outcoming_mapped_to_suppliers",
                "metric_name_ru": self.SUMMARY_LABELS["outcoming_mapped_to_suppliers"],
                "count": len(mapped_external),
                "amount": self._sum_amount(mapped_external),
            },
            {
                "metric": "outcoming_unmapped",
                "metric_name_ru": self.SUMMARY_LABELS["outcoming_unmapped"],
                "count": len([row for row in outcoming_external if not row["supplier_name"]]),
                "amount": self._sum_amount_rows([row for row in outcoming_external if not row["supplier_name"]]),
            },
        ]

        used_sheet_names: set[str] = set()
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summary_sheet = self._make_sheet_name(self.SHEET_NAMES["summary"], used_sheet_names)
            start = self._write_df(writer, summary_sheet, summary_rows, 0)
            start += 2
            supplier_summary_rows = [
                {
                    "supplier_name": row.get("supplier_name"),
                    "payments_count": row.get("payments_count"),
                    "total_amount": row.get("total_amount"),
                    "reconciliation_payments_count": row.get("reconciliation_payments_count"),
                    "reconciliation_total_amount": row.get("reconciliation_total_amount"),
                    "amount_difference": row.get("amount_difference"),
                    "opening_balance": row.get("opening_balance"),
                    "closing_balance": row.get("closing_balance"),
                    "matched_count": row.get("matched_count"),
                    "only_salesdrive_count": row.get("only_salesdrive_count"),
                    "only_supplier_count": row.get("only_supplier_count"),
                    "ambiguous_count": row.get("ambiguous_count"),
                    "mismatch_count": row.get("mismatch_count"),
                }
                for row in grouped_by_supplier
            ]
            self._write_df(writer, summary_sheet, supplier_summary_rows, start)
            self._write_table(writer, self.SHEET_NAMES["receipts_all"], receipts_all, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["receipts_customer"], incoming_customer, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["receipts_excluded"], incoming_excluded, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["incoming_all"], incoming_all_rows, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["incoming_internal"], incoming_internal, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["outcoming_all"], outcoming_all_rows, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["out_external"], outcoming_external, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["out_internal"], outcoming_internal, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["internal_pairs"], internal_transfer_pairs, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["out_by_counterparty"], grouped_by_counterparty, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["out_by_supplier"], grouped_by_supplier, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["unmapped"], unmapped_counterparties, used_sheet_names)
            self._write_table(writer, self.SHEET_NAMES["errors"], errors, used_sheet_names)
            self._write_supplier_detail_sheets(
                writer,
                [payment for payment in outcoming if payment.supplier_name and not payment.is_internal_transfer],
                used_sheet_names,
                supplier_payment_reconciliations,
            )

    def build_supplier_reconciliation(
        self,
        output_path: Path,
        supplier_name: str,
        summary: SupplierReconciliationSummary,
        payment_matches: PaymentMatchArtifacts,
        order_matches: OrderMatchArtifacts,
        return_matches: list[ReconciliationMatchResult],
        warning_rows: list[dict[str, Any]],
        issue_rows: list[dict[str, Any]],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        base = supplier_name.capitalize()
        sheet_names = {
            "summary": f"{base}_Сводка",
            "orders_match": f"{base}_Заказы_Совпали",
            "orders_only_sd": f"{base}_Заказы_SalesDrive",
            "orders_only_reconciliation": f"{base}_Заказы_Акт",
            "returns": f"{base}_Возвраты",
            "warnings": f"{base}_Предупреждения",
            "issues": f"{base}_Проблемы",
        }
        used_sheet_names: set[str] = set()
        summary_rows = [
            {"metric_code": "supplier_name", "metric_name": "Поставщик", "value": summary.supplier_name},
            {"metric_code": "period_key", "metric_name": "Период сверки", "value": summary.period_key},
            {"metric_code": "source_file", "metric_name": "Файл сверки", "value": summary.source_file},
            {"metric_code": "opening_balance", "metric_name": "Начальный остаток депозита", "value": summary.opening_balance},
            {"metric_code": "closing_balance", "metric_name": "Конечный остаток депозита", "value": summary.closing_balance},
            {"metric_code": "payments_in_salesdrive", "metric_name": "Оплаты в SalesDrive", "value": summary.payments_in_salesdrive},
            {"metric_code": "payments_amount_in_salesdrive", "metric_name": "Сумма оплат в SalesDrive", "value": summary.payments_amount_in_salesdrive},
            {"metric_code": "payments_in_reconciliation", "metric_name": "Оплаты в акте", "value": summary.payments_in_reconciliation},
            {"metric_code": "payments_amount_in_reconciliation", "metric_name": "Сумма оплат в акте", "value": summary.payments_amount_in_reconciliation},
            {"metric_code": "matched_payments", "metric_name": "Сопоставленные оплаты", "value": summary.matched_payments},
            {"metric_code": "only_salesdrive_payments", "metric_name": "Оплаты только в SalesDrive", "value": summary.only_salesdrive_payments},
            {"metric_code": "only_supplier_payments", "metric_name": "Оплаты только в акте", "value": summary.only_supplier_payments},
            {"metric_code": "ambiguous_payments", "metric_name": "Неоднозначные оплаты", "value": summary.ambiguous_payments},
            {"metric_code": "sales_in_reconciliation", "metric_name": "Реализации в акте", "value": summary.sales_in_reconciliation},
            {"metric_code": "orders_in_salesdrive", "metric_name": "Заказы в SalesDrive за период", "value": summary.orders_in_salesdrive},
            {"metric_code": "sales_amount_in_reconciliation", "metric_name": "Сумма реализаций в акте", "value": summary.sales_amount_in_reconciliation},
            {"metric_code": "orders_amount_in_salesdrive", "metric_name": "Сумма заказов SalesDrive за период", "value": summary.orders_amount_in_salesdrive},
            {"metric_code": "orders_amount_delta", "metric_name": "Дельта по сумме заказов", "value": summary.orders_amount_delta},
            {"metric_code": "matched_orders", "metric_name": "Сопоставленные заказы", "value": summary.matched_orders},
            {"metric_code": "amount_mismatches", "metric_name": "Расхождения по сумме", "value": summary.amount_mismatches},
            {"metric_code": "missing_orders", "metric_name": "Реализации без заказа", "value": summary.missing_orders},
            {"metric_code": "returns_in_reconciliation", "metric_name": "Возвраты в акте", "value": summary.returns_in_reconciliation},
            {"metric_code": "returns_amount_in_reconciliation", "metric_name": "Сумма возвратов в акте", "value": summary.returns_amount_in_reconciliation},
            {"metric_code": "returns_in_salesdrive", "metric_name": "Заказы SalesDrive со статусом Возврат", "value": summary.returns_in_salesdrive},
            {"metric_code": "returns_amount_in_salesdrive", "metric_name": "Сумма заказов SalesDrive со статусом Возврат", "value": summary.returns_amount_in_salesdrive},
            {"metric_code": "returns_amount_delta", "metric_name": "Дельта по возвратам", "value": summary.returns_amount_delta},
            {"metric_code": "returns_linked_to_orders", "metric_name": "Возвраты, связанные с заказами", "value": summary.returns_linked_to_orders},
            {"metric_code": "returns_unresolved", "metric_name": "Неразобранные возвраты", "value": summary.returns_unresolved},
            {"metric_code": "warnings_count", "metric_name": "Количество предупреждений", "value": summary.warnings_count},
            {"metric_code": "issues_count", "metric_name": "Количество проблем", "value": summary.issues_count},
        ]

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            self._write_table(writer, sheet_names["summary"], summary_rows, used_sheet_names)
            self._write_table(writer, sheet_names["orders_match"], [row.to_row() for row in order_matches.matched], used_sheet_names)
            self._write_table(writer, sheet_names["orders_only_sd"], [row.to_row() for row in order_matches.only_salesdrive], used_sheet_names)
            self._write_table(
                writer,
                sheet_names["orders_only_reconciliation"],
                [row.to_row() for row in order_matches.only_supplier],
                used_sheet_names,
            )
            self._write_table(writer, sheet_names["returns"], [row.to_row() for row in return_matches], used_sheet_names)
            self._write_table(writer, sheet_names["warnings"], warning_rows, used_sheet_names)
            self._write_table(writer, sheet_names["issues"], issue_rows, used_sheet_names)

    def build_proteinplus_reconciliation(
        self,
        output_path: Path,
        supplier_name: str,
        summary: ProteinPlusDepositSummary,
        deposit_rows: list[dict[str, Any]],
        order_matches: OrderMatchArtifacts,
        return_rows: list[dict[str, Any]],
        warning_rows: list[dict[str, Any]],
        issue_rows: list[dict[str, Any]],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        base = supplier_name.capitalize()
        sheet_names = {
            "summary": f"{base}_Сводка",
            "deposit": f"{base}_Депозит",
            "orders_match": f"{base}_Заказы_Совпали",
            "orders_only_sd": f"{base}_Заказы_SalesDrive",
            "orders_only_supplier": f"{base}_Заказы_Supplier",
            "returns": f"{base}_Возвраты",
            "warnings": f"{base}_Предупреждения",
            "issues": f"{base}_Проблемы",
        }
        used_sheet_names: set[str] = set()
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            self._write_table(writer, sheet_names["summary"], summary.to_rows(), used_sheet_names)
            self._write_table(writer, sheet_names["deposit"], deposit_rows, used_sheet_names)
            self._write_table(writer, sheet_names["orders_match"], [row.to_row() for row in order_matches.matched], used_sheet_names)
            self._write_table(writer, sheet_names["orders_only_sd"], [row.to_row() for row in order_matches.only_salesdrive], used_sheet_names)
            self._write_table(writer, sheet_names["orders_only_supplier"], [row.to_row() for row in order_matches.only_supplier], used_sheet_names)
            self._write_table(writer, sheet_names["returns"], return_rows, used_sheet_names)
            self._write_table(writer, sheet_names["warnings"], warning_rows, used_sheet_names)
            self._write_table(writer, sheet_names["issues"], issue_rows, used_sheet_names)

    def _write_supplier_detail_sheets(
        self,
        writer: pd.ExcelWriter,
        payments: list[PaymentRecord],
        used_sheet_names: set[str],
        supplier_payment_reconciliations: list[SupplierPaymentReconciliationSnapshot] | None = None,
    ) -> None:
        snapshots_by_supplier = {
            snapshot.supplier_name.casefold(): snapshot for snapshot in (supplier_payment_reconciliations or [])
        }
        payments_by_supplier: dict[str, list[PaymentRecord]] = {}
        for payment in payments:
            payments_by_supplier.setdefault(payment.supplier_name or "unknown", []).append(payment)

        for supplier_name, supplier_payments in sorted(payments_by_supplier.items()):
            sheet_name = self._make_sheet_name(supplier_name, used_sheet_names)

            summary_rows = [
                {
                    "supplier_name": supplier_name,
                    "payments_count": len(supplier_payments),
                    "total_amount": self._sum_amount(supplier_payments),
                }
            ]
            daily_rows = self._build_supplier_daily_rows(supplier_payments, supplier_name)
            detail_rows = [self._report_row(payment) for payment in sorted(supplier_payments, key=lambda item: item.payment_date or "")]

            start = 0
            start = self._write_df(writer, sheet_name, summary_rows, start)
            start += 2
            start = self._write_df(writer, sheet_name, daily_rows, start)
            start += 2
            start = self._write_df(writer, sheet_name, detail_rows, start)

            snapshot = snapshots_by_supplier.get(supplier_name.casefold())
            if snapshot is not None:
                start += 2
                start = self._write_df(writer, sheet_name, snapshot.to_sheet_summary_rows(), start)
                if snapshot.matched_rows:
                    start += 2
                    start = self._write_df(writer, sheet_name, snapshot.matched_rows, start)
                if snapshot.only_salesdrive_rows:
                    start += 2
                    start = self._write_df(writer, sheet_name, snapshot.only_salesdrive_rows, start)
                if snapshot.only_supplier_rows:
                    start += 2
                    start = self._write_df(writer, sheet_name, snapshot.only_supplier_rows, start)
                if snapshot.ambiguous_rows:
                    start += 2
                    start = self._write_df(writer, sheet_name, snapshot.ambiguous_rows, start)
                if snapshot.mismatch_rows:
                    start += 2
                    self._write_df(writer, sheet_name, snapshot.mismatch_rows, start)

    def _build_supplier_daily_rows(self, payments: list[PaymentRecord], supplier_name: str) -> list[dict[str, Any]]:
        daily: dict[str, dict[str, Any]] = {}
        for payment in payments:
            payment_day = (payment.payment_date or "")[:10]
            row = daily.setdefault(
                payment_day,
                {"supplier_name": supplier_name, "payment_day": payment_day, "payments_count": 0, "total_amount": Decimal("0")},
            )
            row["payments_count"] += 1
            row["total_amount"] += payment.amount or Decimal("0")
        return sorted(daily.values(), key=lambda item: item["payment_day"])

    def _write_table(
        self,
        writer: pd.ExcelWriter,
        sheet_name: str,
        rows: list[dict[str, Any]],
        used_sheet_names: set[str],
    ) -> None:
        final_name = self._make_sheet_name(sheet_name, used_sheet_names)
        self._write_df(writer, final_name, rows, 0)

    def _write_df(
        self,
        writer: pd.ExcelWriter,
        sheet_name: str,
        rows: list[dict[str, Any]],
        startrow: int,
    ) -> int:
        df = self._to_df(rows)
        df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=startrow)
        return startrow + len(df.index) + 1

    def _to_df(self, rows: list[dict[str, Any]]) -> pd.DataFrame:
        normalized_rows = [self._normalize_decimal_values(row) for row in rows]
        df = pd.DataFrame(normalized_rows)
        return df.rename(columns={column: self.HEADER_LABELS.get(column, column) for column in df.columns})

    def _normalize_decimal_values(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if key == "amount":
                normalized["amount_value"] = float(value) if isinstance(value, Decimal) else value
                continue
            normalized[key] = float(value) if isinstance(value, Decimal) else value
        return normalized

    def _report_row(self, payment: PaymentRecord) -> dict[str, Any]:
        row = payment.to_report_row()
        if "amount" in row:
            row["amount_value"] = row.pop("amount")
        return row

    def _sum_amount(self, payments: list[PaymentRecord]) -> float:
        total = sum((payment.amount or Decimal("0")) for payment in payments)
        return float(total)

    def _sum_amount_rows(self, rows: list[dict[str, Any]]) -> float:
        total = Decimal("0")
        for row in rows:
            value = row.get("amount_value")
            if value in (None, "", float("nan")):
                continue
            total += Decimal(str(value))
        return float(total)

    def _make_sheet_name(self, base_name: str, used_sheet_names: set[str]) -> str:
        cleaned = re.sub(r"[\\/*?:\[\]]", "_", base_name)
        cleaned = cleaned[:31] or "sheet"
        if cleaned not in used_sheet_names:
            used_sheet_names.add(cleaned)
            return cleaned

        suffix = 1
        while True:
            suffix_str = f"_{suffix}"
            candidate = f"{cleaned[:31 - len(suffix_str)]}{suffix_str}"
            if candidate not in used_sheet_names:
                used_sheet_names.add(candidate)
                return candidate
            suffix += 1
