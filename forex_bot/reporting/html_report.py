"""HTML report generation: equity curve, drawdown, breakdowns."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .breakdown import per_month_breakdown, per_pair_breakdown, per_session_breakdown
from .metrics import summarize_kpis


def write_html_report(
    out_path: Path,
    title: str,
    trades: pd.DataFrame,
    equity: pd.Series,
    initial: float,
    final: float,
    extra_sections: Optional[dict[str, str]] = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kpis = summarize_kpis(trades, equity, initial, final)
    sess_b = per_session_breakdown(trades).to_html()
    pair_b = per_pair_breakdown(trades).to_html()
    month_b = per_month_breakdown(trades).to_html()
    eq_html = equity.to_frame("equity").to_html() if not equity.empty else "<p>(empty)</p>"
    kpi_rows = "".join(
        f"<tr><th>{k}</th><td>{v if not isinstance(v, float) else round(v, 4)}</td></tr>"
        for k, v in kpis.items()
    )
    extra_html = ""
    if extra_sections:
        for h, body in extra_sections.items():
            extra_html += f"<h2>{h}</h2>{body}"
    html = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>{title}</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;margin:10px 0}} th,td{{border:1px solid #ccc;padding:4px 8px}}
h1,h2{{border-bottom:1px solid #eee}}</style>
</head><body>
<h1>{title}</h1>
<h2>KPIs</h2>
<table>{kpi_rows}</table>
<h2>Per-Session</h2>{sess_b}
<h2>Per-Pair</h2>{pair_b}
<h2>Per-Month</h2>{month_b}
{extra_html}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
