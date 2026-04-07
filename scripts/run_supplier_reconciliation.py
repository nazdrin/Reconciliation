from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run supplier reconciliation against SalesDrive and supplier act files.")
    parser.add_argument("--supplier", required=True, help='Supplier key from config, for example "biotus"')
    parser.add_argument("--period", required=True, help='Reconciliation period in format "YYYY-MM"')
    parser.add_argument("--output", help="Path to output Excel report")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    from payment_analysis.config import load_settings
    from payment_analysis.logging_setup import configure_logging
    from payment_analysis.reconciliation.service import SupplierReconciliationService

    configure_logging()
    settings = load_settings()
    service = SupplierReconciliationService(settings)
    output_path = Path(args.output) if args.output else settings.reports_dir / f"{args.supplier}_reconciliation_{args.period.replace('-', '_')}.xlsx"
    artifacts = service.run(supplier_name=args.supplier, period_key=args.period, output_path=output_path)
    print(
        f"Supplier reconciliation report saved to {artifacts.report_path}. "
        f"Supplier={artifacts.supplier_name}, Period={artifacts.period_key}, "
        f"Warnings={artifacts.warnings_count}, Issues={artifacts.issues_count}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
