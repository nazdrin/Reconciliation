from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any

import requests

from payment_analysis.models.api import OrderPage, PaymentPage

LOGGER = logging.getLogger(__name__)


class SalesDriveClientError(RuntimeError):
    pass


class SalesDriveClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        order_api_key: str | None,
        timeout_seconds: int,
        debug_dir: Path,
        rate_limit_retry_seconds: int = 65,
        rate_limit_max_retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._debug_dir = debug_dir
        self._rate_limit_retry_seconds = rate_limit_retry_seconds
        self._rate_limit_max_retries = rate_limit_max_retries
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json", "X-Api-Key": api_key})
        self._order_session = requests.Session()
        self._order_session.headers.update({"Accept": "application/json", "X-Api-Key": order_api_key or api_key})

    def get_payment_page(
        self,
        payment_type: str,
        date_from: str,
        date_to: str,
        page: int,
        limit: int,
        save_debug_raw: bool = False,
    ) -> PaymentPage:
        params = {
            "type": payment_type,
            "filter[date][from]": date_from,
            "filter[date][to]": date_to,
            "page": page,
            "limit": min(limit, 100),
        }
        url = f"{self._base_url}/api/payment/list/"

        LOGGER.info("Requesting SalesDrive payments page=%s limit=%s type=%s", page, limit, payment_type)
        response = self._request_with_rate_limit_retry(url=url, params=params, page=page, session=self._session)

        if not response.text.strip():
            raise SalesDriveClientError(f"SalesDrive returned empty response for page {page}.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SalesDriveClientError(f"SalesDrive returned non-JSON response for page {page}.") from exc

        items = self._extract_items(payload)
        total_items = self._extract_total_items(payload, items)
        total_pages = self._extract_total_pages(payload, limit, total_items)

        if save_debug_raw:
            self._save_debug_payload(payload, payment_type, page)

        LOGGER.info(
            "Received %s records for page=%s type=%s total_pages=%s total_items=%s",
            len(items),
            page,
            payment_type,
            total_pages,
            total_items,
        )
        return PaymentPage(
            items=items,
            page=page,
            limit=limit,
            total_items=total_items,
            total_pages=total_pages,
            raw_response=payload,
        )

    def _request_with_rate_limit_retry(
        self,
        url: str,
        params: dict[str, Any],
        page: int,
        session: requests.Session,
    ) -> requests.Response:
        attempt = 0
        while True:
            try:
                response = session.get(url, params=params, timeout=self._timeout_seconds)
                response.raise_for_status()
                return response
            except requests.Timeout as exc:
                raise SalesDriveClientError(f"SalesDrive request timed out for page {page}.") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                body = exc.response.text[:500] if exc.response is not None else ""
                if status == 400 and "API limit reached" in body and attempt < self._rate_limit_max_retries:
                    attempt += 1
                    LOGGER.warning(
                        "SalesDrive rate limit reached on page=%s. Sleeping %s seconds before retry %s/%s",
                        page,
                        self._rate_limit_retry_seconds,
                        attempt,
                        self._rate_limit_max_retries,
                    )
                    time.sleep(self._rate_limit_retry_seconds)
                    continue
                raise SalesDriveClientError(f"SalesDrive HTTP error {status} for page {page}: {body}") from exc
            except requests.RequestException as exc:
                if attempt < self._rate_limit_max_retries:
                    attempt += 1
                    LOGGER.warning(
                        "SalesDrive request transport error on page=%s. Sleeping %s seconds before retry %s/%s: %s",
                        page,
                        self._rate_limit_retry_seconds,
                        attempt,
                        self._rate_limit_max_retries,
                        exc,
                    )
                    time.sleep(self._rate_limit_retry_seconds)
                    continue
                raise SalesDriveClientError(f"SalesDrive request failed for page {page}: {exc}") from exc

    def get_all_payments(
        self,
        payment_type: str,
        date_from: str,
        date_to: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        normalized_limit = min(limit, 100)
        all_items: list[dict[str, Any]] = []
        page = 1
        total_pages_logged = False

        while True:
            payment_page = self.get_payment_page(
                payment_type=payment_type,
                date_from=date_from,
                date_to=date_to,
                page=page,
                limit=normalized_limit,
                save_debug_raw=(page == 1),
            )
            if payment_page.total_pages is not None and not total_pages_logged:
                LOGGER.info("SalesDrive reports %s pages for type=%s", payment_page.total_pages, payment_type)
                total_pages_logged = True

            all_items.extend(payment_page.items)

            if not payment_page.items:
                break
            if payment_page.total_pages is not None and page >= payment_page.total_pages:
                break
            if len(payment_page.items) < normalized_limit:
                break
            page += 1

        LOGGER.info("Loaded total %s payments for type=%s", len(all_items), payment_type)
        return all_items

    def get_order_page(
        self,
        page: int,
        limit: int,
        filters: dict[str, Any] | None = None,
        save_debug_raw: bool = False,
    ) -> OrderPage:
        params = {"page": page, "limit": min(limit, 100)}
        if filters:
            params.update(filters)
        url = f"{self._base_url}/api/order/list/"

        LOGGER.info("Requesting SalesDrive orders page=%s limit=%s", page, limit)
        response = self._request_with_rate_limit_retry(url=url, params=params, page=page, session=self._order_session)

        if not response.text.strip():
            raise SalesDriveClientError(f"SalesDrive returned empty order response for page {page}.")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SalesDriveClientError(f"SalesDrive returned non-JSON order response for page {page}.") from exc

        items = self._extract_items(payload)
        total_items = self._extract_total_items(payload, items)
        total_pages = self._extract_total_pages(payload, limit, total_items)

        if save_debug_raw:
            self._save_debug_payload(payload, "orders", page)

        LOGGER.info(
            "Received %s orders for page=%s total_pages=%s total_items=%s",
            len(items),
            page,
            total_pages,
            total_items,
        )
        return OrderPage(
            items=items,
            page=page,
            limit=limit,
            total_items=total_items,
            total_pages=total_pages,
            raw_response=payload,
        )

    def get_all_orders(
        self,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_limit = min(limit, 100)
        all_items: list[dict[str, Any]] = []
        page = 1
        total_pages_logged = False

        while True:
            order_page = self.get_order_page(
                page=page,
                limit=normalized_limit,
                filters=filters,
                save_debug_raw=(page == 1),
            )
            if order_page.total_pages is not None and not total_pages_logged:
                LOGGER.info("SalesDrive reports %s order pages", order_page.total_pages)
                total_pages_logged = True

            all_items.extend(order_page.items)

            if not order_page.items:
                break
            if order_page.total_pages is not None and page >= order_page.total_pages:
                break
            if len(order_page.items) < normalized_limit:
                break
            page += 1

        LOGGER.info("Loaded total %s orders", len(all_items))
        return all_items

    def _extract_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise SalesDriveClientError("Unexpected SalesDrive response type.")

        candidate_keys = ("data", "result", "items", "payments", "rows", "list")
        for key in candidate_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested_items = self._extract_items(value)
                if nested_items:
                    return nested_items

        for value in payload.values():
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value

        return []

    def _extract_total_items(self, payload: Any, items: list[dict[str, Any]]) -> int | None:
        if not isinstance(payload, dict):
            return len(items)

        candidates = ("total", "total_count", "count", "recordsTotal", "items_count")
        for key in candidates:
            value = payload.get(key)
            if isinstance(value, int):
                return value

        meta = payload.get("meta")
        if isinstance(meta, dict):
            for key in candidates:
                value = meta.get(key)
                if isinstance(value, int):
                    return value
        totals = payload.get("totals")
        if isinstance(totals, dict):
            for key in candidates:
                value = totals.get(key)
                if isinstance(value, int):
                    return value
        return None

    def _extract_total_pages(self, payload: Any, limit: int, total_items: int | None) -> int | None:
        if isinstance(payload, dict):
            candidates = ("pages", "total_pages", "pageCount", "last_page")
            for key in candidates:
                value = payload.get(key)
                if isinstance(value, int):
                    return value

            meta = payload.get("meta")
            if isinstance(meta, dict):
                for key in candidates:
                    value = meta.get(key)
                    if isinstance(value, int):
                        return value
            pagination = payload.get("pagination")
            if isinstance(pagination, dict):
                for key in candidates:
                    value = pagination.get(key)
                    if isinstance(value, int):
                        return value
        if total_items is not None and limit > 0:
            return (total_items + limit - 1) // limit
        return None

    def _save_debug_payload(self, payload: Any, payment_type: str, page: int) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        path = self._debug_dir / f"salesdrive_{payment_type}_page_{page}_{timestamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        LOGGER.info("Saved raw SalesDrive response to %s", path)
