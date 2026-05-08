"""Faz 6 Paper Trading Status Report.

Reads paper_journal.duckdb and logs/execution/paper_state_faz6.json
to produce a structured performance report.

Usage:
    python scripts/paper_status_report.py
    python scripts/paper_status_report.py --markdown          # save .md report
    python scripts/paper_status_report.py --journal PATH      # custom journal path
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Production backtest expectation
BACKTEST_ANNUAL_RETURN_PCT = 68.0   # +%68 yearly
BACKTEST_MONTHLY_RETURN_PCT = 68.0 / 12.0  # ~5.6%/month
BACKTEST_WIN_RATE = 0.55            # approximate from walk-forward results
BACKTEST_AVG_R_MULTIPLE = 1.8      # approximate

JOURNAL_PATH = _ROOT / "data" / "paper_journal.duckdb"
PAPER_STATE_PATH = _ROOT / "logs" / "execution" / "paper_state_faz6.json"
LOG_PATH = _ROOT / "logs" / "paper_trading.log"
INITIAL_CAPITAL = 10_000.0


def _get_duckdb_conn(path: Path) -> Any | None:
    try:
        import duckdb  # type: ignore
        if not path.exists():
            return None
        return duckdb.connect(str(path))
    except ImportError:
        return None


def _load_paper_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"balances": {"USDT": INITIAL_CAPITAL}, "positions": [], "realized_pnl_total": 0.0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"balances": {"USDT": INITIAL_CAPITAL}, "positions": [], "realized_pnl_total": 0.0}


def _load_trades(journal_path: Path) -> list[dict[str, Any]]:
    conn = _get_duckdb_conn(journal_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM paper_trades ORDER BY entry_ts"
        ).fetchall()
        cols = [d[0] for d in conn.execute("DESCRIBE paper_trades").fetchall()]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


def _load_equity_snapshots(journal_path: Path) -> list[dict[str, Any]]:
    conn = _get_duckdb_conn(journal_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM paper_equity_snapshots ORDER BY ts"
        ).fetchall()
        cols = [d[0] for d in conn.execute("DESCRIBE paper_equity_snapshots").fetchall()]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


def _parse_log_summaries(log_path: Path) -> list[dict[str, Any]]:
    """Parse JSON lines from paper_trading.log for run history."""
    if not log_path.exists():
        return []
    summaries = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if "run_ts" in data:
                    summaries.append(data)
            except Exception:
                pass
    return summaries


def generate_report(
    journal_path: Path = JOURNAL_PATH,
    paper_state_path: Path = PAPER_STATE_PATH,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, Any]:
    """Generate full performance report. Returns dict of metrics."""
    trades = _load_trades(journal_path)
    snapshots = _load_equity_snapshots(journal_path)
    paper_state = _load_paper_state(paper_state_path)
    log_summaries = _parse_log_summaries(LOG_PATH)

    # ---- Time window ----
    now = datetime.now(timezone.utc)
    first_run_ts = None
    if log_summaries:
        try:
            first_run_ts = datetime.fromisoformat(log_summaries[0]["run_ts"])
        except Exception:
            pass
    if first_run_ts is None and trades:
        try:
            first_run_ts = datetime.fromisoformat(str(trades[0]["entry_ts"]))
        except Exception:
            pass

    days_running = 0
    if first_run_ts:
        days_running = max(1, (now - first_run_ts).days)

    # ---- Current equity ----
    current_equity = float(paper_state["balances"].get("USDT", initial_capital))
    realized_pnl_total = float(paper_state.get("realized_pnl_total", 0.0))
    open_positions_count = len(paper_state.get("positions", []))

    # Estimate unrealized from open positions in paper_state
    unrealized_pnl = 0.0  # Would need live prices to compute properly

    equity_change_pct = ((current_equity - initial_capital) / initial_capital) * 100

    # ---- Trade stats ----
    closed_trades = [t for t in trades if t.get("status") == "closed"]
    open_trades = [t for t in trades if t.get("status") == "open"]
    dry_run_trades = [t for t in trades if t.get("dry_run")]

    wins = [t for t in closed_trades if (t.get("realized_pnl") or 0.0) > 0]
    losses = [t for t in closed_trades if (t.get("realized_pnl") or 0.0) <= 0]

    win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0

    avg_r_multiple = 0.0
    if closed_trades:
        r_vals = [t.get("r_multiple") or 0.0 for t in closed_trades]
        avg_r_multiple = sum(r_vals) / len(r_vals)

    avg_win_usdt = sum(t.get("realized_pnl", 0.0) for t in wins) / len(wins) if wins else 0.0
    avg_loss_usdt = sum(t.get("realized_pnl", 0.0) for t in losses) / len(losses) if losses else 0.0

    # ---- Best/worst trades ----
    sorted_closed = sorted(closed_trades, key=lambda t: t.get("realized_pnl") or 0.0, reverse=True)
    best_3 = sorted_closed[:3]
    worst_3 = sorted_closed[-3:][::-1]

    # ---- Drawdown from equity snapshots ----
    max_equity = initial_capital
    max_dd_pct = 0.0
    current_dd_pct = 0.0
    equity_peak = initial_capital

    equity_history = [initial_capital]
    if snapshots:
        for snap in snapshots:
            eq = float(snap.get("equity") or initial_capital)
            equity_history.append(eq)

    for eq in equity_history:
        if eq > equity_peak:
            equity_peak = eq
        dd = (equity_peak - eq) / equity_peak * 100 if equity_peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd)

    current_dd_pct = (equity_peak - current_equity) / equity_peak * 100 if equity_peak > 0 else 0.0

    # ---- Backtest comparison ----
    if days_running > 0:
        actual_monthly_return_pct = (equity_change_pct / days_running) * 30.0
    else:
        actual_monthly_return_pct = 0.0

    if BACKTEST_MONTHLY_RETURN_PCT != 0:
        return_deviation_pct = abs(
            actual_monthly_return_pct - BACKTEST_MONTHLY_RETURN_PCT
        ) / abs(BACKTEST_MONTHLY_RETURN_PCT) * 100
    else:
        return_deviation_pct = 0.0

    within_20pct_threshold = return_deviation_pct <= 20.0

    # ---- Stopping criteria ----
    four_weeks_done = days_running >= 28
    stopping_criteria_met = four_weeks_done and within_20pct_threshold

    return {
        "report_ts": now.isoformat(),
        "days_running": days_running,
        "initial_capital_usdt": initial_capital,
        "current_equity_usdt": round(current_equity, 2),
        "realized_pnl_total_usdt": round(realized_pnl_total, 2),
        "unrealized_pnl_usdt": round(unrealized_pnl, 2),
        "equity_change_pct": round(equity_change_pct, 2),
        "open_positions": open_positions_count,
        "total_signals_total": len(trades),
        "total_trades_open": len(open_trades),
        "total_trades_closed": len(closed_trades),
        "dry_run_trades": len(dry_run_trades),
        "win_rate": round(win_rate, 4),
        "avg_r_multiple": round(avg_r_multiple, 4),
        "avg_win_usdt": round(avg_win_usdt, 2),
        "avg_loss_usdt": round(avg_loss_usdt, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "current_drawdown_pct": round(current_dd_pct, 2),
        "backtest_comparison": {
            "backtest_annual_return_pct": BACKTEST_ANNUAL_RETURN_PCT,
            "backtest_monthly_return_pct": round(BACKTEST_MONTHLY_RETURN_PCT, 2),
            "actual_monthly_return_pct": round(actual_monthly_return_pct, 2),
            "return_deviation_pct": round(return_deviation_pct, 2),
            "within_20pct_threshold": within_20pct_threshold,
        },
        "stopping_criteria": {
            "four_weeks_done": four_weeks_done,
            "deviation_within_20pct": within_20pct_threshold,
            "all_met": stopping_criteria_met,
        },
        "best_3_trades": [
            {
                "symbol": t.get("symbol"),
                "direction": t.get("side"),
                "realized_pnl": t.get("realized_pnl"),
                "r_multiple": t.get("r_multiple"),
                "exit_reason": t.get("exit_reason"),
            }
            for t in best_3
        ],
        "worst_3_trades": [
            {
                "symbol": t.get("symbol"),
                "direction": t.get("side"),
                "realized_pnl": t.get("realized_pnl"),
                "r_multiple": t.get("r_multiple"),
                "exit_reason": t.get("exit_reason"),
            }
            for t in worst_3
        ],
        "log_runs_total": len(log_summaries),
    }


def format_report_markdown(report: dict[str, Any]) -> str:
    """Format report as Markdown."""
    r = report
    bc = r["backtest_comparison"]
    sc = r["stopping_criteria"]

    lines = [
        "# Faz 6 Paper Trading Status Report",
        f"\n**Generated:** {r['report_ts']}",
        f"**Days Running:** {r['days_running']} / 28 (target)",
        "",
        "## Account Summary",
        f"| Metric | Value |",
        "| --- | --- |",
        f"| Initial Capital | ${r['initial_capital_usdt']:,.2f} USDT |",
        f"| Current Equity | ${r['current_equity_usdt']:,.2f} USDT |",
        f"| Realized P&L | ${r['realized_pnl_total_usdt']:+,.2f} USDT |",
        f"| Equity Change | {r['equity_change_pct']:+.2f}% |",
        f"| Open Positions | {r['open_positions']} |",
        "",
        "## Trade Statistics",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total Trades (Journal) | {r['total_signals_total']} |",
        f"| Open Trades | {r['total_trades_open']} |",
        f"| Closed Trades | {r['total_trades_closed']} |",
        f"| Win Rate | {r['win_rate']:.1%} (backtest: {BACKTEST_WIN_RATE:.1%}) |",
        f"| Avg R-Multiple | {r['avg_r_multiple']:.2f}R (backtest: ~{BACKTEST_AVG_R_MULTIPLE:.1f}R) |",
        f"| Avg Win | ${r['avg_win_usdt']:+.2f} USDT |",
        f"| Avg Loss | ${r['avg_loss_usdt']:+.2f} USDT |",
        "",
        "## Drawdown",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Max Drawdown | {r['max_drawdown_pct']:.2f}% |",
        f"| Current Drawdown | {r['current_drawdown_pct']:.2f}% |",
        f"| Breaker Threshold | 15% monthly / 10% weekly / 5% daily |",
        "",
        "## Backtest Comparison",
        "| Metric | Backtest | Paper |",
        "| --- | --- | --- |",
        f"| Annual Return | {bc['backtest_annual_return_pct']:.1f}% | (extrapolating) |",
        f"| Monthly Return | {bc['backtest_monthly_return_pct']:.2f}% | {bc['actual_monthly_return_pct']:.2f}% |",
        f"| Deviation | — | {bc['return_deviation_pct']:.1f}% |",
        f"| Within 20% threshold | — | {'YES' if bc['within_20pct_threshold'] else 'NO'} |",
        "",
        "## Stopping Criteria (Faz 7 Gate)",
        f"- [{'x' if sc['four_weeks_done'] else ' '}] 4 weeks completed ({r['days_running']}/28 days)",
        f"- [{'x' if sc['deviation_within_20pct'] else ' '}] P&L deviation < 20% from backtest",
        f"- **Gate status: {'PASSED — Ready for Faz 7' if sc['all_met'] else 'IN PROGRESS'}**",
        "",
    ]

    if r["best_3_trades"]:
        lines.extend(["## Top 3 Best Trades", "| Symbol | Dir | P&L | R-Multiple | Exit |"])
        lines.append("| --- | --- | --- | --- | --- |")
        for t in r["best_3_trades"]:
            pnl = t.get("realized_pnl") or 0.0
            rmult = t.get("r_multiple") or 0.0
            lines.append(
                f"| {t.get('symbol', '-')} | {t.get('direction', '-')} | "
                f"${pnl:+.2f} | {rmult:.2f}R | {t.get('exit_reason', '-')} |"
            )
        lines.append("")

    if r["worst_3_trades"]:
        lines.extend(["## Top 3 Worst Trades", "| Symbol | Dir | P&L | R-Multiple | Exit |"])
        lines.append("| --- | --- | --- | --- | --- |")
        for t in r["worst_3_trades"]:
            pnl = t.get("realized_pnl") or 0.0
            rmult = t.get("r_multiple") or 0.0
            lines.append(
                f"| {t.get('symbol', '-')} | {t.get('direction', '-')} | "
                f"${pnl:+.2f} | {rmult:.2f}R | {t.get('exit_reason', '-')} |"
            )
        lines.append("")

    lines.extend([
        "---",
        f"*Strategy: engulfing_continuation v1 | Risk: 2%/trade | Leverage: 1x-5x dynamic*",
        f"*Log runs: {r['log_runs_total']}*",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Faz 6 Paper Trading Status Report"
    )
    parser.add_argument("--journal", type=Path, default=JOURNAL_PATH, help="DuckDB journal path")
    parser.add_argument("--markdown", action="store_true", help="Save markdown report to reports/")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    report = generate_report(journal_path=args.journal)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return

    md = format_report_markdown(report)
    print(md)

    if args.markdown:
        reports_dir = _ROOT / "reports" / "paper"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = reports_dir / f"faz6_status_{ts_str}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    main()
