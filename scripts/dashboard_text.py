"""Text Dashboard MVP — 6-hourly snapshot for paper trading monitor.

Usage:
    python scripts/dashboard_text.py                  # Print to stdout
    python scripts/dashboard_text.py --telegram       # Send to Telegram

Cron entry (6-hourly):
    0 0,6,12,18 * * * cd /path/to/Price Action && python scripts/dashboard_text.py --telegram
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.logging_config import logger


def get_mode() -> str:
    """Get PA_RUN_MODE env var."""
    return os.getenv("PA_RUN_MODE", "unknown").strip()


def get_equity() -> float:
    """Fetch current equity from breaker state or DB (stub)."""
    try:
        from price_action.risk.breaker import DDBreaker

        breaker = DDBreaker()
        # Equity approximated from breaker anchor (not perfect, but available)
        # In real integration, fetch from execution_chief or account state
        if breaker.state.monthly_anchor_equity > 0:
            return breaker.state.monthly_anchor_equity
    except Exception:
        pass
    return 0.0


def get_open_positions() -> list[dict[str, Any]]:
    """Stub: fetch open positions from execution state.

    In real integration, query from DuckDB execution_chief state or exchange.
    Returns list of {symbol, side, notional, R_value}.
    """
    return []


def get_daily_activity() -> dict[str, Any]:
    """Stub: aggregate daily fills and activity."""
    try:
        from price_action.execution.slippage_tracker import SlippageTracker
        from datetime import date

        tracker = SlippageTracker()
        summary = tracker.daily_summary(date.today())
        return {
            "fills": summary.get("n_fills", 0),
            "realized_pnl": summary.get("total_fee_usdt", 0) * -1,  # Stub
            "avg_slippage_bps": summary.get("avg_slippage_bps", 0),
            "alarm_level": summary.get("alarm_level", "OK"),
        }
    except Exception:
        return {"fills": 0, "realized_pnl": 0.0, "avg_slippage_bps": 0.0, "alarm_level": "N/A"}


def get_breaker_status() -> dict[str, Any]:
    """Fetch breaker state snapshot."""
    try:
        from price_action.risk.breaker import DDBreaker

        breaker = DDBreaker()
        daily_loss = (
            -breaker.state.daily_pnl / breaker.state.daily_anchor_equity * 100
            if breaker.state.daily_anchor_equity > 0
            else 0
        )
        weekly_loss = (
            -breaker.state.weekly_pnl / breaker.state.weekly_anchor_equity * 100
            if breaker.state.weekly_anchor_equity > 0
            else 0
        )
        monthly_loss = (
            -breaker.state.monthly_pnl / breaker.state.monthly_anchor_equity * 100
            if breaker.state.monthly_anchor_equity > 0
            else 0
        )
        any_triggered = breaker.any_triggered
        return {
            "daily_dd_pct": daily_loss,
            "weekly_dd_pct": weekly_loss,
            "monthly_dd_pct": monthly_loss,
            "status": "HALTED" if any_triggered else "ACTIVE",
            "triggered_flags": {
                "daily": breaker.state.triggered_daily,
                "weekly": breaker.state.triggered_weekly,
                "monthly": breaker.state.triggered_monthly,
                "consecutive": breaker.state.triggered_consecutive,
            },
        }
    except Exception as e:
        logger.bind(err=str(e)[:100]).debug("dashboard.breaker_fetch_fail")
        return {
            "daily_dd_pct": 0.0,
            "weekly_dd_pct": 0.0,
            "monthly_dd_pct": 0.0,
            "status": "UNKNOWN",
            "triggered_flags": {},
        }


def render_dashboard() -> str:
    """Render text dashboard snapshot."""
    now = datetime.now(timezone.utc)
    mode = get_mode()
    equity = get_equity()
    positions = get_open_positions()
    activity = get_daily_activity()
    breaker = get_breaker_status()

    # Build dashboard
    lines = [
        "=" * 70,
        f"PA Trading Bot Status — {now:%Y-%m-%d %H:%M UTC}",
        "=" * 70,
        "",
        f"Mode: {mode.upper()}",
        f"Equity: ${equity:,.2f} USDT",
        "",
        "POSITIONS (open):",
    ]

    if positions:
        for pos in positions[:10]:  # Top 10
            sym = pos.get("symbol", "?")
            side = pos.get("side", "?")
            notional = pos.get("notional", 0.0)
            r_value = pos.get("R_value", 0.0)
            lines.append(f"  {sym:>8} {side:>5} ${notional:>12,.2f} (R: {r_value:>6.2f})")
        if len(positions) > 10:
            lines.append(f"  ... +{len(positions) - 10} more")
    else:
        lines.append("  (none)")

    lines.extend([
        "",
        "TODAY'S ACTIVITY:",
        f"  Signals Scanned: N/A",
        f"  Fills: {activity['fills']}",
        f"  Realized PnL: ${activity['realized_pnl']:+,.2f}",
        f"  Avg Slippage: {activity['avg_slippage_bps']:.1f} bps",
        f"  Status: {activity['alarm_level']}",
        "",
        "RISK STATE:",
        f"  Daily DD: {breaker['daily_dd_pct']:>6.1f}%",
        f"  Weekly DD: {breaker['weekly_dd_pct']:>6.1f}%",
        f"  Monthly DD: {breaker['monthly_dd_pct']:>6.1f}%",
        f"  Breaker: {breaker['status']}",
    ])

    # Trigger details if any
    flags = breaker.get("triggered_flags", {})
    if any(flags.values()):
        lines.extend([
            "",
            "BREAKER TRIGGERS (active):",
        ])
        if flags.get("daily"):
            lines.append(f"  ⚠️  DAILY ({breaker['daily_dd_pct']:.1f}%)")
        if flags.get("weekly"):
            lines.append(f"  ⚠️  WEEKLY ({breaker['weekly_dd_pct']:.1f}%)")
        if flags.get("monthly"):
            lines.append(f"  ⚠️  MONTHLY ({breaker['monthly_dd_pct']:.1f}%)")
        if flags.get("consecutive"):
            lines.append(f"  ⚠️  CONSECUTIVE_LOSSES")

    lines.extend([
        "",
        "=" * 70,
    ])

    return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    dashboard_text = render_dashboard()

    if "--telegram" in sys.argv:
        # Send to Telegram
        try:
            from price_action.notifications.telegram import send_telegram

            if send_telegram(dashboard_text):
                print("Dashboard sent to Telegram", file=sys.stderr)
            else:
                print("Failed to send dashboard to Telegram", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Telegram send error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Print to stdout
        print(dashboard_text)


if __name__ == "__main__":
    main()
