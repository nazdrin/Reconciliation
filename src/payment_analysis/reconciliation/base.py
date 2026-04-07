from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from payment_analysis.reconciliation.models import SupplierReconciliationRecord


class SupplierReconciliationProvider(ABC):
    @abstractmethod
    def parse_file(self, file_path: Path, period_key: str) -> list[SupplierReconciliationRecord]:
        raise NotImplementedError
