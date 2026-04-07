from __future__ import annotations

import argparse
from calendar import monthrange
from pathlib import Path
from datetime import datetime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze SalesDrive payments.")
    parser.add_argument("--type", choices=["incoming", "outcoming", "all"], required=True)
    parser.add_argument("--month", help='Reporting month in format "YYYY-MM"')
    parser.add_argument("--date-from", help='Example: "2025-03-01 00:00:00"')
    parser.add_argument("--date-to", help='Example: "2025-03-31 23:59:59"')
    parser.add_argument("--output", help="Path to Excel report")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    from payment_analysis.config import load_settings
    from payment_analysis.logging_setup import configure_logging
    from payment_analysis.services.payment_analysis_service import PaymentAnalysisService
    import yaml

    configure_logging()
    settings = load_settings()
    analysis_settings = yaml.safe_load(settings.analysis_settings_path.read_text(encoding="utf-8")) or {}
    default_month = ((analysis_settings.get("default_period") or {}).get("month") or "").strip()

    period_month = args.month or default_month
    if period_month:
        date_from, date_to, period_label = resolve_month_period(period_month)
    elif args.date_from and args.date_to:
        date_from, date_to = args.date_from, args.date_to
        period_label = sanitize_period_label(date_from, date_to)
    else:
        raise ValueError("Provide --month or both --date-from and --date-to.")

    output_path = Path(args.output) if args.output else build_default_output_path(settings, analysis_settings, period_label)
    service = PaymentAnalysisService(settings)
    artifacts = service.run(
        payment_type=args.type,
        date_from=date_from,
        date_to=date_to,
        output_path=output_path,
        period_label=period_label,
    )
    print(
        f"Report saved to {artifacts.report_path}. "
        f"Incoming={artifacts.incoming_count}, "
        f"Outcoming={artifacts.outcoming_count}, "
        f"Unmapped counterparties={artifacts.unmapped_count}."
    )
    return 0


def resolve_month_period(period_month: str) -> tuple[str, str, str]:
    month_dt = datetime.strptime(period_month, "%Y-%m")
    last_day = monthrange(month_dt.year, month_dt.month)[1]
    date_from = f"{period_month}-01 00:00:00"
    date_to = f"{period_month}-{last_day:02d} 23:59:59"
    return date_from, date_to, period_month.replace("-", "_")


def build_default_output_path(settings, analysis_settings: dict, period_label: str) -> Path:
    reports_cfg = analysis_settings.get("reports", {})
    output_dir = Path(reports_cfg.get("output_dir", settings.reports_dir))
    filename_template = reports_cfg.get("filename_template", "payment_report_{period_label}.xlsx")
    return output_dir / filename_template.format(period_label=period_label)


def sanitize_period_label(date_from: str, date_to: str) -> str:
    return f"{date_from[:10].replace('-', '_')}_{date_to[:10].replace('-', '_')}"
