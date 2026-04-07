from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from pathlib import Path

import yaml

from payment_analysis.models.payments import PaymentRecord

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OwnAccount:
    account_number: str
    label: str | None = None
    card_mask: str | None = None


@dataclass(slots=True)
class AllowedAccountPair:
    from_account: str
    to_account: str


@dataclass(slots=True)
class InternalTransferRules:
    require_pair_match: bool
    pairing_window_minutes: int
    allow_direct_self_markers_without_pair: bool
    own_entity_names: list[str]
    own_entity_tax_ids: list[str]
    own_accounts: list[OwnAccount]
    allowed_account_pairs: list[AllowedAccountPair]
    self_transfer_phrases: list[str]
    direct_self_markers: list[str]

    @classmethod
    def from_yaml(cls, path: Path) -> "InternalTransferRules":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        own_entities = payload.get("own_entities", {})
        pair_rules = payload.get("pair_rules", {})
        text_markers = payload.get("text_markers", {})
        return cls(
            require_pair_match=bool(payload.get("require_pair_match", True)),
            pairing_window_minutes=int(payload.get("pairing_window_minutes", 5)),
            allow_direct_self_markers_without_pair=bool(payload.get("allow_direct_self_markers_without_pair", True)),
            own_entity_names=own_entities.get("names", []),
            own_entity_tax_ids=own_entities.get("tax_ids", []),
            own_accounts=[OwnAccount(**row) for row in payload.get("own_accounts", [])],
            allowed_account_pairs=[AllowedAccountPair(**row) for row in pair_rules.get("allowed_account_pairs", [])],
            self_transfer_phrases=text_markers.get("self_transfer_phrases", []),
            direct_self_markers=text_markers.get("direct_self_markers", []),
        )


@dataclass(slots=True)
class InternalTransferPair:
    pair_id: str
    amount: Decimal | None
    outcoming_payment_id: str | None
    outcoming_date: str | None
    outcoming_account: str | None
    incoming_payment_id: str | None
    incoming_date: str | None
    incoming_account: str | None
    reason: str

    def to_row(self) -> dict[str, str | Decimal | None]:
        return {
            "pair_id": self.pair_id,
            "amount": self.amount,
            "outcoming_payment_id": self.outcoming_payment_id,
            "outcoming_date": self.outcoming_date,
            "outcoming_account": self.outcoming_account,
            "incoming_payment_id": self.incoming_payment_id,
            "incoming_date": self.incoming_date,
            "incoming_account": self.incoming_account,
            "reason": self.reason,
        }


class InternalTransferDetector:
    def __init__(self, rules: InternalTransferRules) -> None:
        self._rules = rules
        self._own_accounts = {account.account_number for account in rules.own_accounts}
        self._allowed_pairs = {(pair.from_account, pair.to_account) for pair in rules.allowed_account_pairs}

    def detect(
        self,
        incoming_payments: list[PaymentRecord],
        outcoming_payments: list[PaymentRecord],
    ) -> list[InternalTransferPair]:
        pairs: list[InternalTransferPair] = []
        used_incoming_ids: set[str] = set()
        used_outcoming_ids: set[str] = set()

        for out_payment in outcoming_payments:
            if out_payment.payment_id in used_outcoming_ids:
                continue
            if not self._is_self_candidate(out_payment):
                continue

            matched_incoming = self._find_best_incoming_match(out_payment, incoming_payments, used_incoming_ids)
            if matched_incoming is None:
                if self._rules.allow_direct_self_markers_without_pair and self._has_direct_self_marker(out_payment):
                    self._mark_payment_internal(out_payment, pair_id=f"out-{out_payment.payment_id}", reason="Self transfer markers without matched incoming pair")
                elif not self._rules.require_pair_match:
                    self._mark_payment_internal(out_payment, pair_id=f"out-{out_payment.payment_id}", reason="Self transfer candidate without matched incoming pair")
                continue

            pair_id = f"internal-{out_payment.payment_id}-{matched_incoming.payment_id}"
            reason = "Matched incoming/outcoming pair between own accounts with self-transfer markers"
            self._mark_payment_internal(out_payment, pair_id=pair_id, reason=reason)
            self._mark_payment_internal(matched_incoming, pair_id=pair_id, reason=reason)
            used_outcoming_ids.add(out_payment.payment_id or "")
            used_incoming_ids.add(matched_incoming.payment_id or "")
            pairs.append(
                InternalTransferPair(
                    pair_id=pair_id,
                    amount=out_payment.amount,
                    outcoming_payment_id=out_payment.payment_id,
                    outcoming_date=out_payment.payment_date,
                    outcoming_account=out_payment.account_reference,
                    incoming_payment_id=matched_incoming.payment_id,
                    incoming_date=matched_incoming.payment_date,
                    incoming_account=matched_incoming.account_reference,
                    reason=reason,
                )
            )

        LOGGER.info("Detected %s internal transfer pairs", len(pairs))
        if self._rules.allow_direct_self_markers_without_pair:
            for incoming_payment in incoming_payments:
                if incoming_payment.is_internal_transfer:
                    continue
                if self._has_direct_self_marker(incoming_payment) and self._is_own_account(incoming_payment.account_reference):
                    self._mark_payment_internal(
                        incoming_payment,
                        pair_id=f"in-{incoming_payment.payment_id}",
                        reason="Direct self marker on own account without matched outgoing pair",
                    )
            for outcoming_payment in outcoming_payments:
                if outcoming_payment.is_internal_transfer:
                    continue
                if self._has_direct_self_marker(outcoming_payment) and self._is_own_account(outcoming_payment.account_reference):
                    self._mark_payment_internal(
                        outcoming_payment,
                        pair_id=f"out-{outcoming_payment.payment_id}",
                        reason="Direct self marker on own account without matched incoming pair",
                    )
        return pairs

    def _find_best_incoming_match(
        self,
        out_payment: PaymentRecord,
        incoming_payments: list[PaymentRecord],
        used_incoming_ids: set[str],
    ) -> PaymentRecord | None:
        candidates: list[tuple[timedelta, PaymentRecord]] = []
        out_dt = self._parse_datetime(out_payment.payment_date)
        if out_dt is None or out_payment.amount is None:
            return None

        for in_payment in incoming_payments:
            if in_payment.payment_id in used_incoming_ids:
                continue
            if in_payment.amount != out_payment.amount:
                continue
            if in_payment.account_reference == out_payment.account_reference:
                continue
            if not self._is_own_account(in_payment.account_reference) or not self._is_own_account(out_payment.account_reference):
                continue
            if not self._is_allowed_pair(out_payment.account_reference, in_payment.account_reference):
                continue

            in_dt = self._parse_datetime(in_payment.payment_date)
            if in_dt is None:
                continue
            delta = abs(in_dt - out_dt)
            if delta > timedelta(minutes=self._rules.pairing_window_minutes):
                continue
            if not self._is_self_candidate(in_payment):
                continue
            candidates.append((delta, in_payment))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _is_self_candidate(self, payment: PaymentRecord) -> bool:
        contact = payment.raw_payload.get("contact") if isinstance(payment.raw_payload, dict) else None
        text = " ".join(
            filter(
                None,
                [
                    payment.counterparty_name,
                    payment.counterparty_tax_id,
                    payment.comment,
                    payment.purpose,
                    contact.get("fName") if isinstance(contact, dict) else None,
                    contact.get("lName") if isinstance(contact, dict) else None,
                    contact.get("mName") if isinstance(contact, dict) else None,
                ],
            )
        ).casefold()
        name_match = any(name.casefold() in text for name in self._rules.own_entity_names)
        tax_match = any(tax_id.casefold() in text for tax_id in self._rules.own_entity_tax_ids)
        phrase_match = any(phrase.casefold() in text for phrase in self._rules.self_transfer_phrases)
        account_match = self._is_own_account(payment.account_reference)
        return account_match and (name_match or tax_match or phrase_match)

    def _is_own_account(self, account_reference: str | None) -> bool:
        return bool(account_reference and account_reference in self._own_accounts)

    def _is_allowed_pair(self, from_account: str | None, to_account: str | None) -> bool:
        if not from_account or not to_account:
            return False
        if not self._allowed_pairs:
            return True
        return (from_account, to_account) in self._allowed_pairs

    def _mark_payment_internal(self, payment: PaymentRecord, pair_id: str, reason: str) -> None:
        payment.is_internal_transfer = True
        payment.incoming_category = "internal_transfer" if payment.payment_type == "incoming" else payment.incoming_category
        payment.internal_transfer_pair_id = pair_id
        payment.internal_transfer_reason = reason

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _has_direct_self_marker(self, payment: PaymentRecord) -> bool:
        contact = payment.raw_payload.get("contact") if isinstance(payment.raw_payload, dict) else None
        text = " ".join(
            filter(
                None,
                [
                    payment.counterparty_name,
                    payment.comment,
                    payment.purpose,
                    contact.get("fName") if isinstance(contact, dict) else None,
                    contact.get("lName") if isinstance(contact, dict) else None,
                    contact.get("mName") if isinstance(contact, dict) else None,
                ],
            )
        ).casefold()
        return any(marker.casefold() in text for marker in self._rules.direct_self_markers)
