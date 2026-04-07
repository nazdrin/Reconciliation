from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from payment_analysis.models.payments import PaymentRecord

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExcelMappingRule:
    counterparty_pattern: str
    supplier_name: str
    match_type: str
    priority: int
    is_active: bool
    notes: str | None = None


@dataclass(slots=True)
class SupplierMapping:
    aliases_to_supplier: dict[str, str]
    excel_rules: list[ExcelMappingRule]

    @classmethod
    def from_sources(cls, yaml_path: Path, excel_path: Path) -> "SupplierMapping":
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        suppliers = payload.get("suppliers", {})
        aliases_to_supplier: dict[str, str] = {}
        for supplier_name, supplier_config in suppliers.items():
            for alias in supplier_config.get("aliases", []):
                aliases_to_supplier[alias.casefold()] = supplier_name

        excel_rules: list[ExcelMappingRule] = []
        if excel_path.exists():
            try:
                df = pd.read_excel(excel_path, sheet_name="mappings")
                for row in df.fillna("").to_dict(orient="records"):
                    pattern = str(row.get("counterparty_pattern", "")).strip()
                    supplier_name = str(row.get("supplier_name", "")).strip()
                    if not pattern or not supplier_name:
                        continue
                    excel_rules.append(
                        ExcelMappingRule(
                            counterparty_pattern=pattern,
                            supplier_name=supplier_name,
                            match_type=str(row.get("match_type", "contains")).strip() or "contains",
                            priority=int(row.get("priority", 100) or 100),
                            is_active=str(row.get("is_active", "true")).strip().lower() not in {"false", "0", "no"},
                            notes=str(row.get("notes", "")).strip() or None,
                        )
                    )
            except ValueError:
                LOGGER.warning("Excel mapping file %s does not contain 'mappings' sheet", excel_path)

        excel_rules.sort(key=lambda rule: rule.priority)
        return cls(aliases_to_supplier=aliases_to_supplier, excel_rules=excel_rules)


class CounterpartyMapper:
    def __init__(self, mapping: SupplierMapping) -> None:
        self._mapping = mapping

    def map_supplier(self, counterparty_name: str | None) -> tuple[str | None, str | None]:
        if not counterparty_name:
            return None, None

        normalized = counterparty_name.casefold()
        for rule in self._mapping.excel_rules:
            if not rule.is_active:
                continue
            pattern = rule.counterparty_pattern.casefold()
            if rule.match_type == "exact" and normalized == pattern:
                return rule.supplier_name, "excel_exact"
            if rule.match_type == "contains" and pattern in normalized:
                return rule.supplier_name, "excel_contains"

        if normalized in self._mapping.aliases_to_supplier:
            return self._mapping.aliases_to_supplier[normalized], "yaml_exact"
        for alias, supplier in self._mapping.aliases_to_supplier.items():
            if alias in normalized or normalized in alias:
                return supplier, "yaml_contains"

        return None, None

    def map_payments(self, payments: list[PaymentRecord]) -> tuple[list[PaymentRecord], list[dict[str, Any]]]:
        unmapped: dict[str, dict[str, Any]] = {}
        for payment in payments:
            supplier, source = self.map_supplier(payment.counterparty_name)
            payment.supplier_name = supplier
            payment.mapping_source = source
            if supplier is None:
                key = payment.counterparty_name or "<empty>"
                row = unmapped.setdefault(
                    key,
                    {
                        "counterparty_name": key,
                        "occurrences": 0,
                        "supplier_name": None,
                        "example_comment": payment.comment or payment.purpose,
                    },
                )
                row["occurrences"] += 1

        unmapped_rows = sorted(unmapped.values(), key=lambda item: (-int(item["occurrences"]), str(item["counterparty_name"])))
        LOGGER.info("Mapped %s outcoming payments, unmapped counterparties=%s", len(payments), len(unmapped_rows))
        return payments, unmapped_rows
