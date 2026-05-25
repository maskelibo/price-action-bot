"""Crypto bot vs forex bot side-by-side comparison report."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def write_comparison_report(
    out_path: Path,
    crypto_kpis: dict,
    forex_kpis: dict,
    rationale: Optional[str] = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    keys = ["return_total_pct", "cagr_pct", "max_dd_pct", "sharpe", "sortino", "calmar",
            "win_rate", "profit_factor", "expectancy_r", "n_trades"]

    def _row(k):
        c = crypto_kpis.get(k, "—")
        f = forex_kpis.get(k, "—")
        return f"<tr><th>{k}</th><td>{c}</td><td>{f}</td></tr>"

    rows = "".join(_row(k) for k in keys)
    rationale_html = f"<h2>Why the delta?</h2><pre>{rationale}</pre>" if rationale else ""
    html = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Crypto vs Forex — Side-by-Side</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;margin:10px 0}} th,td{{border:1px solid #ccc;padding:6px 12px}}</style>
</head><body>
<h1>Crypto Bot vs Forex Bot</h1>
<table>
<thead><tr><th>KPI</th><th>Crypto (15m)</th><th>Forex (15m)</th></tr></thead>
<tbody>{rows}</tbody>
</table>
{rationale_html}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
