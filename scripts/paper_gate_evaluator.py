#!/usr/bin/env python3
"""SEC54.7: Paper Gate Evaluator — Cron job (hourly).

Runs on cron: 0 * * * * python scripts/paper_gate_evaluator.py

Evaluates K2 + K3 (and future K1-K6) gates every hour.
- K2 trigger → activate kill switch (HARD KILL)
- K3 trigger → send alert only (manual review, daemon continues)

Setup:
  1. Load paper gate config from risk_phoenix_v204.yaml (paper_trading section)
  2. Create TradeJournal instance (futures_journal.duckdb)
  3. Get TelegramThrottle singleton
  4. Evaluate all gates
  5. For HALT actions: write kill_switch.json {halted: true, reason: "K#: ..."}
  6. Log results
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Setup logging dir
KILL_SWITCH_PATH = ROOT / "logs" / "kill_switch.json"
LOG_DIR = ROOT / "logs"

# Ensure logs dir exists
LOG_DIR.mkdir(parents=True, exist_ok=True)

def main() -> int:
    """Main entry point."""
    try:
        from price_action.ops import PaperGate, PaperGateConfig, get_telegram_throttle
        from price_action.execution.trade_journal import TradeJournal
        from price_action.settings import get_settings
        from price_action.logging_config import logger
        import yaml

        # Load config
        settings = get_settings()
        config_path = ROOT / "configs" / "risk_phoenix_v204.yaml"

        if not config_path.exists():
            logger.bind(config_path=str(config_path)).error("paper_gate_evaluator.config_not_found")
            return 1

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        paper_config_data = config_data.get("paper_trading", {})
        if not paper_config_data.get("enabled", False):
            # Paper trading disabled — no-op
            logger.debug("paper_gate_evaluator.paper_trading_disabled")
            return 0

        # Parse start date
        start_date_str = paper_config_data.get("start_date", "2026-05-25")
        try:
            start_date = datetime.fromisoformat(start_date_str).replace(tzinfo=timezone.utc)
        except Exception as exc:
            logger.bind(err=str(exc), start_date=start_date_str).error("paper_gate_evaluator.parse_date_fail")
            return 1

        # Create gate config
        gate_config = PaperGateConfig(
            paper_start_date=start_date,
            cap_usd=float(paper_config_data.get("cap_usdt", 1000.0)),
            k2_max_neg_months_first_30d=int(paper_config_data.get("k2_max_neg_months_first_30d", 1)),
            k3_min_monthly_roi_pct=float(paper_config_data.get("k3_min_monthly_roi_pct", 15.0)),
        )

        # Create journal + gate
        journal = TradeJournal(db_path=ROOT / "data" / "futures_journal.duckdb")
        telegram = get_telegram_throttle()

        gate = PaperGate(gate_config, journal, telegram)

        # Evaluate all gates
        now = datetime.now(timezone.utc)
        results = gate.evaluate_all(now)

        # Process results
        halt_triggered = False
        halt_reason = ""

        for result in results:
            if result.action == "HALT":
                halt_triggered = True
                halt_reason = f"{result.switch}: {result.reason}"
                logger.bind(
                    switch=result.switch,
                    reason=result.reason,
                    metric=result.metric_value,
                    threshold=result.threshold,
                ).critical("paper_gate_evaluator.halt_triggered")

            elif result.action == "ALERT":
                logger.bind(
                    switch=result.switch,
                    reason=result.reason,
                    metric=result.metric_value,
                    threshold=result.threshold,
                ).warning("paper_gate_evaluator.alert_triggered")

        # If any HALT triggered, write kill_switch.json
        if halt_triggered:
            kill_switch_data = {
                "halted": True,
                "reason": halt_reason,
                "triggered_at": now.isoformat(),
                "trigger_gates": [r.switch for r in results if r.action == "HALT"],
            }
            try:
                KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(KILL_SWITCH_PATH, "w", encoding="utf-8") as f:
                    json.dump(kill_switch_data, f, indent=2)
                logger.bind(kill_switch_path=str(KILL_SWITCH_PATH)).info(
                    "paper_gate_evaluator.kill_switch_written"
                )
            except Exception as exc:
                logger.bind(err=str(exc)).error("paper_gate_evaluator.kill_switch_write_fail")
                return 1

        logger.info("paper_gate_evaluator.complete")
        return 0

    except Exception as exc:
        import traceback

        print(f"FATAL: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
