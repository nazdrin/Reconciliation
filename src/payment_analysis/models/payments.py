from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Literal

PaymentType = Literal["incoming", "outcoming"]
IncomingCategory = Literal["customer_receipt", "excluded_receipt", "internal_transfer", "unknown_incoming"]


@dataclass(slots=True)
class PaymentRecord:
    payment_id: str | None
    payment_type: PaymentType
    payment_date: str | None
    amount: Decimal | None
    currency: str | None
    counterparty_name: str | None
    counterparty_tax_id: str | None
    comment: str | None
    purpose: str | None
    organization_name: str | None
    organization_tax_id: str | None
    account_reference: str | None
    raw_status: str | None
    supplier_name: str | None = None
    incoming_category: IncomingCategory | None = None
    is_internal_transfer: bool = False
    internal_transfer_pair_id: str | None = None
    internal_transfer_reason: str | None = None
    mapping_source: str | None = None
    source_system: str = "salesdrive"
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_report_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["amount"] = str(self.amount) if self.amount is not None else None
        row["raw_payload"] = str(self.raw_payload)
        return row
