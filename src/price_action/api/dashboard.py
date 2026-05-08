"""Basit Jinja2 + Plotly tabanlı operasyonel dashboard.

Plotly CDN'den yüklenir; sunucu tarafı sadece veri sağlar.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
from jinja2 import Template

from price_action import __version__

_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Price Action Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
    <style>
        body { font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
               margin: 24px; color: #222; }
        h1 { margin-top: 0; }
        .kpi { display: inline-block; padding: 12px 18px; margin: 4px;
               background: #f4f4f7; border-radius: 8px; min-width: 120px; }
        .kpi b { display: block; font-size: 20px; }
        .kpi span { font-size: 12px; color: #666; }
        table { border-collapse: collapse; margin-top: 12px; }
        th, td { padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 13px; }
        th { background: #fafafa; text-align: left; }
        .footer { margin-top: 32px; color: #888; font-size: 12px; }
    </style>
</head>
<body>
    <h1>Price Action — Operations Dashboard</h1>
    <p>v{{ version }} — {{ now }}</p>

    <h2>KPI Snapshot</h2>
    <div>
        <div class="kpi"><b>{{ kpi.n_trades }}</b><span>Trades</span></div>
        <div class="kpi"><b>{{ "%.1f"|format(kpi.net_pnl_usdt) }}</b><span>Net PnL (USDT)</span></div>
        <div class="kpi"><b>{{ "%.2f"|format(kpi.sharpe) }}</b><span>Sharpe</span></div>
        <div class="kpi"><b>{{ "%.2f"|format(kpi.profit_factor) }}</b><span>Profit Factor</span></div>
        <div class="kpi"><b>{{ "%.0f"|format(kpi.win_rate * 100) }}%</b><span>Win rate</span></div>
        <div class="kpi"><b>{{ "%.1f"|format(kpi.max_drawdown * 100) }}%</b><span>Max DD</span></div>
    </div>

    <h2>Equity Curve</h2>
    <div id="equity" style="width:100%; height:380px;"></div>

    <h2>Recent Trades</h2>
    {% if trades %}
    <table>
        <tr><th>Exit</th><th>Symbol</th><th>Side</th><th>R</th><th>PnL</th><th>Strategy</th></tr>
        {% for t in trades %}
        <tr>
            <td>{{ t.exit_ts }}</td>
            <td>{{ t.symbol }}</td>
            <td>{{ t.side }}</td>
            <td>{{ "%.2f"|format(t.realized_r_multiple) }}</td>
            <td>{{ "%.2f"|format(t.realized_pnl_usdt) }}</td>
            <td>{{ t.strategy_id }}</td>
        </tr>
        {% endfor %}
    </table>
    {% else %}
    <p><em>henüz trade yok</em></p>
    {% endif %}

    <p class="footer">Price Action Co. — local dashboard.</p>

    <script>
    const equityData = {{ equity_json|safe }};
    Plotly.newPlot("equity", [{
        x: equityData.x,
        y: equityData.y,
        type: "scatter",
        mode: "lines",
        line: { color: "#2a6df4" }
    }], {
        margin: {t: 10, l: 50, r: 20, b: 40},
        yaxis: {title: "Equity (USDT)"},
        xaxis: {title: "Time"}
    }, {responsive: true});
    </script>
</body>
</html>
"""
)


def render_dashboard(trades_df: pd.DataFrame | None = None) -> str:
    from datetime import datetime as _dt, timezone as _tz

    from price_action.analytics.kpi import compute_kpis

    if trades_df is None or trades_df.empty:
        kpi = {
            "n_trades": 0,
            "net_pnl_usdt": 0.0,
            "sharpe": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
        }
        equity_json = json.dumps({"x": [], "y": []})
        trades_list: list[dict[str, Any]] = []
    else:
        kpi = compute_kpis(trades_df)
        df = trades_df.sort_values("exit_ts").copy()
        df["equity"] = 10_000.0 + df["realized_pnl_usdt"].fillna(0).cumsum()
        equity_json = json.dumps(
            {
                "x": [str(t) for t in df["exit_ts"].tolist()],
                "y": [float(v) for v in df["equity"].tolist()],
            }
        )
        trades_list = df.tail(20).to_dict(orient="records")

    return _TEMPLATE.render(
        version=__version__,
        now=_dt.now(_tz.utc).isoformat(timespec="seconds"),
        kpi=kpi,
        equity_json=equity_json,
        trades=trades_list,
    )
