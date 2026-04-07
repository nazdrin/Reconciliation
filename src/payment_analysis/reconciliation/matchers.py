from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re

from payment_analysis.models.payments import PaymentRecord
from payment_analysis.reconciliation.config import SupplierReconciliationSettings
from payment_analysis.reconciliation.models import (
    ReconciliationMatchResult,
    SalesDriveOrderRecord,
    SupplierReconciliationRecord,
)

SUPPLIER_DOCUMENT_RE = re.compile(r"\b((?:BI|BO)-\d+|(?:ЗН|ZN|SA)\d+|№\s*\d{4,}|\d{4,})\b", re.IGNORECASE)
SUPPLIER_DOCUMENT_NUMERIC_RE = re.compile(r"(\d+)")


@dataclass(slots=True)
class PaymentMatchArtifacts:
    matched: list[ReconciliationMatchResult]
    only_salesdrive: list[ReconciliationMatchResult]
    only_supplier: list[ReconciliationMatchResult]
    ambiguous: list[ReconciliationMatchResult]
    mismatches: list[ReconciliationMatchResult]


@dataclass(slots=True)
class OrderMatchArtifacts:
    matched: list[ReconciliationMatchResult]
    only_salesdrive: list[ReconciliationMatchResult]
    only_supplier: list[ReconciliationMatchResult]
    warnings: list[ReconciliationMatchResult]
    issues: list[ReconciliationMatchResult]


def reconcile_payments(
    supplier_name: str,
    period_key: str,
    settings: SupplierReconciliationSettings,
    salesdrive_payments: list[PaymentRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> PaymentMatchArtifacts:
    matched: list[ReconciliationMatchResult] = []
    only_salesdrive: list[ReconciliationMatchResult] = []
    only_supplier: list[ReconciliationMatchResult] = []
    ambiguous: list[ReconciliationMatchResult] = []
    mismatches: list[ReconciliationMatchResult] = []

    supplier_payments = [record for record in supplier_records if record.record_type == "payment"]
    supplier_by_doc_exact: dict[str, list[SupplierReconciliationRecord]] = defaultdict(list)
    supplier_by_doc_fallback: dict[str, list[SupplierReconciliationRecord]] = defaultdict(list)
    for record in supplier_payments:
        exact_key = document_exact_key(record.document_number)
        fallback_key = normalize_supplier_document_key(record.document_number, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        if exact_key:
            supplier_by_doc_exact[exact_key].append(record)
        if fallback_key:
            supplier_by_doc_fallback[fallback_key].append(record)

    matched_supplier_rows: set[int] = set()
    for payment in salesdrive_payments:
        payment_doc = extract_supplier_document_number(payment.purpose, payment.comment)
        payment_doc_exact = document_exact_key(payment_doc)
        payment_doc_key = normalize_supplier_document_key(payment_doc, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        doc_candidates: list[SupplierReconciliationRecord] = []
        if payment_doc_exact:
            doc_candidates = supplier_by_doc_exact.get(payment_doc_exact, [])
        if not doc_candidates and payment_doc_key:
            doc_candidates = supplier_by_doc_fallback.get(payment_doc_key, [])
        if payment_doc_exact or payment_doc_key:
            if len(doc_candidates) > 1:
                ambiguous.append(
                    _match_result(
                        supplier_name=supplier_name,
                        period_key=period_key,
                        reconciliation_type="payments",
                        match_status="ambiguous",
                        payment=payment,
                        supplier_record=None,
                        match_key=payment_doc_exact or payment_doc_key,
                        notes="В акте сверки найдено несколько строк оплаты с одинаковым номером документа поставщика.",
                    )
                )
                continue
            if len(doc_candidates) == 1:
                record = doc_candidates[0]
                matched_supplier_rows.add(record.row_number)
                status = _payment_match_status(payment, record, settings)
                target = matched if status == "matched" else mismatches
                target.append(
                    _match_result(
                        supplier_name=supplier_name,
                        period_key=period_key,
                        reconciliation_type="payments",
                        match_status=status,
                        payment=payment,
                        supplier_record=record,
                        match_key=payment_doc_exact or payment_doc_key,
                    )
                )
                continue

        fallback_candidates = [
            record
            for record in supplier_payments
            if record.row_number not in matched_supplier_rows
            and payment.amount is not None
            and record.amount == payment.amount
            and (
                _date_distance_days(payment.payment_date, record.accounting_date) <= settings.payment_match_date_tolerance_days
                or _datetime_distance_hours(payment.payment_date, record.document_datetime) <= settings.payment_match_datetime_tolerance_hours
            )
        ]
        if len(fallback_candidates) > 1:
            ambiguous.append(
                _match_result(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="payments",
                    match_status="ambiguous",
                    payment=payment,
                    supplier_record=None,
                    match_key=f"{payment.amount}|{(payment.payment_date or '')[:10]}",
                    notes="Найдено несколько оплат в акте сверки по той же сумме и дате в пределах допуска.",
                )
            )
            continue
        if len(fallback_candidates) == 1:
            record = fallback_candidates[0]
            matched_supplier_rows.add(record.row_number)
            status = _payment_match_status(payment, record, settings)
            target = matched if status == "matched" else mismatches
            target.append(
                _match_result(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="payments",
                    match_status=status,
                    payment=payment,
                    supplier_record=record,
                    match_key=f"{payment.amount}|{(payment.payment_date or '')[:10]}",
                )
            )
            continue

        only_salesdrive.append(
            _match_result(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="payments",
                match_status="only_salesdrive",
                payment=payment,
                supplier_record=None,
                match_key=payment_doc_key,
            )
        )

    for record in supplier_payments:
        if record.row_number in matched_supplier_rows:
            continue
        only_supplier.append(
            _match_result(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="payments",
                match_status="only_supplier",
                payment=None,
                supplier_record=record,
                match_key=normalize_supplier_document_key(record.document_number, strip_leading_zeros=settings.strip_leading_zeros_for_fallback),
            )
        )

    return PaymentMatchArtifacts(
        matched=matched,
        only_salesdrive=only_salesdrive,
        only_supplier=only_supplier,
        ambiguous=ambiguous,
        mismatches=mismatches,
    )


def reconcile_orders(
    supplier_name: str,
    period_key: str,
    settings: SupplierReconciliationSettings,
    status_mapping: dict[int, str],
    orders: list[SalesDriveOrderRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> OrderMatchArtifacts:
    if settings.order_match_field == "tracking_number":
        return _reconcile_orders_by_tracking_number(
            supplier_name=supplier_name,
            period_key=period_key,
            settings=settings,
            status_mapping=status_mapping,
            orders=orders,
            supplier_records=supplier_records,
        )
    if settings.order_match_strategy == "amount_and_date_only":
        return _reconcile_orders_by_amount_and_date_only(
            supplier_name=supplier_name,
            period_key=period_key,
            settings=settings,
            status_mapping=status_mapping,
            orders=orders,
            supplier_records=supplier_records,
        )

    matched: list[ReconciliationMatchResult] = []
    only_salesdrive: list[ReconciliationMatchResult] = []
    only_supplier: list[ReconciliationMatchResult] = []
    warnings: list[ReconciliationMatchResult] = []
    issues: list[ReconciliationMatchResult] = []

    sales_records = [record for record in supplier_records if record.record_type == "sale"]
    orders_by_number_exact: dict[str, list[SalesDriveOrderRecord]] = defaultdict(list)
    orders_by_number_fallback: dict[str, list[SalesDriveOrderRecord]] = defaultdict(list)
    unmatched_orders: list[SalesDriveOrderRecord] = []
    for order in orders:
        if not order.number_sup:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="missing_numberSup",
                    salesdrive_ref=order.order_id,
                    supplier_ref=None,
                    match_key=None,
                    salesdrive_date=order.order_time,
                    supplier_date=None,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=None,
                    notes="У заказа SalesDrive пустое поле numberSup.",
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name,
                    salesdrive_order_id=order.order_id,
                )
            )
            continue
        exact_key = document_exact_key(order.number_sup)
        normalized_key = normalize_supplier_document_key(order.number_sup, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        if exact_key or normalized_key:
            if exact_key:
                orders_by_number_exact[exact_key].append(order)
            if normalized_key:
                orders_by_number_fallback[normalized_key].append(order)
            unmatched_orders.append(order)
        else:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="missing_numberSup",
                    salesdrive_ref=order.order_id,
                    supplier_ref=None,
                    match_key=None,
                    salesdrive_date=order.order_time,
                    supplier_date=None,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=None,
                    notes="Поле numberSup у заказа SalesDrive не содержит распознаваемый номер документа поставщика.",
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name,
                    salesdrive_order_id=order.order_id,
                )
            )

    matched_numbers: set[str] = set()
    supplier_sale_numbers: set[str] = set()
    unmatched_sales: list[SupplierReconciliationRecord] = []

    for record in sales_records:
        if not record.document_number:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="Для строки реализации в акте сверки не удалось распарсить номер документа.",
                )
            )
            continue

        exact_key = document_exact_key(record.document_number)
        key = normalize_supplier_document_key(record.document_number, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        if key is None:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.debit_amount,
                    notes="Номер документа в строке реализации акта сверки не содержит распознаваемый номер поставщика.",
                )
            )
            continue
        supplier_sale_numbers.add(key)
        order_candidates = orders_by_number_exact.get(exact_key or "", []) if exact_key else []
        if not order_candidates:
            order_candidates = orders_by_number_fallback.get(key, [])
        if len(order_candidates) > 1:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="duplicate_numberSup",
                    salesdrive_ref=",".join(order.order_id or "" for order in order_candidates),
                    supplier_ref=str(record.row_number),
                    match_key=key,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.debit_amount,
                    notes="В SalesDrive найдено несколько заказов с одинаковым numberSup.",
                )
            )
            continue
        if not order_candidates:
            unmatched_sales.append(record)
            continue

        order = order_candidates[0]
        matched_numbers.add(key)
        if order in unmatched_orders:
            unmatched_orders.remove(order)
        status = "matched"
        if order.expenses_amount != record.debit_amount:
            status = "mismatch_amount"
        result = ReconciliationMatchResult(
            supplier_name=supplier_name,
            period_key=period_key,
            reconciliation_type="orders",
            match_status=status,
            salesdrive_ref=order.order_id,
            supplier_ref=str(record.row_number),
            match_key=key,
            salesdrive_date=order.order_time,
            supplier_date=record.accounting_date,
            salesdrive_amount=order.expenses_amount,
            supplier_amount=record.debit_amount,
            salesdrive_status_id=order.status_id,
            salesdrive_status_name=order.status_name or status_mapping.get(order.status_id or -1),
            salesdrive_order_id=order.order_id,
        )
        matched.append(result)

        if order.status_id not in settings.allowed_sale_status_ids:
            warnings.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="warning",
                    salesdrive_ref=order.order_id,
                    supplier_ref=str(record.row_number),
                    match_key=key,
                    salesdrive_date=order.order_time,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=record.debit_amount,
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name or status_mapping.get(order.status_id or -1),
                    salesdrive_order_id=order.order_id,
                    warning_code="unexpected_status",
                    warning_message="Заказ найден в акте сверки как реализация, но статус SalesDrive не входит в допустимые статусы продажи",
                )
            )

    fallback_matches, fallback_only_orders, fallback_only_sales = _fallback_match_orders_by_amount_and_date(
        supplier_name=supplier_name,
        period_key=period_key,
        settings=settings,
        orders=unmatched_orders,
        sales=unmatched_sales,
    )
    matched.extend(fallback_matches)

    for order in fallback_only_orders:
        if not order.number_sup:
            continue
        key = normalize_supplier_document_key(order.number_sup, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        if key is None or key not in matched_numbers and key not in supplier_sale_numbers:
            only_salesdrive.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="only_salesdrive",
                    salesdrive_ref=order.order_id,
                    supplier_ref=None,
                    match_key=key,
                    salesdrive_date=order.order_time,
                    supplier_date=None,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=None,
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name,
                    salesdrive_order_id=order.order_id,
                )
            )

    for record in fallback_only_sales:
        key = normalize_supplier_document_key(record.document_number, strip_leading_zeros=settings.strip_leading_zeros_for_fallback)
        only_supplier.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="orders",
                match_status="only_supplier",
                salesdrive_ref=None,
                supplier_ref=str(record.row_number),
                match_key=key,
                salesdrive_date=None,
                supplier_date=record.accounting_date,
                salesdrive_amount=None,
                supplier_amount=record.debit_amount,
                notes="Реализация есть в акте сверки, но соответствующий заказ SalesDrive не найден.",
            )
        )

    return OrderMatchArtifacts(
        matched=matched,
        only_salesdrive=only_salesdrive,
        only_supplier=only_supplier,
        warnings=warnings,
        issues=issues,
    )


def reconcile_returns(
    supplier_name: str,
    period_key: str,
    orders: list[SalesDriveOrderRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> tuple[list[ReconciliationMatchResult], list[ReconciliationMatchResult]]:
    returns = [record for record in supplier_records if record.record_type == "return"]
    orders_by_number_exact = {
        key: order
        for order in orders
        if (key := document_exact_key(order.number_sup)) is not None
    }
    orders_by_number_fallback = {
        key: order
        for order in orders
        if (key := normalize_supplier_document_key(order.number_sup, strip_leading_zeros=True)) is not None
    }
    results: list[ReconciliationMatchResult] = []
    issues: list[ReconciliationMatchResult] = []

    for record in returns:
        if not record.document_number:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.credit_amount,
                    notes="Для строки возврата в акте сверки не удалось распарсить номер документа.",
                )
            )
            continue
        exact_key = document_exact_key(record.document_number)
        normalized_key = normalize_supplier_document_key(record.document_number, strip_leading_zeros=True)
        if normalized_key is None:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.credit_amount,
                    notes="Номер документа в строке возврата акта сверки не содержит распознаваемый номер поставщика.",
                )
            )
            continue
        order = orders_by_number_exact.get(exact_key or "") if exact_key else None
        if order is None:
            order = orders_by_number_fallback.get(normalized_key)
        if order is None:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="only_supplier",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=normalized_key,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.credit_amount,
                    notes="Возврат есть в акте сверки, но заказ SalesDrive по номеру не найден. В этом слое не используется отдельная сущность возврата из API.",
                )
            )
            continue
        results.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="returns",
                match_status="matched",
                salesdrive_ref=order.order_id,
                supplier_ref=str(record.row_number),
                match_key=normalized_key,
                salesdrive_date=order.updated_at or order.order_time,
                supplier_date=record.accounting_date,
                salesdrive_amount=order.expenses_amount,
                supplier_amount=record.credit_amount,
                salesdrive_status_id=order.status_id,
                salesdrive_status_name=order.status_name,
                salesdrive_order_id=order.order_id,
                notes="Возврат связан с заказом SalesDrive по номеру документа. Отдельная сущность возврата SalesDrive здесь не использовалась.",
            )
        )
    return results, issues


def _reconcile_orders_by_amount_and_date_only(
    supplier_name: str,
    period_key: str,
    settings: SupplierReconciliationSettings,
    status_mapping: dict[int, str],
    orders: list[SalesDriveOrderRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> OrderMatchArtifacts:
    sales_records = [record for record in supplier_records if record.record_type == "sale"]
    matched, remaining_orders, remaining_sales = _fallback_match_orders_by_amount_and_date(
        supplier_name=supplier_name,
        period_key=period_key,
        settings=settings,
        orders=orders,
        sales=sales_records,
    )
    warnings: list[ReconciliationMatchResult] = []
    for row in matched:
        if row.salesdrive_status_id not in settings.allowed_sale_status_ids:
            warnings.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="warning",
                    salesdrive_ref=row.salesdrive_ref,
                    supplier_ref=row.supplier_ref,
                    match_key=row.match_key,
                    salesdrive_date=row.salesdrive_date,
                    supplier_date=row.supplier_date,
                    salesdrive_amount=row.salesdrive_amount,
                    supplier_amount=row.supplier_amount,
                    salesdrive_status_id=row.salesdrive_status_id,
                    salesdrive_status_name=row.salesdrive_status_name or status_mapping.get(row.salesdrive_status_id or -1),
                    salesdrive_order_id=row.salesdrive_order_id,
                    warning_code="unexpected_status",
                    warning_message="Заказ найден в акте сверки как реализация, но статус SalesDrive не входит в допустимые статусы продажи",
                )
            )

    only_salesdrive = [
        ReconciliationMatchResult(
            supplier_name=supplier_name,
            period_key=period_key,
            reconciliation_type="orders",
            match_status="only_salesdrive",
            salesdrive_ref=order.order_id,
            supplier_ref=None,
            match_key=None,
            salesdrive_date=order.order_time,
            supplier_date=None,
            salesdrive_amount=order.expenses_amount,
            supplier_amount=None,
            salesdrive_status_id=order.status_id,
            salesdrive_status_name=order.status_name,
            salesdrive_order_id=order.order_id,
            notes="Заказ SalesDrive не удалось сопоставить с актом по сумме и дате.",
        )
        for order in remaining_orders
    ]
    only_supplier = [
        ReconciliationMatchResult(
            supplier_name=supplier_name,
            period_key=period_key,
            reconciliation_type="orders",
            match_status="only_supplier",
            salesdrive_ref=None,
            supplier_ref=str(record.row_number),
            match_key=normalize_supplier_document_key(record.document_number),
            salesdrive_date=None,
            supplier_date=record.accounting_date,
            salesdrive_amount=None,
            supplier_amount=record.amount,
            notes="Реализация есть в акте сверки, но соответствующий заказ SalesDrive не найден по сумме и дате.",
        )
        for record in remaining_sales
    ]
    return OrderMatchArtifacts(matched=matched, only_salesdrive=only_salesdrive, only_supplier=only_supplier, warnings=warnings, issues=[])


def _reconcile_orders_by_tracking_number(
    supplier_name: str,
    period_key: str,
    settings: SupplierReconciliationSettings,
    status_mapping: dict[int, str],
    orders: list[SalesDriveOrderRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> OrderMatchArtifacts:
    matched: list[ReconciliationMatchResult] = []
    only_salesdrive: list[ReconciliationMatchResult] = []
    only_supplier: list[ReconciliationMatchResult] = []
    warnings: list[ReconciliationMatchResult] = []
    issues: list[ReconciliationMatchResult] = []

    orders_by_tracking: dict[str, list[SalesDriveOrderRecord]] = defaultdict(list)
    for order in orders:
        if not order.tracking_number:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="missing_numberSup",
                    salesdrive_ref=order.order_id,
                    supplier_ref=None,
                    match_key=None,
                    salesdrive_date=order.updated_at or order.order_time,
                    supplier_date=None,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=None,
                    notes="У заказа SalesDrive пустой trackingNumber.",
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name,
                    salesdrive_order_id=order.order_id,
                )
            )
            continue
        orders_by_tracking[order.tracking_number].append(order)

    matched_tracking: set[str] = set()
    for record in [r for r in supplier_records if r.record_type == "sale"]:
        tracking = record.document_number
        if not tracking:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="В supplier orders file отсутствует tracking number.",
                )
            )
            continue
        candidates = orders_by_tracking.get(tracking, [])
        if len(candidates) > 1:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="ambiguous",
                    salesdrive_ref=",".join(order.order_id or "" for order in candidates),
                    supplier_ref=str(record.row_number),
                    match_key=tracking,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="Найдено несколько заказов SalesDrive с одинаковым trackingNumber.",
                )
            )
            continue
        if not candidates:
            only_supplier.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="only_supplier",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=tracking,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="Заказ есть только в supplier orders file, по trackingNumber совпадение в SalesDrive не найдено.",
                )
            )
            continue

        order = candidates[0]
        matched_tracking.add(tracking)
        status = "matched" if order.expenses_amount == record.amount else "mismatch_amount"
        matched.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="orders",
                match_status=status,
                salesdrive_ref=order.order_id,
                supplier_ref=str(record.row_number),
                match_key=tracking,
                salesdrive_date=order.updated_at or order.order_time,
                supplier_date=record.accounting_date,
                salesdrive_amount=order.expenses_amount,
                supplier_amount=record.amount,
                salesdrive_status_id=order.status_id,
                salesdrive_status_name=order.status_name or status_mapping.get(order.status_id or -1),
                salesdrive_order_id=order.order_id,
            )
        )
        if order.status_id not in settings.allowed_sale_status_ids:
            warnings.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="orders",
                    match_status="warning",
                    salesdrive_ref=order.order_id,
                    supplier_ref=str(record.row_number),
                    match_key=tracking,
                    salesdrive_date=order.updated_at or order.order_time,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=order.expenses_amount,
                    supplier_amount=record.amount,
                    salesdrive_status_id=order.status_id,
                    salesdrive_status_name=order.status_name or status_mapping.get(order.status_id or -1),
                    salesdrive_order_id=order.order_id,
                    warning_code="unexpected_status",
                    warning_message="Заказ найден по trackingNumber, но статус SalesDrive не входит в допустимые статусы продажи",
                )
            )

    for order in orders:
        if not order.tracking_number or order.tracking_number in matched_tracking:
            continue
        only_salesdrive.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="orders",
                match_status="only_salesdrive",
                salesdrive_ref=order.order_id,
                supplier_ref=None,
                match_key=order.tracking_number,
                salesdrive_date=order.updated_at or order.order_time,
                supplier_date=None,
                salesdrive_amount=order.expenses_amount,
                supplier_amount=None,
                salesdrive_status_id=order.status_id,
                salesdrive_status_name=order.status_name,
                salesdrive_order_id=order.order_id,
                notes="Заказ есть только в SalesDrive, по trackingNumber совпадение в supplier orders file не найдено.",
            )
        )

    return OrderMatchArtifacts(matched=matched, only_salesdrive=only_salesdrive, only_supplier=only_supplier, warnings=warnings, issues=issues)


def reconcile_returns_by_tracking_number(
    supplier_name: str,
    period_key: str,
    orders: list[SalesDriveOrderRecord],
    supplier_records: list[SupplierReconciliationRecord],
) -> tuple[list[ReconciliationMatchResult], list[ReconciliationMatchResult]]:
    matched: list[ReconciliationMatchResult] = []
    issues: list[ReconciliationMatchResult] = []
    orders_by_tracking: dict[str, list[SalesDriveOrderRecord]] = defaultdict(list)

    for order in orders:
        if not order.tracking_number:
            continue
        orders_by_tracking[order.tracking_number].append(order)

    for record in [r for r in supplier_records if r.record_type == "return"]:
        tracking = record.document_number
        if not tracking:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="error",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=None,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="У возврата поставщика отсутствует ТТН в поле Коментар.",
                )
            )
            continue

        candidates = orders_by_tracking.get(tracking, [])
        if len(candidates) > 1:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="ambiguous",
                    salesdrive_ref=",".join(order.order_id or "" for order in candidates),
                    supplier_ref=str(record.row_number),
                    match_key=tracking,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="Найдено несколько возвратных заказов SalesDrive с одинаковым trackingNumber.",
                )
            )
            continue
        if not candidates:
            issues.append(
                ReconciliationMatchResult(
                    supplier_name=supplier_name,
                    period_key=period_key,
                    reconciliation_type="returns",
                    match_status="only_supplier",
                    salesdrive_ref=None,
                    supplier_ref=str(record.row_number),
                    match_key=tracking,
                    salesdrive_date=None,
                    supplier_date=record.accounting_date,
                    salesdrive_amount=None,
                    supplier_amount=record.amount,
                    notes="Возврат есть в файле поставщика, но возвратный заказ SalesDrive по ТТН не найден.",
                )
            )
            continue

        order = candidates[0]
        status = "matched" if order.expenses_amount == record.amount else "mismatch_amount"
        matched.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="returns",
                match_status=status,
                salesdrive_ref=order.order_id,
                supplier_ref=str(record.row_number),
                match_key=tracking,
                salesdrive_date=order.updated_at or order.order_time,
                supplier_date=record.accounting_date,
                salesdrive_amount=order.expenses_amount,
                supplier_amount=record.amount,
                salesdrive_status_id=order.status_id,
                salesdrive_status_name=order.status_name,
                salesdrive_order_id=order.order_id,
            )
        )

    return matched, issues


def extract_supplier_document_number(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = SUPPLIER_DOCUMENT_RE.search(value)
        if match:
            return match.group(1).replace("№", "").strip().upper()
    return None


def document_exact_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper().replace("№", "").replace(" ", "")
    return normalized or None


def normalize_supplier_document_key(value: str | None, strip_leading_zeros: bool = False) -> str | None:
    if not value:
        return None
    match = SUPPLIER_DOCUMENT_NUMERIC_RE.search(value.strip().upper())
    if not match:
        return None
    digits = match.group(1)
    if strip_leading_zeros:
        digits = digits.lstrip("0") or "0"
    return digits


def _fallback_match_orders_by_amount_and_date(
    supplier_name: str,
    period_key: str,
    settings: SupplierReconciliationSettings,
    orders: list[SalesDriveOrderRecord],
    sales: list[SupplierReconciliationRecord],
) -> tuple[list[ReconciliationMatchResult], list[SalesDriveOrderRecord], list[SupplierReconciliationRecord]]:
    candidates: list[tuple[int, float, int, SalesDriveOrderRecord, SupplierReconciliationRecord]] = []
    amount_tolerance = Decimal(str(settings.order_match_amount_tolerance))

    for order in orders:
        if order.expenses_amount is None or order.order_time is None:
            continue
        order_date = _parse_any_datetime(order.order_time)
        if order_date is None:
            continue
        for sale in sales:
            if sale.debit_amount is None or sale.accounting_date is None:
                continue
            sale_date = _parse_any_datetime(sale.accounting_date)
            if sale_date is None:
                continue
            amount_delta = abs(order.expenses_amount - sale.debit_amount)
            day_delta = abs((order_date.date() - sale_date.date()).days)
            if amount_delta <= amount_tolerance and day_delta <= settings.order_match_date_tolerance_days:
                candidates.append((day_delta, float(amount_delta), sale.row_number, order, sale))

    candidates.sort(key=lambda item: (item[0], item[1], item[2], int(item[3].order_id or 0)))
    used_orders: set[str] = set()
    used_sales: set[int] = set()
    matched: list[ReconciliationMatchResult] = []

    for day_delta, amount_delta, _row_number, order, sale in candidates:
        order_key = order.order_id or ""
        if order_key in used_orders or sale.row_number in used_sales:
            continue
        used_orders.add(order_key)
        used_sales.add(sale.row_number)
        status = "matched"
        if order.expenses_amount != sale.debit_amount:
            status = "mismatch_amount"
        matched.append(
            ReconciliationMatchResult(
                supplier_name=supplier_name,
                period_key=period_key,
                reconciliation_type="orders",
                match_status=status,
                salesdrive_ref=order.order_id,
                supplier_ref=str(sale.row_number),
                match_key=f"fallback_amount_date|{sale.debit_amount}|{sale.accounting_date}",
                salesdrive_date=order.order_time,
                supplier_date=sale.accounting_date,
                salesdrive_amount=order.expenses_amount,
                supplier_amount=sale.debit_amount,
                salesdrive_status_id=order.status_id,
                salesdrive_status_name=order.status_name,
                salesdrive_order_id=order.order_id,
                notes=f"Сопоставлено по сумме и дате. Расхождение по дате: {day_delta} дн., по сумме: {amount_delta}.",
            )
        )

    remaining_orders = [order for order in orders if (order.order_id or "") not in used_orders]
    remaining_sales = [sale for sale in sales if sale.row_number not in used_sales]
    return matched, remaining_orders, remaining_sales


def _payment_match_status(
    payment: PaymentRecord,
    record: SupplierReconciliationRecord,
    settings: SupplierReconciliationSettings,
) -> str:
    if payment.amount != record.amount:
        return "mismatch_amount"
    if (
        _date_distance_days(payment.payment_date, record.accounting_date) > settings.payment_match_date_tolerance_days
        and _datetime_distance_hours(payment.payment_date, record.document_datetime) > settings.payment_match_datetime_tolerance_hours
    ):
        return "mismatch_date"
    return "matched"


def _date_distance_days(left: str | None, right: str | None) -> int:
    left_dt = _parse_any_datetime(left)
    right_dt = _parse_any_datetime(right)
    if left_dt is None or right_dt is None:
        return 9999
    return abs((left_dt.date() - right_dt.date()).days)


def _datetime_distance_hours(left: str | None, right: str | None) -> int:
    left_dt = _parse_any_datetime(left)
    right_dt = _parse_any_datetime(right)
    if left_dt is None or right_dt is None:
        return 9999
    seconds = abs((left_dt - right_dt).total_seconds())
    return int(seconds // 3600)


def _parse_any_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    patterns = (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d", 10),
        ("%d.%m.%Y %H:%M:%S", 19),
        ("%d.%m.%Y", 10),
    )
    for pattern, text_len in patterns:
        try:
            return datetime.strptime(text[:text_len], pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _match_result(
    supplier_name: str,
    period_key: str,
    reconciliation_type: str,
    match_status: str,
    payment: PaymentRecord | None,
    supplier_record: SupplierReconciliationRecord | None,
    match_key: str | None,
    notes: str | None = None,
) -> ReconciliationMatchResult:
    return ReconciliationMatchResult(
        supplier_name=supplier_name,
        period_key=period_key,
        reconciliation_type=reconciliation_type,  # type: ignore[arg-type]
        match_status=match_status,  # type: ignore[arg-type]
        salesdrive_ref=payment.payment_id if payment else None,
        supplier_ref=str(supplier_record.row_number) if supplier_record else None,
        match_key=match_key,
        salesdrive_date=payment.payment_date if payment else None,
        supplier_date=supplier_record.accounting_date if supplier_record else None,
        salesdrive_amount=payment.amount if payment else None,
        supplier_amount=supplier_record.amount if supplier_record else None,
        notes=notes,
    )
