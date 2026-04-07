from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from payment_analysis.models.api import PaymentFieldAnalysis
from payment_analysis.models.payments import PaymentRecord, PaymentType

LOGGER = logging.getLogger(__name__)


class PaymentNormalizer:
    FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
        "payment_id": ("id", "payment_id", "paymentId", "number", "document_id"),
        "payment_date": ("date", "payment_date", "created_at", "datetime", "operation_date"),
        "amount": ("amount", "sum", "total", "value", "price"),
        "currency": ("currency", "currency_code", "valuta", "currencyName"),
        "comment": ("comment", "purpose", "description", "note", "notes", "payment_comment"),
        "counterparty_name": (
            "counterparty",
            "counterparty_name",
            "company",
            "client",
            "sender",
            "recipient",
            "contractor",
            "payer",
            "payee",
            "fio",
            "name",
        ),
        "organization_name": ("organization", "organization_name", "company_name", "legal_entity"),
        "counterparty_tax_id": ("egrpou",),
        "organization_tax_id": ("egrpou",),
        "account_reference": ("account", "accountNumber", "iban", "card", "requisites", "bank_account", "account_number"),
        "raw_status": ("status", "payment_status", "state"),
    }

    def normalize_many(self, payloads: Iterable[dict[str, Any]], payment_type: PaymentType) -> list[PaymentRecord]:
        return [self.normalize_one(payload, payment_type) for payload in payloads]

    def normalize_one(self, payload: dict[str, Any], payment_type: PaymentType) -> PaymentRecord:
        payment_id = self._extract_value(payload, self.FIELD_CANDIDATES["payment_id"])
        payment_date = self._extract_value(payload, self.FIELD_CANDIDATES["payment_date"])
        amount_value = self._extract_value(payload, self.FIELD_CANDIDATES["amount"])
        currency = self._extract_value(payload, self.FIELD_CANDIDATES["currency"])
        comment = self._extract_value(payload, self.FIELD_CANDIDATES["comment"])
        purpose = self._extract_value(payload, ("purpose",))
        counterparty_name = self._extract_value(payload, self.FIELD_CANDIDATES["counterparty_name"])
        counterparty_tax_id = self._extract_value_from_prefix(payload, "counterparty", "egrpou")
        organization_name = self._extract_value(payload, self.FIELD_CANDIDATES["organization_name"])
        organization_tax_id = self._extract_value_from_prefix(payload, "organization", "egrpou")
        account_reference = self._extract_value(payload, self.FIELD_CANDIDATES["account_reference"])
        raw_status = self._extract_value(payload, self.FIELD_CANDIDATES["raw_status"])

        return PaymentRecord(
            payment_id=str(payment_id) if payment_id is not None else None,
            payment_type=payment_type,
            payment_date=str(payment_date) if payment_date is not None else None,
            amount=self._to_decimal(amount_value),
            currency=str(currency) if currency is not None else None,
            counterparty_name=str(counterparty_name) if counterparty_name is not None else None,
            counterparty_tax_id=str(counterparty_tax_id) if counterparty_tax_id is not None else None,
            comment=str(comment) if comment is not None else None,
            purpose=str(purpose) if purpose is not None else None,
            organization_name=str(organization_name) if organization_name is not None else None,
            organization_tax_id=str(organization_tax_id) if organization_tax_id is not None else None,
            account_reference=str(account_reference) if account_reference is not None else None,
            raw_status=str(raw_status) if raw_status is not None else None,
            raw_payload=payload,
        )

    def analyze_structure(self, payloads: Iterable[dict[str, Any]], raw_response: Any) -> PaymentFieldAnalysis:
        payload_list = list(payloads)
        first_payload = payload_list[0] if payload_list else {}
        payment_fields = sorted(self._flatten_keys(first_payload)) if isinstance(first_payload, dict) else []
        response_top_level_fields = sorted(raw_response.keys()) if isinstance(raw_response, dict) else []
        candidate_mapping = {
            field_name: self._find_resolved_field_path(first_payload, candidates)
            for field_name, candidates in self.FIELD_CANDIDATES.items()
        }
        notes = []
        if not payment_fields:
            notes.append("Payment item fields were not detected. Response may be empty or nested unexpectedly.")
        if candidate_mapping["counterparty_name"] is None:
            notes.append("Counterparty field is ambiguous and was not mapped confidently.")
        if candidate_mapping["comment"] is None:
            notes.append("Comment field is ambiguous and was not mapped confidently.")
        if candidate_mapping["account_reference"] is None:
            notes.append("Account or requisites field is ambiguous and was not mapped confidently.")
        if candidate_mapping["currency"] is None:
            notes.append("Currency field is absent in payment items. Currency may need to be derived from account context or assumed externally.")
        if candidate_mapping["raw_status"] is None:
            notes.append("Item-level payment status is absent. Top-level response status is only API call status, not payment lifecycle status.")
        if self._has_sparse_counterparty(payload_list):
            notes.append("Some payments may not have a filled counterparty object. In such cases, beneficiary text may only exist in `purpose`.")
        if self._comment_is_sparse_but_purpose_is_populated(payload_list):
            notes.append("`comment` is often empty, while `purpose` contains the business-meaningful payment description. Normalization should prefer `purpose`.")
        return PaymentFieldAnalysis(
            response_top_level_fields=response_top_level_fields,
            payment_fields=payment_fields,
            candidate_mapping=candidate_mapping,
            notes=notes,
        )

    def write_analysis_markdown(
        self,
        analysis: PaymentFieldAnalysis,
        raw_response: Any,
        destination: Path,
    ) -> None:
        example_payment = None
        if isinstance(raw_response, dict):
            example_items = []
            for value in raw_response.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    example_items = value
                    break
            if example_items:
                example_payment = example_items[0]
        content = [
            "# Payment API Analysis",
            "",
            "## Top-level response fields",
            "",
        ]
        if analysis.response_top_level_fields:
            content.extend(f"- `{field}`" for field in analysis.response_top_level_fields)
        else:
            content.append("- No top-level dict fields detected")
        content.extend(["", "## Payment item fields", ""])
        if analysis.payment_fields:
            content.extend(f"- `{field}`" for field in analysis.payment_fields)
        else:
            content.append("- No payment item fields detected")
        content.extend(["", "## Interpreted field mapping", ""])
        for logical_name, actual_field in analysis.candidate_mapping.items():
            content.append(f"- `{logical_name}` -> `{actual_field}`" if actual_field else f"- `{logical_name}` -> unresolved")
        content.extend(["", "## Notes", ""])
        if analysis.notes:
            content.extend(f"- {note}" for note in analysis.notes)
        else:
            content.append("- No critical ambiguities detected from the first sample.")
        if example_payment is not None:
            content.extend(
                [
                    "",
                    "## Example payment payload",
                    "",
                    "```json",
                    json.dumps(example_payment, ensure_ascii=False, indent=2),
                    "```",
                ]
            )
        destination.write_text("\n".join(content) + "\n", encoding="utf-8")
        LOGGER.info("Updated API analysis document at %s", destination)

    def _extract_value(self, payload: dict[str, Any], candidates: tuple[str, ...]) -> Any:
        for candidate in candidates:
            value = self._get_nested_value_by_key(payload, candidate)
            if value not in (None, ""):
                if isinstance(value, dict):
                    for nested_key in ("name", "title", "value", "number"):
                        nested_value = value.get(nested_key)
                        if nested_value not in (None, ""):
                            return nested_value
                return value
        return None

    def _find_resolved_field_path(self, payload: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
        flattened = self._flatten_key_map(payload)
        for candidate in candidates:
            candidate_lower = candidate.lower()
            for path, value in flattened.items():
                if path.split(".")[-1].lower() == candidate_lower:
                    if isinstance(value, dict):
                        for nested_key in ("title", "name", "value", "number", "accountNumber"):
                            nested_value = value.get(nested_key)
                            if nested_value not in (None, ""):
                                return f"{path}.{nested_key}"
                    if value in (None, ""):
                        continue
                    return path
        return None

    def _extract_value_from_prefix(self, payload: dict[str, Any], prefix: str, nested_key: str) -> Any:
        flattened = self._flatten_key_map(payload)
        target = f"{prefix}.{nested_key}".lower()
        for path, value in flattened.items():
            if path.lower() == target and value not in (None, ""):
                return value
        return None

    def _get_nested_value_by_key(self, payload: dict[str, Any], candidate: str) -> Any:
        candidate_lower = candidate.lower()
        for path, value in self._flatten_key_map(payload).items():
            if path.split(".")[-1].lower() == candidate_lower:
                return value
        return None

    def _flatten_keys(self, payload: dict[str, Any], prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            if isinstance(value, dict):
                keys.update(self._flatten_keys(value, path))
        return keys

    def _flatten_key_map(self, payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            result[path] = value
            if isinstance(value, dict):
                result.update(self._flatten_key_map(value, path))
        return result

    def _to_decimal(self, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            normalized = value.replace(" ", "").replace(",", ".")
            try:
                return Decimal(normalized)
            except InvalidOperation:
                return None
        return None

    def _has_sparse_counterparty(self, payloads: list[dict[str, Any]]) -> bool:
        for payload in payloads:
            counterparty = payload.get("counterparty")
            purpose = payload.get("purpose")
            if counterparty in (None, "", {}) and purpose not in (None, ""):
                return True
        return False

    def _comment_is_sparse_but_purpose_is_populated(self, payloads: list[dict[str, Any]]) -> bool:
        if not payloads:
            return False
        sparse_comment_count = 0
        purpose_count = 0
        for payload in payloads:
            if payload.get("comment") in (None, ""):
                sparse_comment_count += 1
            if payload.get("purpose") not in (None, ""):
                purpose_count += 1
        return sparse_comment_count >= max(1, len(payloads) // 2) and purpose_count >= max(1, len(payloads) // 2)
