from __future__ import annotations

from pathlib import Path

from payment_analysis.reconciliation.config import SupplierReconciliationSettings


class SupplierReconciliationFileError(RuntimeError):
    pass


class SupplierReconciliationFileLocator:
    def locate(self, settings: SupplierReconciliationSettings, period_key: str) -> Path:
        pattern = self._build_pattern(settings.file_pattern_type, period_key)
        return self.locate_by_pattern(settings.reconciliation_folder, pattern, settings.supplier_name, period_key)

    def locate_from_patterns(self, settings: SupplierReconciliationSettings, period_key: str, patterns: list[str], label: str) -> Path:
        candidates: list[Path] = []
        for pattern_template in patterns:
            pattern = self._build_pattern(pattern_template, period_key)
            candidates.extend(self._collect_candidates(settings.reconciliation_folder, pattern))
        candidates = sorted(set(candidates))
        if not candidates:
            raise SupplierReconciliationFileError(
                f"No {label} reconciliation file found for supplier={settings.supplier_name} period={period_key} in {settings.reconciliation_folder}"
            )
        if len(candidates) > 1:
            raise SupplierReconciliationFileError(
                f"Multiple {label} reconciliation files found for supplier={settings.supplier_name} period={period_key}: "
                + ", ".join(str(path) for path in candidates)
            )
        return candidates[0]

    def locate_by_pattern(self, folder: Path, pattern: str, supplier_name: str, period_key: str) -> Path:
        candidates = self._collect_candidates(folder, pattern)
        if not candidates:
            raise SupplierReconciliationFileError(
                f"No reconciliation file found for supplier={supplier_name} period={period_key} in {folder}"
            )
        if len(candidates) > 1:
            raise SupplierReconciliationFileError(
                f"Multiple reconciliation files found for supplier={supplier_name} period={period_key}: "
                + ", ".join(str(path) for path in candidates)
            )
        return candidates[0]

    def _collect_candidates(self, folder: Path, pattern: str) -> list[Path]:
        return sorted([path for path in folder.glob(f"{pattern}.*") if path.suffix.lower() in {".xls", ".xlsx", ".pdf"}])

    def _build_pattern(self, file_pattern_type: str, period_key: str) -> str:
        year, month = period_key.split("-")
        if file_pattern_type == "MMYYYY":
            return f"{month}{year}"
        if "MMYYYY" in file_pattern_type:
            return file_pattern_type.replace("MMYYYY", f"{month}{year}")
        raise SupplierReconciliationFileError(f"Unsupported file_pattern_type={file_pattern_type}")
