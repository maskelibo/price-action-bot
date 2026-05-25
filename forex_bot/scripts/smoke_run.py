"""End-to-end smoke run with synthetic data — no external dependencies.

Generates 1 year of synthetic 15m bars for 3 pairs, runs through the full pipeline,
and writes a smoke report to reports/forex/smoke_*.html.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..data.quality import run_quality_checks
from ..data.synthetic import generate_synthetic_ohlcv
from ..news.guard import NewsGuard
from ..reporting.compare_crypto import write_comparison_report
from ..reporting.html_report import write_html_report
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import REPORTS_DIR
from ..signals.generator import SignalGenerator, GeneratorConfig
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)


def smoke_run(start: str = "2024-01-01", end: str = "2025-01-01", pairs: list[str] | None = None) -> dict:
    pairs = pairs or ["EURUSD", "GBPUSD", "USDJPY"]
    summary = {}
    for pair in pairs:
        df = generate_synthetic_ohlcv(pair, start, end)
        qr = run_quality_checks(df, pair, "15m")
        print(f"[{pair}] quality: rows={qr.rows} gaps={qr.gaps_internal} weekend={qr.weekend_bars} dst={qr.dst_transitions}")
        strategies = [cls() for cls in (
            LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
            SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
            FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy,
        )]
        news = NewsGuard()
        gen = SignalGenerator(pair=pair, strategies=strategies, config=GeneratorConfig(), news_guard=news)
        signals = gen.generate(df)
        risk = RiskOfficer(RiskConfig())
        engine = BacktestEngine(risk, CostModel(), EngineConfig(), news_guard=news)
        result = engine.run(df, signals, pair=pair)
        summary[pair] = {"n_signals": len(signals), **result.kpis}
        out_html = REPORTS_DIR / f"smoke_{pair}_{datetime.utcnow():%Y%m%d_%H%M%S}.html"
        write_html_report(out_html, f"Smoke — {pair}", result.trades, result.equity_curve,
                          result.initial_balance, result.final_balance)
        print(f"[{pair}] {out_html}")
    out_json = REPORTS_DIR / f"smoke_summary_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n[smoke] wrote {out_json}")
    return summary


if __name__ == "__main__":
    smoke_run()
