from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any

from payment_analysis.clients.salesdrive_client import SalesDriveClient, SalesDriveClientError
from payment_analysis.config import Settings
from payment_analysis.models.payments import PaymentRecord
from payment_analysis.reconciliation.config import ReconciliationConfig
from payment_analysis.reconciliation.file_locator import SupplierReconciliationFileError, SupplierReconciliationFileLocator
from payment_analysis.reconciliation.matchers import reconcile_payments
from payment_analysis.reconciliation.models import SupplierPaymentReconciliationSnapshot
from payment_analysis.reconciliation.providers import (
    BiotusReconciliationProvider,
    DSNReconciliationProvider,
    MonsterLabReconciliationProvider,
    SportAtletReconciliationProvider,
)
from payment_analysis.reports.excel_report import ExcelReportBuilder
from payment_analysis.services.internal_transfer_detector import InternalTransferDetector, InternalTransferRules
from payment_analysis.services.payment_filters import IncomingCustomerRules, IncomingPaymentClassifier
from payment_analysis.services.payment_loader import PaymentLoader
from payment_analysis.services.payment_mapper import CounterpartyMapper, SupplierMapping
from payment_analysis.services.payment_normalizer import PaymentNormalizer

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PaymentAnalysisArtifacts:
    report_path: Path
    incoming_count: int
    outcoming_count: int
    unmapped_count: int
    errors: list[dict[str, str]]


class PaymentAnalysisService:
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
        self._loader = PaymentLoader(self._client, page_limit=settings.salesdrive_page_limit)
        self._normalizer = PaymentNormalizer()
        self._internal_transfer_detector = InternalTransferDetector(InternalTransferRules.from_yaml(settings.internal_transfer_rules_path))
        self._classifier = IncomingPaymentClassifier(IncomingCustomerRules.from_yaml(settings.analysis_settings_path))
        self._mapper = CounterpartyMapper(SupplierMapping.from_sources(settings.supplier_mapping_path, settings.supplier_mapping_excel_path))
        self._reconciliation_config = ReconciliationConfig.from_yaml(settings.supplier_reconciliation_config_path)
        self._reconciliation_file_locator = SupplierReconciliationFileLocator()
        self._report_builder = ExcelReportBuilder()

    def run(
        self,
        payment_type: str,
        date_from: str,
        date_to: str,
        output_path: Path,
        period_label: str,
    ) -> PaymentAnalysisArtifacts:
        LOGGER.info("Starting payment analysis type=%s date_from=%s date_to=%s", payment_type, date_from, date_to)
        errors: list[dict[str, str]] = []
        try:
            raw_payments_by_type = self._loader.load(payment_type, date_from, date_to)
        except SalesDriveClientError as exc:
            raise RuntimeError(f"Failed to load payments: {exc}") from exc

        incoming_raw = raw_payments_by_type.get("incoming", [])
        outcoming_raw = raw_payments_by_type.get("outcoming", [])

        incoming = self._normalizer.normalize_many(incoming_raw, "incoming")
        outcoming = self._normalizer.normalize_many(outcoming_raw, "outcoming")
        internal_transfer_pairs = self._internal_transfer_detector.detect(incoming, outcoming)

        analysis_payloads = [*incoming_raw[:10], *outcoming_raw[:10]]

        if incoming_raw:
            first_page = self._client.get_payment_page(
                payment_type="incoming",
                date_from=date_from,
                date_to=date_to,
                page=1,
                limit=self._settings.salesdrive_page_limit,
                save_debug_raw=False,
            )
            analysis = self._normalizer.analyze_structure(analysis_payloads, first_page.raw_response)
            self._normalizer.write_analysis_markdown(
                analysis=analysis,
                raw_response=first_page.raw_response,
                destination=self._settings.payment_api_analysis_path,
            )
        elif outcoming_raw:
            first_page = self._client.get_payment_page(
                payment_type="outcoming",
                date_from=date_from,
                date_to=date_to,
                page=1,
                limit=self._settings.salesdrive_page_limit,
                save_debug_raw=False,
            )
            analysis = self._normalizer.analyze_structure(analysis_payloads, first_page.raw_response)
            self._normalizer.write_analysis_markdown(
                analysis=analysis,
                raw_response=first_page.raw_response,
                destination=self._settings.payment_api_analysis_path,
            )
        else:
            errors.append({"stage": "load", "message": "No payments returned for the selected range."})

        self._classifier.classify_many(incoming)
        external_outcoming = [payment for payment in outcoming if not payment.is_internal_transfer]
        mapped_external_outcoming, unmapped = self._mapper.map_payments(external_outcoming)
        external_by_id = {payment.payment_id: payment for payment in mapped_external_outcoming}
        outcoming = [external_by_id.get(payment.payment_id, payment) for payment in outcoming]

        grouped_by_counterparty = self._group_outcoming_by_counterparty(mapped_external_outcoming)
        grouped_by_supplier = self._group_outcoming_by_supplier(mapped_external_outcoming)
        supplier_payment_reconciliations = self._build_supplier_payment_reconciliations(
            payments=mapped_external_outcoming,
            period_label=period_label,
            errors=errors,
        )
        grouped_by_supplier = self._merge_supplier_reconciliation_summary(grouped_by_supplier, supplier_payment_reconciliations)

        self._report_builder.build(
            output_path=output_path,
            incoming=incoming,
            outcoming=outcoming,
            internal_transfer_pairs=[pair.to_row() for pair in internal_transfer_pairs],
            grouped_by_counterparty=grouped_by_counterparty,
            grouped_by_supplier=grouped_by_supplier,
            unmapped_counterparties=unmapped,
            errors=errors,
            period_label=period_label,
            supplier_payment_reconciliations=supplier_payment_reconciliations,
        )
        LOGGER.info("Saved payment report to %s", output_path)
        return PaymentAnalysisArtifacts(
            report_path=output_path,
            incoming_count=len(incoming),
            outcoming_count=len(outcoming),
            unmapped_count=len(unmapped),
            errors=errors,
        )

    def _group_outcoming_by_counterparty(self, payments: list[PaymentRecord]) -> list[dict[str, Any]]:
        aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {"payments_count": 0, "total_amount": Decimal("0")})
        for payment in payments:
            key = payment.counterparty_name or "<empty>"
            aggregates[key]["counterparty_name"] = key
            aggregates[key]["payments_count"] += 1
            aggregates[key]["total_amount"] += payment.amount or Decimal("0")
            if payment.currency and "currency" not in aggregates[key]:
                aggregates[key]["currency"] = payment.currency
        return sorted(aggregates.values(), key=lambda row: (-row["payments_count"], row["counterparty_name"]))

    def _group_outcoming_by_supplier(self, payments: list[PaymentRecord]) -> list[dict[str, Any]]:
        aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {"payments_count": 0, "total_amount": Decimal("0")})
        for payment in payments:
            key = payment.supplier_name or "unmapped"
            aggregates[key]["supplier_name"] = key
            aggregates[key]["payments_count"] += 1
            aggregates[key]["total_amount"] += payment.amount or Decimal("0")
            if payment.currency and "currency" not in aggregates[key]:
                aggregates[key]["currency"] = payment.currency
        return sorted(aggregates.values(), key=lambda row: (-row["payments_count"], row["supplier_name"]))

    def _build_supplier_payment_reconciliations(
        self,
        payments: list[PaymentRecord],
        period_label: str,
        errors: list[dict[str, str]],
    ) -> list[SupplierPaymentReconciliationSnapshot]:
        period_key = self._normalize_period_label(period_label)
        if period_key is None:
            return []

        snapshots: list[SupplierPaymentReconciliationSnapshot] = []
        for supplier_settings in self._reconciliation_config.suppliers.values():
            alias_keys = {supplier_settings.supplier_name.casefold(), *[alias.casefold() for alias in supplier_settings.supplier_aliases]}
            supplier_payments = [payment for payment in payments if (payment.supplier_name or "").casefold() in alias_keys]
            if not supplier_payments:
                continue

            try:
                file_path = self._reconciliation_file_locator.locate(supplier_settings, period_key)
            except SupplierReconciliationFileError as exc:
                errors.append({"stage": "supplier_payment_reconciliation", "message": str(exc)})
                continue

            try:
                provider = self._build_reconciliation_provider(supplier_settings.supplier_name)
            except KeyError as exc:
                errors.append({"stage": "supplier_payment_reconciliation", "message": str(exc)})
                continue
            records = provider.parse_file(file_path, period_key)
            file_months = {(record.accounting_date or "")[:7] for record in records if record.accounting_date}
            if file_months and period_key not in file_months:
                errors.append(
                    {
                        "stage": "supplier_payment_reconciliation",
                        "message": f"File {file_path.name} contains months {sorted(file_months)}, expected {period_key}.",
                    }
                )
                continue

            payment_match = reconcile_payments(
                supplier_name=supplier_settings.supplier_name,
                period_key=period_key,
                settings=supplier_settings,
                salesdrive_payments=supplier_payments,
                supplier_records=records,
            )
            reconciliation_records = [record for record in records if record.record_type == "payment"]
            supplier_display_name = supplier_payments[0].supplier_name or supplier_settings.supplier_name
            snapshots.append(
                SupplierPaymentReconciliationSnapshot(
                    supplier_name=supplier_display_name,
                    period_key=period_key,
                    source_file=str(file_path),
                    salesdrive_payments_count=len(supplier_payments),
                    salesdrive_total_amount=self._sum_amount_decimal(supplier_payments),
                    reconciliation_payments_count=len(reconciliation_records),
                    reconciliation_total_amount=sum((record.amount or Decimal("0")) for record in reconciliation_records),
                    amount_difference=self._sum_amount_decimal(supplier_payments)
                    - sum((record.amount or Decimal("0")) for record in reconciliation_records),
                    opening_balance=self._extract_balance(records, "opening_balance"),
                    closing_balance=self._extract_balance(records, "closing_balance"),
                    matched_count=len(payment_match.matched),
                    matched_amount=sum((row.salesdrive_amount or Decimal("0")) for row in payment_match.matched),
                    only_salesdrive_count=len(payment_match.only_salesdrive),
                    only_supplier_count=len(payment_match.only_supplier),
                    ambiguous_count=len(payment_match.ambiguous),
                    mismatch_count=len(payment_match.mismatches),
                    matched_rows=[row.to_row() for row in payment_match.matched],
                    only_salesdrive_rows=[row.to_row() for row in payment_match.only_salesdrive],
                    only_supplier_rows=[row.to_row() for row in payment_match.only_supplier],
                    ambiguous_rows=[row.to_row() for row in payment_match.ambiguous],
                    mismatch_rows=[row.to_row() for row in payment_match.mismatches],
                )
            )
        return snapshots

    def _merge_supplier_reconciliation_summary(
        self,
        grouped_by_supplier: list[dict[str, Any]],
        snapshots: list[SupplierPaymentReconciliationSnapshot],
    ) -> list[dict[str, Any]]:
        snapshot_by_supplier = {snapshot.supplier_name.casefold(): snapshot for snapshot in snapshots}
        merged: list[dict[str, Any]] = []
        for row in grouped_by_supplier:
            merged_row = dict(row)
            snapshot = snapshot_by_supplier.get(str(row.get("supplier_name", "")).casefold())
            if snapshot:
                merged_row.update(snapshot.to_summary_row())
            merged.append(merged_row)
        return merged

    def _build_reconciliation_provider(self, supplier_name: str):
        if supplier_name.casefold() == "biotus":
            return BiotusReconciliationProvider(self._reconciliation_config.get_supplier(supplier_name))
        if supplier_name.casefold() == "dsn":
            return DSNReconciliationProvider(self._reconciliation_config.get_supplier(supplier_name))
        if supplier_name.casefold() == "monsterlab":
            return MonsterLabReconciliationProvider(self._reconciliation_config.get_supplier(supplier_name))
        if supplier_name.casefold() == "sport-atlet":
            return SportAtletReconciliationProvider(self._reconciliation_config.get_supplier(supplier_name))
        raise KeyError(f"No payment reconciliation provider registered for {supplier_name!r}")

    def _normalize_period_label(self, period_label: str) -> str | None:
        normalized = period_label.replace("_", "-")
        try:
            datetime.strptime(normalized, "%Y-%m")
        except ValueError:
            return None
        return normalized

    def _sum_amount_decimal(self, payments: list[PaymentRecord]) -> Decimal:
        return sum((payment.amount or Decimal("0")) for payment in payments)

    def _extract_balance(self, records: list, record_type: str) -> Decimal | None:
        for record in records:
            if getattr(record, "record_type", None) == record_type:
                return getattr(record, "amount", None)
        return None
