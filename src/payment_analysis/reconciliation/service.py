from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
from typing import Any

from payment_analysis.clients.nbu_client import NbuClientError, NbuExchangeRateClient
from payment_analysis.clients.salesdrive_client import SalesDriveClient, SalesDriveClientError
from payment_analysis.config import Settings
from payment_analysis.models.payments import PaymentRecord
from payment_analysis.reconciliation.config import ReconciliationConfig
from payment_analysis.reconciliation.file_locator import SupplierReconciliationFileLocator
from payment_analysis.reconciliation.matchers import (
    OrderMatchArtifacts,
    PaymentMatchArtifacts,
    reconcile_orders,
    reconcile_payments,
    reconcile_returns_by_tracking_number,
    reconcile_returns,
)
from payment_analysis.reconciliation.models import (
    ProteinPlusDepositSummary,
    ReconciliationMatchResult,
    SalesDriveOrderRecord,
    SupplierReconciliationSummary,
    SupplierReconciliationRecord,
)
from payment_analysis.reconciliation.providers import (
    BiotusReconciliationProvider,
    DobavkiUAReconciliationProvider,
    DSNReconciliationProvider,
    MonsterLabReconciliationProvider,
    ProteinPlusReconciliationProvider,
    SportAtletReconciliationProvider,
)
from payment_analysis.reports.excel_report import ExcelReportBuilder
from payment_analysis.services.internal_transfer_detector import InternalTransferDetector, InternalTransferRules
from payment_analysis.services.payment_loader import PaymentLoader
from payment_analysis.services.payment_mapper import CounterpartyMapper, SupplierMapping
from payment_analysis.services.payment_normalizer import PaymentNormalizer

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SupplierReconciliationArtifacts:
    report_path: Path
    supplier_name: str
    period_key: str
    issues_count: int
    warnings_count: int


class SupplierReconciliationService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = SalesDriveClient(
            base_url=settings.salesdrive_base_url,
            api_key=settings.salesdrive_api_key,
            order_api_key=settings.salesdrive_order_api_key,
            timeout_seconds=settings.salesdrive_timeout_seconds,
            debug_dir=settings.debug_dir,
            rate_limit_retry_seconds=settings.salesdrive_rate_limit_retry_seconds,
            rate_limit_max_retries=settings.salesdrive_rate_limit_max_retries,
        )
        self._nbu_client = NbuExchangeRateClient(timeout_seconds=settings.salesdrive_timeout_seconds)
        self._loader = PaymentLoader(self._client, page_limit=settings.salesdrive_page_limit)
        self._normalizer = PaymentNormalizer()
        self._internal_transfer_detector = InternalTransferDetector(InternalTransferRules.from_yaml(settings.internal_transfer_rules_path))
        self._mapper = CounterpartyMapper(SupplierMapping.from_sources(settings.supplier_mapping_path, settings.supplier_mapping_excel_path))
        self._config = ReconciliationConfig.from_yaml(settings.supplier_reconciliation_config_path)
        self._file_locator = SupplierReconciliationFileLocator()
        self._report_builder = ExcelReportBuilder()

    def run(self, supplier_name: str, period_key: str, output_path: Path) -> SupplierReconciliationArtifacts:
        supplier_settings = self._config.get_supplier(supplier_name)
        if supplier_settings.supplier_name.casefold() == "proteinplus":
            return self._run_proteinplus(supplier_settings, period_key, output_path)
        if supplier_settings.supplier_name.casefold() == "dobavki.ua":
            return self._run_dobavki_ua(supplier_settings, period_key, output_path)
        file_path = self._file_locator.locate(supplier_settings, period_key)
        provider = self._build_provider(supplier_settings.supplier_name)
        issues: list[dict[str, Any]] = []

        records = provider.parse_file(file_path, period_key)
        period_issues, is_period_valid = self._validate_reconciliation_period(records, file_path, period_key)
        issues.extend(period_issues)

        payments: list[PaymentRecord] = []
        orders: list[SalesDriveOrderRecord] = []
        payment_matches = PaymentMatchArtifacts(matched=[], only_salesdrive=[], only_supplier=[], ambiguous=[], mismatches=[])
        order_matches = OrderMatchArtifacts(matched=[], only_salesdrive=[], only_supplier=[], warnings=[], issues=[])
        return_matches: list[ReconciliationMatchResult] = []
        return_issues: list[ReconciliationMatchResult] = []

        if is_period_valid:
            payments = self._load_supplier_payments(supplier_settings, period_key)
            try:
                orders, order_api_raw = self._load_orders(supplier_settings, period_key)
                self._write_order_api_analysis(order_api_raw)
            except RuntimeError as exc:
                issues.append(
                    {
                        "issue_type": "order_api_error",
                        "message": str(exc),
                    }
                )
                orders = []

            payment_matches = reconcile_payments(
                supplier_name=supplier_settings.supplier_name,
                period_key=period_key,
                settings=supplier_settings,
                salesdrive_payments=payments,
                supplier_records=records,
            )
            order_matches = reconcile_orders(
                supplier_name=supplier_settings.supplier_name,
                period_key=period_key,
                settings=supplier_settings,
                status_mapping=self._config.status_mapping,
                orders=orders,
                supplier_records=records,
            )
            return_matches, return_issues = reconcile_returns(
                supplier_name=supplier_settings.supplier_name,
                period_key=period_key,
                orders=orders,
                supplier_records=records,
            )
            sale_records_count = len([record for record in records if record.record_type == "sale"])
            if orders and sale_records_count and not order_matches.matched:
                issues.append(
                    {
                        "issue_type": "no_order_key_overlap",
                        "message": "В SalesDrive есть заказы и в акте есть реализации, но совпадений по нормализованному номеру документа не найдено. Для Biotus в live order payload, вероятно, используется другое поле номера документа поставщика.",
                    }
                )
        else:
            LOGGER.warning("Skipping detailed reconciliation for %s %s because supplier file period content mismatches requested period.", supplier_settings.supplier_name, period_key)

        all_issue_rows = issues + [row.to_row() for row in payment_matches.ambiguous + payment_matches.mismatches + order_matches.issues + return_issues]
        warning_rows = [row.to_row() for row in order_matches.warnings]
        summary = self._build_summary(
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            file_path=file_path,
            records=records,
            payments=payments,
            orders=orders,
            payment_matches=payment_matches,
            order_matches=order_matches,
            return_matches=return_matches,
            warnings_count=len(warning_rows),
            issues_count=len(all_issue_rows),
        )

        self._report_builder.build_supplier_reconciliation(
            output_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            summary=summary,
            payment_matches=payment_matches,
            order_matches=order_matches,
            return_matches=return_matches,
            warning_rows=warning_rows,
            issue_rows=all_issue_rows,
        )
        LOGGER.info("Saved supplier reconciliation report to %s", output_path)
        return SupplierReconciliationArtifacts(
            report_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            issues_count=len(all_issue_rows),
            warnings_count=len(warning_rows),
        )

    def _build_provider(self, supplier_name: str):
        if supplier_name.casefold() == "biotus":
            return BiotusReconciliationProvider(self._config.get_supplier(supplier_name))
        if supplier_name.casefold() == "dobavki.ua":
            return DobavkiUAReconciliationProvider(self._config.get_supplier(supplier_name))
        if supplier_name.casefold() == "dsn":
            return DSNReconciliationProvider(self._config.get_supplier(supplier_name))
        if supplier_name.casefold() == "monsterlab":
            return MonsterLabReconciliationProvider(self._config.get_supplier(supplier_name))
        if supplier_name.casefold() == "proteinplus":
            return ProteinPlusReconciliationProvider(self._config.get_supplier(supplier_name))
        if supplier_name.casefold() == "sport-atlet":
            return SportAtletReconciliationProvider(self._config.get_supplier(supplier_name))
        raise KeyError(f"No reconciliation provider registered for {supplier_name!r}")

    def _load_supplier_payments(self, supplier_settings, period_key: str) -> list[PaymentRecord]:
        date_from, date_to = self.resolve_period(period_key)
        raw_by_type = self._loader.load("all", date_from, date_to)
        incoming = self._normalizer.normalize_many(raw_by_type.get("incoming", []), "incoming")
        outcoming = self._normalizer.normalize_many(raw_by_type.get("outcoming", []), "outcoming")
        self._internal_transfer_detector.detect(incoming, outcoming)

        external_outgoing = [payment for payment in outcoming if not payment.is_internal_transfer]
        mapped_external, _ = self._mapper.map_payments(external_outgoing)
        aliases = {alias.casefold() for alias in supplier_settings.supplier_aliases}
        aliases.add(supplier_settings.supplier_name.casefold())
        aliases.add(str(supplier_settings.supplier_code).casefold())
        matched = [
            payment
            for payment in mapped_external
            if (payment.supplier_name or "").casefold() in aliases
        ]
        LOGGER.info("Loaded %s outcoming payments mapped to supplier=%s", len(matched), supplier_settings.supplier_name)
        return matched

    def _load_orders(self, supplier_settings, period_key: str) -> tuple[list[SalesDriveOrderRecord], Any]:
        period_start, period_end = self._period_dates(period_key)
        fetch_from = (period_start - timedelta(days=supplier_settings.order_fetch_lookback_days)).strftime("%Y-%m-%d 00:00:00")
        fetch_to = (period_end + timedelta(days=supplier_settings.order_fetch_lookforward_days)).strftime("%Y-%m-%d 23:59:59")
        filters = {
            "filter[supplierlist]": supplier_settings.supplier_code,
            "filter[updateAt][from]": fetch_from,
            "filter[updateAt][to]": fetch_to,
            "filter[orderTime][from]": fetch_from,
            "filter[orderTime][to]": fetch_to,
        }
        try:
            first_page = self._client.get_order_page(page=1, limit=self._settings.salesdrive_page_limit, filters=filters, save_debug_raw=True)
            raw_items = list(first_page.items)
            page = 2
            total_pages = first_page.total_pages or 1
            while page <= total_pages:
                next_page = self._client.get_order_page(page=page, limit=self._settings.salesdrive_page_limit, filters=filters, save_debug_raw=False)
                raw_items.extend(next_page.items)
                if not next_page.items:
                    break
                page += 1
            orders = [self._normalize_order(item, supplier_settings) for item in raw_items]
            return orders, first_page.raw_response
        except SalesDriveClientError as exc:
            raise RuntimeError(f"Failed to load SalesDrive orders: {exc}") from exc

    def _normalize_order(self, payload: dict[str, Any], supplier_settings) -> SalesDriveOrderRecord:
        supplier_value = payload.get("supplierlist")
        number_sup = payload.get("numberSup")
        amount_field = supplier_settings.order_amount_field or "expensesAmount"
        expenses = self._to_decimal(payload.get(amount_field))
        status_id = self._to_int(payload.get("statusId"))
        status_name = self._config.status_mapping.get(status_id) if status_id is not None else None
        return SalesDriveOrderRecord(
            order_id=str(payload.get("id")) if payload.get("id") is not None else None,
            supplier_code=str(supplier_value) if supplier_value is not None else None,
            number_sup=str(number_sup).strip().upper() if number_sup not in (None, "") else None,
            tracking_number=self._extract_tracking_number(payload),
            expenses_amount=expenses,
            status_id=status_id,
            status_name=status_name,
            order_time=str(payload.get("orderTime")) if payload.get("orderTime") not in (None, "") else None,
            updated_at=str(payload.get("updateAt")) if payload.get("updateAt") not in (None, "") else None,
            raw_payload=payload,
        )

    def _write_order_api_analysis(self, raw_response: Any) -> None:
        top_level = sorted(raw_response.keys()) if isinstance(raw_response, dict) else []
        items = raw_response.get("data", []) if isinstance(raw_response, dict) else []
        order_fields = sorted(items[0].keys()) if items and isinstance(items[0], dict) else []
        content = [
            "# Order API Analysis",
            "",
            "## Top-level response fields",
            "",
        ]
        content.extend([f"- `{field}`" for field in top_level] or ["- No top-level fields detected"])
        content.extend(["", "## Order item fields", ""])
        content.extend([f"- `{field}`" for field in order_fields] or ["- No order item fields detected"])
        content.extend(
            [
                "",
                "## Confirmed reconciliation fields",
                "",
                f"- `supplierlist`: {'present' if 'supplierlist' in order_fields else 'missing'}",
                f"- `numberSup`: {'present' if 'numberSup' in order_fields else 'missing'}",
                f"- `expensesAmount`: {'present' if 'expensesAmount' in order_fields else 'missing'}",
                f"- `paymentAmount`: {'present' if 'paymentAmount' in order_fields else 'missing'}",
                f"- `statusId`: {'present' if 'statusId' in order_fields else 'missing'}",
                f"- `orderTime`: {'present' if 'orderTime' in order_fields else 'missing'}",
                f"- `updateAt`: {'present' if 'updateAt' in order_fields else 'missing'}",
                f"- `id`: {'present' if 'id' in order_fields else 'missing'}",
                "",
                "## Notes",
                "",
                "- SalesDrive order API uses `updateAt` in the live payload, not `updatedAt`.",
                "- Live Biotus orders expose `numberSup` values with `BO-...` prefix, while supplier reconciliation uses `BI-...`.",
                "- Reconciliation layer normalizes supplier document keys by numeric suffix, so `BO-00046907` and `BI-00046907` are treated as the same supplier reference for matching.",
            ]
        )
        if items and isinstance(items[0], dict):
            content.extend(["", "## Example order payload", "", "```json", json.dumps(items[0], ensure_ascii=False, indent=2), "```"])
        self._settings.order_api_analysis_path.write_text("\n".join(content) + "\n", encoding="utf-8")

    def _run_proteinplus(self, supplier_settings, period_key: str, output_path: Path) -> SupplierReconciliationArtifacts:
        provider = ProteinPlusReconciliationProvider(supplier_settings)
        deposit_file = self._file_locator.locate_from_patterns(supplier_settings, period_key, supplier_settings.deposit_file_patterns, "deposit")
        orders_file = self._file_locator.locate_from_patterns(supplier_settings, period_key, supplier_settings.orders_file_patterns, "orders")
        usd_to_uah_rate, rate_source = self._resolve_usd_to_uah_rate(supplier_settings, period_key)
        deposit_summary, deposit_rows, return_rows = provider.parse_deposit_file(deposit_file, period_key, usd_to_uah_rate=usd_to_uah_rate)
        supplier_order_records = provider.parse_orders_file(orders_file, period_key)
        supplier_orders_total = sum((record.amount or Decimal("0")) for record in supplier_order_records)

        issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        orders: list[SalesDriveOrderRecord] = []
        try:
            orders, order_api_raw = self._load_orders(supplier_settings, period_key)
            self._write_order_api_analysis(order_api_raw)
        except RuntimeError as exc:
            issues.append({"issue_type": "order_api_error", "message": str(exc)})
        sales_orders = [
            order for order in orders
            if order.status_id == 5 and (order.updated_at or "").startswith(period_key)
        ]
        salesdrive_orders_total = sum((order.expenses_amount or Decimal("0")) for order in sales_orders)
        salesdrive_return_orders = [
            order for order in orders
            if order.status_id == 7 and (order.order_time or "").startswith(period_key)
        ]

        order_matches = reconcile_orders(
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            settings=supplier_settings,
            status_mapping=self._config.status_mapping,
            orders=sales_orders,
            supplier_records=supplier_order_records,
        )
        warnings = [row.to_row() for row in order_matches.warnings]
        all_issue_rows = issues + [row.to_row() for row in order_matches.issues]

        summary = ProteinPlusDepositSummary(
            supplier_name=supplier_settings.supplier_name,
            supplier_code=supplier_settings.supplier_code,
            period_key=period_key,
            deposit_file=str(deposit_file),
            orders_file=str(orders_file),
            opening_deposit_usd=deposit_summary.opening_deposit_usd,
            opening_deposit_uah=deposit_summary.opening_deposit_uah,
            closing_deposit_usd=deposit_summary.closing_deposit_usd,
            closing_deposit_uah=deposit_summary.closing_deposit_uah,
            returns_total_usd=deposit_summary.returns_total_usd,
            returns_total_uah=deposit_summary.returns_total_uah,
            withdrawal_total_usd=deposit_summary.withdrawal_total_usd,
            withdrawal_total_uah=deposit_summary.withdrawal_total_uah,
            usd_to_uah_rate=deposit_summary.usd_to_uah_rate,
            returns_supplier_count=len(return_rows),
            returns_salesdrive_count=len(salesdrive_return_orders),
            returns_count_delta=len(salesdrive_return_orders) - len(return_rows),
            supplier_orders_count=len(supplier_order_records),
            supplier_orders_total=supplier_orders_total,
            salesdrive_orders_count=len(sales_orders),
            salesdrive_orders_total=salesdrive_orders_total,
            orders_total_delta=salesdrive_orders_total - supplier_orders_total,
            matched_orders_count=len([row for row in order_matches.matched if row.match_status in {"matched", "mismatch_amount"}]),
            only_salesdrive_orders_count=len(order_matches.only_salesdrive),
            only_supplier_orders_count=len(order_matches.only_supplier),
            amount_mismatch_count=len([row for row in order_matches.matched if row.match_status == "mismatch_amount"]),
            warnings_count=len(warnings),
            issues_count=len(all_issue_rows),
            raw_payload={**deposit_summary.raw_payload, "usd_to_uah_rate_source": rate_source},
        )

        self._report_builder.build_proteinplus_reconciliation(
            output_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            summary=summary,
            deposit_rows=deposit_rows,
            order_matches=order_matches,
            return_rows=[row.to_row() for row in return_rows],
            warning_rows=warnings,
            issue_rows=all_issue_rows,
        )
        LOGGER.info("Saved supplier reconciliation report to %s", output_path)
        return SupplierReconciliationArtifacts(
            report_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            issues_count=len(all_issue_rows),
            warnings_count=len(warnings),
        )

    def _run_dobavki_ua(self, supplier_settings, period_key: str, output_path: Path) -> SupplierReconciliationArtifacts:
        file_path = self._file_locator.locate(supplier_settings, period_key)
        provider = DobavkiUAReconciliationProvider(supplier_settings)
        records = provider.parse_file(file_path, period_key)

        issues: list[dict[str, Any]] = []
        orders: list[SalesDriveOrderRecord] = []
        try:
            orders, order_api_raw = self._load_orders(supplier_settings, period_key)
            self._write_order_api_analysis(order_api_raw)
        except RuntimeError as exc:
            issues.append({"issue_type": "order_api_error", "message": str(exc)})

        sales_orders = [order for order in orders if order.status_id == 5 and (order.order_time or "").startswith(period_key)]
        return_orders = [order for order in orders if order.status_id == 7 and (order.order_time or "").startswith(period_key)]

        order_matches = reconcile_orders(
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            settings=supplier_settings,
            status_mapping=self._config.status_mapping,
            orders=sales_orders,
            supplier_records=records,
        )
        return_matches, return_issues = reconcile_returns_by_tracking_number(
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            orders=return_orders,
            supplier_records=records,
        )

        all_issue_rows = issues + [row.to_row() for row in order_matches.issues + return_issues]
        warning_rows = [row.to_row() for row in order_matches.warnings]
        summary = SupplierReconciliationSummary(
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            source_file=str(file_path),
            opening_balance=None,
            closing_balance=None,
            payments_in_salesdrive=0,
            payments_amount_in_salesdrive=Decimal("0"),
            payments_in_reconciliation=0,
            payments_amount_in_reconciliation=Decimal("0"),
            matched_payments=0,
            only_salesdrive_payments=0,
            only_supplier_payments=0,
            ambiguous_payments=0,
            sales_in_reconciliation=len([record for record in records if record.record_type == "sale"]),
            orders_in_salesdrive=len(sales_orders),
            sales_amount_in_reconciliation=sum((record.amount or Decimal("0")) for record in records if record.record_type == "sale"),
            orders_amount_in_salesdrive=sum((order.expenses_amount or Decimal("0")) for order in sales_orders),
            orders_amount_delta=sum((order.expenses_amount or Decimal("0")) for order in sales_orders)
            - sum((record.amount or Decimal("0")) for record in records if record.record_type == "sale"),
            matched_orders=len([row for row in order_matches.matched if row.match_status in {"matched", "mismatch_amount"}]),
            amount_mismatches=len([row for row in order_matches.matched if row.match_status == "mismatch_amount"])
            + len([row for row in return_matches if row.match_status == "mismatch_amount"]),
            missing_orders=len(order_matches.only_supplier),
            returns_in_reconciliation=len([record for record in records if record.record_type == "return"]),
            returns_amount_in_reconciliation=sum((record.amount or Decimal("0")) for record in records if record.record_type == "return"),
            returns_in_salesdrive=len(return_orders),
            returns_amount_in_salesdrive=sum((order.expenses_amount or Decimal("0")) for order in return_orders),
            returns_amount_delta=sum((order.expenses_amount or Decimal("0")) for order in return_orders)
            - sum((record.amount or Decimal("0")) for record in records if record.record_type == "return"),
            returns_linked_to_orders=len(return_matches),
            returns_unresolved=max(0, len([record for record in records if record.record_type == "return"]) - len(return_matches)),
            warnings_count=len(warning_rows),
            issues_count=len(all_issue_rows),
        )

        self._report_builder.build_supplier_reconciliation(
            output_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            summary=summary,
            payment_matches=PaymentMatchArtifacts(matched=[], only_salesdrive=[], only_supplier=[], ambiguous=[], mismatches=[]),
            order_matches=order_matches,
            return_matches=return_matches,
            warning_rows=warning_rows,
            issue_rows=all_issue_rows,
        )
        LOGGER.info("Saved supplier reconciliation report to %s", output_path)
        return SupplierReconciliationArtifacts(
            report_path=output_path,
            supplier_name=supplier_settings.supplier_name,
            period_key=period_key,
            issues_count=len(all_issue_rows),
            warnings_count=len(warning_rows),
        )

    def _resolve_usd_to_uah_rate(self, supplier_settings, period_key: str) -> tuple[Decimal, str]:
        period_end = self._period_end_date(period_key)
        try:
            return self._nbu_client.get_rate_for_date("USD", period_end), f"NBU {period_end.isoformat()}"
        except NbuClientError as exc:
            if supplier_settings.usd_to_uah_rate is None:
                raise
            LOGGER.warning("Failed to load NBU USD/UAH rate for %s, using config fallback: %s", period_key, exc)
            return Decimal(str(supplier_settings.usd_to_uah_rate)), "config_fallback"

    def _period_end_date(self, period_key: str):
        year, month = period_key.split("-")
        last_day = monthrange(int(year), int(month))[1]
        return datetime(int(year), int(month), last_day).date()

    def _validate_reconciliation_period(
        self,
        records: list[SupplierReconciliationRecord],
        file_path: Path,
        period_key: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        target_month = period_key
        seen_months = sorted({(record.accounting_date or "")[:7] for record in records if record.accounting_date})
        if seen_months and target_month not in seen_months:
            return (
                [
                    {
                        "issue_type": "period_mismatch",
                        "message": f"Файл сверки {file_path.name} содержит месяцы {seen_months}, ожидался период {target_month}. Детальная сверка пропущена, чтобы избежать ложных расхождений.",
                    }
                ],
                False,
            )
        return [], True

    def _build_summary(
        self,
        supplier_name: str,
        period_key: str,
        file_path: Path,
        records: list[SupplierReconciliationRecord],
        payments: list[PaymentRecord],
        orders: list[SalesDriveOrderRecord],
        payment_matches: PaymentMatchArtifacts,
        order_matches: OrderMatchArtifacts,
        return_matches: list[ReconciliationMatchResult],
        warnings_count: int,
        issues_count: int,
    ) -> SupplierReconciliationSummary:
        period_orders = [order for order in orders if (order.order_time or "")[:7] == period_key]
        period_return_orders = [order for order in period_orders if order.status_id == 7]
        sales_records = [record for record in records if record.record_type == "sale"]
        return_records = [record for record in records if record.record_type == "return"]
        payment_records = [record for record in records if record.record_type == "payment"]
        sales_amount = sum((record.debit_amount or Decimal("0")) for record in sales_records)
        orders_amount = sum((order.expenses_amount or Decimal("0")) for order in period_orders)
        return_amount = sum((record.credit_amount or Decimal("0")) for record in return_records)
        return_orders_amount = sum((order.expenses_amount or Decimal("0")) for order in period_return_orders)
        return SupplierReconciliationSummary(
            supplier_name=supplier_name,
            period_key=period_key,
            source_file=str(file_path),
            opening_balance=self._extract_balance(records, "opening_balance"),
            closing_balance=self._extract_balance(records, "closing_balance"),
            payments_in_salesdrive=len(payments),
            payments_amount_in_salesdrive=sum((payment.amount or Decimal("0")) for payment in payments),
            payments_in_reconciliation=len(payment_records),
            payments_amount_in_reconciliation=sum((record.amount or Decimal("0")) for record in payment_records),
            matched_payments=len(payment_matches.matched),
            only_salesdrive_payments=len(payment_matches.only_salesdrive),
            only_supplier_payments=len(payment_matches.only_supplier),
            ambiguous_payments=len(payment_matches.ambiguous),
            sales_in_reconciliation=len(sales_records),
            orders_in_salesdrive=len(period_orders),
            sales_amount_in_reconciliation=sales_amount,
            orders_amount_in_salesdrive=orders_amount,
            orders_amount_delta=orders_amount - sales_amount,
            matched_orders=len([row for row in order_matches.matched if row.match_status in {"matched", "mismatch_amount"}]),
            amount_mismatches=len(payment_matches.mismatches) + len([row for row in order_matches.matched if row.match_status == "mismatch_amount"]),
            missing_orders=len(order_matches.only_supplier),
            returns_in_reconciliation=len(return_records),
            returns_amount_in_reconciliation=return_amount,
            returns_in_salesdrive=len(period_return_orders),
            returns_amount_in_salesdrive=return_orders_amount,
            returns_amount_delta=return_orders_amount - return_amount,
            returns_linked_to_orders=len(return_matches),
            returns_unresolved=max(0, len(return_records) - len(return_matches)),
            warnings_count=warnings_count,
            issues_count=issues_count,
        )

    def _extract_balance(self, records: list[SupplierReconciliationRecord], record_type: str) -> Decimal | None:
        for record in records:
            if record.record_type == record_type:
                return record.amount
        return None

    @staticmethod
    def resolve_period(period_key: str) -> tuple[str, str]:
        month_dt = datetime.strptime(period_key, "%Y-%m")
        last_day = monthrange(month_dt.year, month_dt.month)[1]
        return f"{period_key}-01 00:00:00", f"{period_key}-{last_day:02d} 23:59:59"

    @staticmethod
    def _period_dates(period_key: str) -> tuple[datetime, datetime]:
        month_dt = datetime.strptime(period_key, "%Y-%m")
        last_day = monthrange(month_dt.year, month_dt.month)[1]
        return datetime(month_dt.year, month_dt.month, 1), datetime(month_dt.year, month_dt.month, last_day)

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            return None

    def _to_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_tracking_number(self, payload: dict[str, Any]) -> str | None:
        direct = payload.get("trackingNumber")
        if direct not in (None, ""):
            return str(direct).strip()
        delivery_data = payload.get("ord_delivery_data")
        if isinstance(delivery_data, list):
            for item in delivery_data:
                if not isinstance(item, dict):
                    continue
                value = item.get("trackingNumber")
                if value not in (None, ""):
                    return str(value).strip()
        return None
