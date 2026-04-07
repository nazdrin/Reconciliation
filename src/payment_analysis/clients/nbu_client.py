from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import logging

import requests

LOGGER = logging.getLogger(__name__)


class NbuClientError(RuntimeError):
    pass


class NbuExchangeRateClient:
    _URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self._timeout_seconds = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def get_rate_for_date(self, currency_code: str, target_date: date, lookback_days: int = 7) -> Decimal:
        code = currency_code.upper()
        current_date = target_date
        for _ in range(lookback_days + 1):
            rate = self._request_rate(code, current_date)
            if rate is not None:
                LOGGER.info("Loaded NBU FX rate %s/%s=%s for %s", code, "UAH", rate, current_date.isoformat())
                return rate
            current_date -= timedelta(days=1)
        raise NbuClientError(f"NBU rate for {code} was not found for {target_date.isoformat()} within {lookback_days} days lookback.")

    def _request_rate(self, currency_code: str, target_date: date) -> Decimal | None:
        params = {
            "valcode": currency_code,
            "date": target_date.strftime("%Y%m%d"),
            "json": "",
        }
        try:
            response = self._session.get(self._URL, params=params, timeout=self._timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise NbuClientError(f"NBU FX request timed out for {target_date.isoformat()}.") from exc
        except requests.RequestException as exc:
            raise NbuClientError(f"NBU FX request failed for {target_date.isoformat()}: {exc}") from exc
        except ValueError as exc:
            raise NbuClientError(f"NBU FX endpoint returned non-JSON payload for {target_date.isoformat()}.") from exc

        if not isinstance(payload, list) or not payload:
            return None

        first_item = payload[0]
        if not isinstance(first_item, dict):
            return None

        raw_rate = first_item.get("rate")
        if raw_rate in (None, ""):
            return None
        try:
            return Decimal(str(raw_rate))
        except InvalidOperation:
            raise NbuClientError(f"NBU FX endpoint returned invalid rate value for {target_date.isoformat()}: {raw_rate!r}")
