"""Paper trading daemon — Phase 5 readiness.

Loops every 15min boundary:
 1. Fetch latest bar (paper: synthetic + real cache; live: broker tick stream)
 2. Run signal generator across pairs
 3. RiskOfficer evaluate → OrderRouter route → PaperBroker fill
 4. Update DDBreaker via TradeJournal realized PnL
 5. Heartbeat → DMS
 6. Telegram throttle alerts on critical events

Usage:
  python -m forex_bot.scripts.paper_daemon --pairs USDJPY --interval 60
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..backtest.costs import CostModel
from ..data.store import OHLCVStore
from ..data.synthetic import generate_synthetic_ohlcv
from ..execution import (
    CapitalCap, DeadMansSwitch, IdempotencyStore, OrderRouter, PaperBroker,
    SlippageTracker, TradeJournal,
)
from ..logging_config import setup_logging
from ..news.guard import NewsGuard
from ..ops.telegram_throttle import TelegramThrottle
from ..risk.officer import AccountState, RiskConfig, RiskOfficer
from ..settings import DUCKDB_PATH, LOGS_DIR, PAIRS, PARQUET_DIR, REPORTS_DIR
from ..signals.generator import GeneratorConfig, SignalGenerator
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)

logger = logging.getLogger(__name__)

STRATS = (
    LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
    SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
    FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy,
)


class PaperDaemon:
    def __init__(self, pairs: list[str], interval_sec: int = 900):
        self.pairs = pairs
        self.interval_sec = interval_sec
        self.broker = PaperBroker(initial_balance_usd=10_000.0)
        self.broker.connect()
        self.idempotency = IdempotencyStore(db_path=LOGS_DIR / "forex_idempotency.duckdb")
        self.trade_journal = TradeJournal(db_path=LOGS_DIR / "forex_journal.duckdb")
        self.slippage = SlippageTracker(db_path=LOGS_DIR / "forex_slippage.duckdb",
                                         alarm_cb=self._alert)
        self.throttle = TelegramThrottle(send_fn=lambda m: logger.warning("[ALERT] %s", m))
        self.news = NewsGuard()
        self.risk = RiskOfficer(RiskConfig(), news_guard=self.news,
                                 breaker_state_path=LOGS_DIR / "forex_breaker_state.json")
        self.router = OrderRouter(self.broker, self.risk, self.idempotency)
        self.dms = DeadMansSwitch(self.broker, heartbeat_path=LOGS_DIR / "forex_heartbeat",
                                   kill_switch_path=LOGS_DIR / "forex_kill_switch.json",
                                   timeout_sec=300, heartbeat_interval_sec=30,
                                   alarm_cb=self._alert)
        self.capital_cap = CapitalCap.from_env()
        self._stop = False
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_stop", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))

    def _alert(self, msg: str) -> None:
        self.throttle.send_throttled("daemon_alert", msg, level="CRITICAL")

    def run(self):
        self.dms.start()
        logger.info("paper daemon started pairs=%s interval=%ds", self.pairs, self.interval_sec)
        store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
        while not self._stop:
            try:
                self._scan_iteration(store)
            except Exception as e:
                logger.exception("scan iteration failed: %s", e)
                self._alert(f"scan iteration error: {e}")
            for _ in range(self.interval_sec):
                if self._stop:
                    break
                time.sleep(1)
        self.dms.stop()
        logger.info("daemon stopped")

    def _scan_iteration(self, store: OHLCVStore):
        if self.dms.is_halted():
            logger.warning("DMS halted — skipping iteration")
            return
        now = datetime.now(timezone.utc)
        for pair in self.pairs:
            df = store.read_ohlcv(pair, "15m")
            if df.empty:
                logger.warning("[%s] no data; skipping", pair)
                continue
            strategies = [cls() for cls in STRATS]
            gen = SignalGenerator(pair=pair, strategies=strategies,
                                   config=GeneratorConfig(), news_guard=self.news)
            signals = gen.generate(df.tail(500))  # last ~5 days
            if not signals:
                continue
            latest_signal = signals[-1]
            account = AccountState(
                equity_usd=self.broker.equity_usd({}),
                free_margin_usd=self.broker.balance_usd(),
                open_positions={p.pair: {"side": p.side, "lots": p.lots,
                                          "notional": p.lots * 100_000.0}
                                for p in self.broker.positions()},
                mode="paper",
            )
            # capital cap check
            allow_cap, cap_reason = self.capital_cap.check("paper", account.equity_usd)
            if not allow_cap:
                logger.warning("capital cap reject: %s", cap_reason)
                continue
            status, fill, rej, decision = self.router.route(
                latest_signal, account, now, df["close"].iloc[-1],
            )
            if status == "filled" and fill:
                self.trade_journal  # noqa (placeholder; close events go here on TP/SL hit)
                self.slippage.record_fill(pair, latest_signal.side,
                                           latest_signal.entry_price, fill.fill_price,
                                           decision.lots if decision else 0.0, ts=now)
                self.throttle.send_throttled("trade_filled",
                    f"{pair} {latest_signal.side} {decision.lots if decision else 0:.2f} lots @ {fill.fill_price:.5f}",
                    level="INFO")
            elif status == "rejected" and rej:
                logger.info("[%s] rejected: %s/%s", pair, rej.rejected_by, rej.reason)
        self.dms.heartbeat()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", default="USDJPY", help="comma-separated, default USDJPY (best edge)")
    p.add_argument("--interval", type=int, default=900, help="loop interval in seconds")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()
    setup_logging(level=getattr(logging, args.log_level))
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    daemon = PaperDaemon(pairs=pairs, interval_sec=args.interval)
    daemon.run()


if __name__ == "__main__":
    main()
