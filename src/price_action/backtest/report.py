"""HTML rapor üreticisi (jinja2)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from price_action.backtest.engine import BacktestResult
from price_action.logging_config import logger

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest Report — {{ result.strategy_name }}</title>
<style>
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1d1d1f; }
h1, h2 { border-bottom: 1px solid #ddd; padding-bottom: 0.4rem; }
table { border-collapse: collapse; margin: 1rem 0; }
td, th { padding: 0.4rem 0.7rem; border: 1px solid #ddd; text-align: left; }
th { background: #f5f5f7; }
.kpi-pos { color: #007a33; font-weight: 600; }
.kpi-neg { color: #c0392b; font-weight: 600; }
.small { color: #666; font-size: 0.9rem; }
pre { background: #f5f5f7; padding: 1rem; overflow-x: auto; }
.row { display: flex; flex-wrap: wrap; gap: 1rem; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; min-width: 220px; }
</style>
</head>
<body>
  <h1>Backtest Report — {{ result.strategy_name }}</h1>
  <div class="small">
    {{ result.start.isoformat() }} → {{ result.end.isoformat() }} ({{ result.timeframe }})
    | manifest <code>{{ result.manifest.composite }}</code>
    | runtime {{ "%.2f"|format(result.elapsed_sec) }}s
  </div>

  <h2>KPIs</h2>
  <div class="row">
    {% for k, v in result.kpis.items() %}
    <div class="card">
      <div class="small">{{ k }}</div>
      <div class="{{ 'kpi-pos' if v >= 0 else 'kpi-neg' }}">
        {{ "%.4f"|format(v) if v is number else v }}
      </div>
    </div>
    {% endfor %}
  </div>

  <h2>Equity Curve</h2>
  <table>
    <tr><th>ts</th><th>equity</th></tr>
    {% for ts, val in equity_rows %}
    <tr><td>{{ ts }}</td><td>{{ "%.2f"|format(val) }}</td></tr>
    {% endfor %}
  </table>

  <h2>Per-Symbol P&L</h2>
  <table>
    <tr><th>symbol</th><th>n_trades</th><th>net</th><th>win_rate</th></tr>
    {% for row in per_symbol %}
    <tr>
      <td>{{ row.symbol }}</td>
      <td>{{ row.n_trades }}</td>
      <td>{{ "%.2f"|format(row.net) }}</td>
      <td>{{ "%.2f%%"|format(row.win_rate * 100) }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Trades</h2>
  <table>
    <tr>
      <th>ts</th><th>sym</th><th>side</th><th>entry</th><th>exit</th>
      <th>qty</th><th>pnl</th><th>R</th><th>pattern</th>
    </tr>
    {% for tr in trades_rows %}
    <tr>
      <td>{{ tr.entry_ts }}</td>
      <td>{{ tr.symbol }}</td>
      <td>{{ tr.side }}</td>
      <td>{{ "%.4f"|format(tr.entry_price) }}</td>
      <td>{{ "%.4f"|format(tr.exit_price) }}</td>
      <td>{{ "%.4f"|format(tr.quantity) }}</td>
      <td class="{{ 'kpi-pos' if tr.realized_pnl_usdt >= 0 else 'kpi-neg' }}">
        {{ "%.2f"|format(tr.realized_pnl_usdt) }}
      </td>
      <td>{{ "%.2f"|format(tr.realized_r_multiple) }}</td>
      <td>{{ tr.pattern_id }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""


def render_report(result: BacktestResult, out_path: str | Path) -> Path:
    """Backtest sonucunu HTML rapora dönüştür."""
    try:
        from jinja2 import Template  # type: ignore
        tmpl = Template(_TEMPLATE)
    except ImportError:  # pragma: no cover
        tmpl = _MiniTemplate(_TEMPLATE)

    equity_rows = [(str(ts), float(v)) for ts, v in result.equity_curve.items()]
    trades_rows = result.trades.to_dict("records") if not result.trades.empty else []
    per_symbol = _per_symbol(trades_rows)

    html = tmpl.render(
        result=result,
        equity_rows=equity_rows[-200:],  # son 200 satır rapor için yeterli
        trades_rows=trades_rows[-500:],
        per_symbol=per_symbol,
    )
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    logger.bind(path=str(p), trades=len(trades_rows)).info("report.rendered")
    return p


def _per_symbol(trades_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in trades_rows:
        by.setdefault(r["symbol"], []).append(r)
    out = []
    for sym, rows in by.items():
        net = sum(r["realized_pnl_usdt"] for r in rows)
        wins = sum(1 for r in rows if r["realized_pnl_usdt"] > 0)
        out.append(
            {
                "symbol": sym,
                "n_trades": len(rows),
                "net": net,
                "win_rate": wins / len(rows) if rows else 0.0,
            }
        )
    out.sort(key=lambda x: x["net"], reverse=True)
    return out


# Mini fallback template — jinja2 yoksa
class _MiniTemplate:
    def __init__(self, src: str) -> None:
        self.src = src

    def render(self, **kwargs: Any) -> str:
        out = self.src
        for k, v in kwargs.items():
            out = out.replace("{{ " + k + " }}", str(v))
        return out
