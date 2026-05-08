"""Morning Smoke — Sistem 'sabah uyandığında çalışıyor mu?' hızlı kontrolü.

Ne yapar:
1. Tüm modüller import edilebiliyor mu?
2. Sentetik OHLCV ile pattern detector'lar çalışıyor mu?
3. Risk Officer bir sinyali değerlendirip RiskedOrder döndürüyor mu?
4. LLM dry-run mock cevap üretiyor mu?
5. Memory katmanı okunabiliyor mu?
6. Klasör yapısı bütün mü?

Çalıştırma (proje kökünden):
    PYTHONPATH=src PA_LLM_DRY_RUN=true python scripts/morning_smoke.py
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ------------------------------------------------------------------------
# 1) Modül smoke
# ------------------------------------------------------------------------

MODULES = [
    "price_action.contracts",
    "price_action.settings",
    "price_action.logging_config",
    "price_action.data.store",
    "price_action.data.quality",
    "price_action.data.universe",
    "price_action.signals.candles",
    "price_action.signals.structure",
    "price_action.signals.confluence",
    "price_action.strategies.classic_pa",
    "price_action.risk.sizing",
    "price_action.risk.gates",
    "price_action.portfolio.allocator",
    "price_action.backtest.engine",
    "price_action.backtest.walk_forward",
    "price_action.execution.ccxt_paper",
    "price_action.memory.store",
    "price_action.memory.episodic",
    "price_action.rag.store",
    "price_action.rag.retrieve",
    "price_action.agents.base",
    "price_action.agents.ceo",
    "price_action.agents.researcher",
    "price_action.agents.analyst",
    "price_action.agents.lab_scientist",
    "price_action.agents.ops_engineer",
    "price_action.orchestrator.scheduler",
    "price_action.analytics.kpi",
    "price_action.api.server",
    "price_action.cli",
]


def step_modules() -> int:
    print("\n[1/6] Modül import smoke testi")
    failed = 0
    for m in MODULES:
        try:
            importlib.import_module(m)
            print(f"  OK   {m}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {m}: {type(e).__name__}: {e}")
            failed += 1
    if failed:
        print(f"  -> {failed} modül başarısız")
    else:
        print(f"  -> {len(MODULES)} modül OK")
    return failed


# ------------------------------------------------------------------------
# 2) Pattern detector smoke
# ------------------------------------------------------------------------

def step_signals() -> int:
    print("\n[2/6] Pattern detector smoke testi")
    try:
        import numpy as np
        import pandas as pd

        from price_action.signals.candles import bullish_pin_bar
        from price_action.signals.structure import atr, ema

        np.random.seed(42)
        n = 100
        ts = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "open": close + np.random.randn(n) * 0.3,
                "high": close + np.abs(np.random.randn(n)),
                "low": close - np.abs(np.random.randn(n)),
                "close": close,
                "volume": 1e6,
            },
            index=ts,
        )
        a = atr(df).iloc[-1]
        e = ema(df["close"], 50).iloc[-1]
        pin = bullish_pin_bar(df).sum()
        print(f"  ATR(14) son bar: {a:.3f}")
        print(f"  EMA(50) son bar: {e:.3f}")
        print(f"  Bullish pin bar tespit: {int(pin)} adet (sentetik)")

        # Lookahead causality
        full = bullish_pin_bar(df)
        truncated = bullish_pin_bar(df.iloc[: 50 + 1])
        if bool(full.iloc[50]) != bool(truncated.iloc[50]):
            print("  FAIL Lookahead test — t indeksinde tutarsız çıktı")
            return 1
        print("  Lookahead causality test OK")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1


# ------------------------------------------------------------------------
# 3) Risk Officer smoke
# ------------------------------------------------------------------------

def step_risk() -> int:
    print("\n[3/6] Risk Officer smoke testi")
    try:
        import yaml

        from price_action.contracts import Signal
        from price_action.risk.breaker import DDBreaker
        from price_action.risk.sizing import AccountState, RiskOfficer

        cfg = yaml.safe_load((ROOT / "configs" / "risk.yaml").read_text(encoding="utf-8"))
        br = DDBreaker(cfg["drawdown_breakers"], state_path=ROOT / "data" / "br_smoke.json")
        ro = RiskOfficer(cfg, breaker=br)
        sig = Signal(
            ts=datetime(2024, 6, 1, tzinfo=timezone.utc),
            venue="binance",
            symbol="BTC/USDT",
            timeframe="1d",
            direction="long",
            pattern_id="bullish_pin_bar",
            confluence_score=2.5,
            sl_price=92.0,
            tp_price=116.0,
            suggested_size_atr=4.0,
            metadata={"atr14": 2.0},
        )
        acct = AccountState(equity_usdt=10_000, free_margin_usdt=10_000)
        out = ro.evaluate(sig, acct, market_price=100.0, atr=2.0)
        kind = type(out).__name__
        print(f"  Çıktı tipi: {kind}")
        if hasattr(out, "quantity"):
            print(f"  qty={out.quantity:.2f}, notional=${out.notional_usdt:.2f}, leverage={out.leverage:.2f}")
            print(f"  SL={out.sl_price}, TPs={[(t.price, t.fraction) for t in out.tp_levels]}")
            return 0
        print(f"  Reject sebebi: {out.reason}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1


# ------------------------------------------------------------------------
# 4) LLM dry-run smoke
# ------------------------------------------------------------------------

def step_llm() -> int:
    print("\n[4/6] LLM dry-run smoke testi")
    try:
        import os

        os.environ.setdefault("PA_LLM_DRY_RUN", "true")
        from price_action.agents.ceo import CEOAgent

        async def _run() -> str:
            ceo = CEOAgent()
            return await ceo.run("Smoke test prompt", max_tokens=50)

        resp = asyncio.run(_run())
        print(f"  CEO dry-run cevap (ilk 100 ch): {resp[:100]}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1


# ------------------------------------------------------------------------
# 5) Memory katmanı smoke
# ------------------------------------------------------------------------

def step_memory() -> int:
    print("\n[5/6] Memory layer smoke testi")
    try:
        from price_action.memory.store import MemoryStore

        m = MemoryStore()
        ceo_id = m.read_identity("ceo")
        sf = m.read_shared_facts()
        print(f"  CEO identity uzunluğu: {len(ceo_id)} char")
        print(f"  Shared facts dosya sayısı: {len(sf)}")
        boot = m.boot_context("ceo")
        print(f"  Boot context uzunluğu: {len(boot)} char")
        if not ceo_id or not boot:
            return 1
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1


# ------------------------------------------------------------------------
# 6) Klasör yapısı
# ------------------------------------------------------------------------

REQUIRED_DIRS = [
    "agents",
    "memory/ceo",
    "memory/researcher",
    "memory/analyst",
    "memory/lab_scientist",
    "memory/ops_engineer",
    "memory/shared/facts",
    "memory/shared/lessons",
    "memory/shared/decisions",
    "knowledge",
    "knowledge/books",
    "configs",
    "configs/strategies",
    "src/price_action",
    "tests",
    "scripts",
]
REQUIRED_FILES = [
    "README.md",
    "ARCHITECTURE.md",
    "RUNBOOK.md",
    "pyproject.toml",
    "docker-compose.yml",
    ".env.example",
    "configs/symbols.yaml",
    "configs/risk.yaml",
    "configs/strategies/classic_pa.yaml",
    "knowledge/seeds.yaml",
    "agents/ceo.md",
    "agents/researcher.md",
    "memory/shared/glossary.md",
]


def step_filesystem() -> int:
    print("\n[6/6] Klasör/dosya bütünlüğü")
    missing = 0
    for d in REQUIRED_DIRS:
        if not (ROOT / d).is_dir():
            print(f"  MISSING DIR  {d}")
            missing += 1
    for f in REQUIRED_FILES:
        if not (ROOT / f).is_file():
            print(f"  MISSING FILE {f}")
            missing += 1
    if missing == 0:
        print(f"  -> Tüm {len(REQUIRED_DIRS)} dir + {len(REQUIRED_FILES)} dosya OK")
    return missing


# ------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("Price Action — Morning Smoke Test")
    print("=" * 70)

    failures = 0
    failures += step_modules()
    failures += step_signals()
    failures += step_risk()
    failures += step_llm()
    failures += step_memory()
    failures += step_filesystem()

    print("\n" + "=" * 70)
    if failures == 0:
        print("OK — Sistem ayağa kalktı, ilk ingest'e hazır.")
        print("Sonraki adım: RUNBOOK.md adım 3 (ingest_ccxt).")
        return 0
    print(f"FAIL — {failures} sorun var. Yukarıdaki çıktıyı incele.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
