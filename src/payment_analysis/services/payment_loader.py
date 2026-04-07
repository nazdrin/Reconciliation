from __future__ import annotations

import logging
from typing import Any

from payment_analysis.clients.salesdrive_client import SalesDriveClient

LOGGER = logging.getLogger(__name__)


class PaymentLoader:
    def __init__(self, client: SalesDriveClient, page_limit: int) -> None:
        self._client = client
        self._page_limit = page_limit

    def load(
        self,
        payment_type: str,
        date_from: str,
        date_to: str,
    ) -> dict[str, list[dict[str, Any]]]:
        if payment_type == "all":
            LOGGER.info("Loading both incoming and outcoming payments")
            return {
                "incoming": self._client.get_all_payments("incoming", date_from, date_to, self._page_limit),
                "outcoming": self._client.get_all_payments("outcoming", date_from, date_to, self._page_limit),
            }
        LOGGER.info("Loading payments for type=%s", payment_type)
        return {
            payment_type: self._client.get_all_payments(payment_type, date_from, date_to, self._page_limit),
        }
