"""P0 FIX RETEST: 15m R4 walk-forward with PYRAMID ENABLED + cooldown FIX.

Pool: data/sec31_15m_pool.pkl (cached 5y TOP-10)
Filter: TOP-4 (vsa, brooks_fb, anchored_vwap, engulfing_cont) × 10 sym
Config: configs/risk_phoenix_scalp_15m_pyramid_r3.yaml (+ P0 fix: pyramid_triggers/sizes added)
Override: max_concurrent=20, same_symbol_side_cooldown_days=0 (R4 mc=20 senaryosu)

Walk-forward: 2y train + 3mo OOS + 1mo step (sec31 pattern)

Baseline (before P0 fix, RESUME): yıllık +%233.5 / DD -%29.8 / r-adj 7.834 / 34/34 pozitif

Compare 4 scenarios:
  A. R4 baseline (pyramid OFF, cooldown=0 from YAML int cast bug)
  B. R4 + pyramid ON (P0 fix: triggers/sizes added)
  C. R4 + pyramid ON + cooldown ENFORCED (15dk from 0.010d)
  D. R4 cooldown=0 override + pyramid ON (script-level override, exact match RESUME label)
"""
from __future__ import annotations
import io, os, pickle, sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

from price_action.backtest.lab import ProductionConfig, production_replay

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

TRAIN_DAYS = 2 * 365     # 2y train
OOS_DAYS = 90            # 3mo OOS
STEP_DAYS = 30           # 1mo step


def build_windows(trades, train_days=TRAIN_DAYS, oos_days=OOS_DAYS, step_days=STEP_DAYS):
    """sec31 paterni: (cur, cur+train_days) — 2y replay pencere."""
    trades.sort(key=lambda x: x["entry_ts"])
    start = trades[0]["entry_ts"]
    end = trades[-1]["exit_ts"]
    out = []
    cur = start
    while cur + pd.Timedelta(days=train_days + oos_days) <= end:
        out.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=step_days)
    return out


def run_scenario(name, cfg, pool, windows, years=TRAIN_DAYS / 365.0):
    print(f"\n=== {name} ===")
    print(f"   pyramid={cfg.pyramid_enabled} triggers={cfg.pyramid_triggers} sizes={cfg.pyramid_sizes}")
    print(f"   cooldown={cfg.same_symbol_side_cooldown_days}d  mc={cfg.max_concurrent}")
    anns, dds, ras = [], [], []
    neg = 0
    n_trades_total = 0
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if not w: continue
        r = production_replay(w, cfg)
        if r is None: continue
        ann = r.annualized(years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        anns.append(ann); dds.append(dd); ras.append(ra)
        n_trades_total += r.trades
        if ann < 0: neg += 1
    if not anns:
        print("   NO RESULTS")
        return None
    ma = mean(anns); md = mean(dds); mr = mean(ras)
    print(f"   Windows: {len(anns)} (neg: {neg})")
    print(f"   Mean Ann: {ma:+.2f}%  Mean DD: {md:.2f}%  r-adj: {mr:.3f}  Trades: {n_trades_total:,}")
    return {"name": name, "ma": ma, "md": md, "ra": mr, "n_win": len(anns),
            "neg": neg, "n_tr": n_trades_total}


def main():
    print(f"[LOAD] {CACHE.name} ({CACHE.stat().st_size/1e6:.1f} MB)")
    with CACHE.open("rb") as f: pool_raw = pickle.load(f)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"[POOL] {len(pool):,} trade  (TOP-4 × 10 sym × 5y)")

    cfg_base = ProductionConfig.from_yaml(str(YAML_R3))
    print(f"\n[YAML LOAD] {YAML_R3.name}")
    print(f"   pyramid_enabled={cfg_base.pyramid_enabled}")
    print(f"   pyramid_triggers={cfg_base.pyramid_triggers}  (P0 FIX: önceden ())")
    print(f"   pyramid_sizes={cfg_base.pyramid_sizes}        (P0 FIX: önceden ())")
    print(f"   cooldown={cfg_base.same_symbol_side_cooldown_days}d "
          f"(P0 FIX: önceden int cast=0; şimdi float)")

    pool.sort(key=lambda x: x["entry_ts"])
    windows = build_windows(pool)
    print(f"\n[WINDOWS] {len(windows)} (2y train + 3mo OOS + 1mo step)")

    # ====================================================================
    # Senaryolar
    # ====================================================================
    results = []

    # B. R4 + Pyramid ON (P0 fix) + cooldown YAML enforced (15dk = 0.010d)
    cfg_b = cfg_base.with_overrides(max_concurrent=20)
    results.append(run_scenario("B. R4 mc=20 + Pyramid ON + cooldown=15dk (YAML, P0 fix enforced)",
                                cfg_b, pool, windows))

    # C. R4 + Pyramid ON + cooldown=0 override (RESUME label "mc=20 + cooldown=0")
    cfg_c = cfg_base.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    results.append(run_scenario("C. R4 mc=20 + Pyramid ON + cooldown=0 (RESUME label match)",
                                cfg_c, pool, windows))

    # A. Pre-fix baseline approximation: pyramid OFF + cooldown=0
    cfg_a = replace(cfg_base, pyramid_enabled=False, pyramid_triggers=(),
                    pyramid_sizes=()).with_overrides(
        max_concurrent=20, same_symbol_side_cooldown_days=0)
    results.append(run_scenario("A. PRE-FIX baseline (pyramid OFF + cooldown=0) — RESUME +%233.5 ref",
                                cfg_a, pool, windows))

    # ====================================================================
    # ÖZET
    # ====================================================================
    print("\n" + "="*80)
    print("ÖZET TABLO")
    print("="*80)
    print(f"{'Senaryo':<60} {'Ann%':>8} {'DD%':>8} {'r-adj':>7} {'win':>5} {'neg':>4}")
    print("-" * 100)
    for r in results:
        if r is None: continue
        print(f"{r['name'][:60]:<60} {r['ma']:>+7.2f}% {r['md']:>+7.2f}% {r['ra']:>6.3f} {r['n_win']:>4} {r['neg']:>4}")

    # Verdict
    print()
    if results[0]:
        b = results[0]
        if b["ma"] >= 250 and b["md"] >= -35 and b["ra"] >= 7.0 and b["neg"] == 0:
            verdict = "PASS-STRONG (Pyramid ON yıllık ≥ +250%, baseline beat)"
        elif b["ma"] >= 200:
            verdict = "PASS (Pyramid ON yıllık ≥ +200%, production candidate)"
        elif b["ma"] >= 150:
            verdict = "PARTIAL (Pyramid ON 150-200% bandı, yorum gerekli)"
        else:
            verdict = "REGRESSION (Pyramid ON < +150%, fix BROKEN?)"
        print(f"VERDICT: {verdict}")
        print(f"  Pyramid uplift vs A (no-pyr): {b['ma'] - results[2]['ma']:+.2f}pp  "
              f"(forensic önerisi: ~+50-100pp)")


if __name__ == "__main__":
    main()
