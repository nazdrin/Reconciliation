from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PaymentPage:
    items: list[dict[str, Any]]
    page: int
    limit: int
    total_items: int | None
    total_pages: int | None
    raw_response: Any


@dataclass(slots=True)
class PaymentFieldAnalysis:
    response_top_level_fields: list[str]
    payment_fields: list[str]
    candidate_mapping: dict[str, str | None]
    notes: list[str]


@dataclass(slots=True)
class OrderPage:
    items: list[dict[str, Any]]
    page: int
    limit: int
    total_items: int | None
    total_pages: int | None
    raw_response: Any
