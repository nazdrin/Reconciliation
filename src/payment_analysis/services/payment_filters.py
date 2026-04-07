from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import yaml

from payment_analysis.models.payments import IncomingCategory, PaymentRecord

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class IncomingCustomerRules:
    include_if_counterparty_contains: list[str]
    include_if_comment_contains: list[str]
    exclude_from_customer_receipts_if_counterparty_contains: list[str]
    exclude_from_customer_receipts_if_comment_contains: list[str]
    exclude_from_customer_receipts_if_exact_counterparty: list[str]

    @classmethod
    def from_yaml(cls, path: Path) -> "IncomingCustomerRules":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules = payload.get("incoming_customer_rules", payload)
        return cls(
            include_if_counterparty_contains=rules.get("include_if_counterparty_contains", []),
            include_if_comment_contains=rules.get("include_if_comment_contains", []),
            exclude_from_customer_receipts_if_counterparty_contains=rules.get("exclude_from_customer_receipts_if_counterparty_contains", []),
            exclude_from_customer_receipts_if_comment_contains=rules.get("exclude_from_customer_receipts_if_comment_contains", []),
            exclude_from_customer_receipts_if_exact_counterparty=rules.get("exclude_from_customer_receipts_if_exact_counterparty", []),
        )


class IncomingPaymentClassifier:
    def __init__(self, rules: IncomingCustomerRules) -> None:
        self._rules = rules

    def classify_incoming_payment(self, payment: PaymentRecord) -> IncomingCategory:
        if payment.is_internal_transfer:
            return "internal_transfer"

        counterparty = (payment.counterparty_name or "").casefold()
        comment = " ".join(filter(None, [payment.comment, payment.purpose])).casefold()

        if counterparty in {value.casefold() for value in self._rules.exclude_from_customer_receipts_if_exact_counterparty}:
            return "excluded_receipt"
        if self._contains_any(counterparty, self._rules.exclude_from_customer_receipts_if_counterparty_contains):
            return "excluded_receipt"
        if self._contains_any(comment, self._rules.exclude_from_customer_receipts_if_comment_contains):
            return "excluded_receipt"

        if self._contains_any(counterparty, self._rules.include_if_counterparty_contains):
            return "customer_receipt"
        if self._contains_any(comment, self._rules.include_if_comment_contains):
            return "customer_receipt"

        return "customer_receipt"

    def classify_many(self, payments: list[PaymentRecord]) -> list[PaymentRecord]:
        for payment in payments:
            payment.incoming_category = self.classify_incoming_payment(payment)
        LOGGER.info("Classified %s incoming payments", len(payments))
        return payments

    def _contains_any(self, haystack: str, needles: list[str]) -> bool:
        return any(needle.casefold() in haystack for needle in needles if needle)
