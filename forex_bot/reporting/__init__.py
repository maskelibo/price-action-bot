"""Reporting: per-pair/session/month breakdown, HTML, JSON, crypto comparison."""
from .metrics import summarize_kpis
from .breakdown import per_session_breakdown, per_pair_breakdown, per_month_breakdown
from .html_report import write_html_report
from .compare_crypto import write_comparison_report

__all__ = [
    "summarize_kpis", "per_session_breakdown", "per_pair_breakdown", "per_month_breakdown",
    "write_html_report", "write_comparison_report",
]
