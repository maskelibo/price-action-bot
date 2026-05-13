"""SEC11 FINAL: A+B+E winners stack benchmark.

Hedef: %50/yıl
Stack:
  v1.1.0 baseline (monthly_dd=0.08): yıllık +%37.5
  + A: runner_trail_mult=2.0     (+%7.9)
  + B: tp2_R=1.5                 (+%9.5)
  + E: TOP_11 = TOP_10 + FVG     (+%8.7)
  Independent uplifts toplam +%26 — ama additive olmaz, etkileşimleri var.
  Beklenti: %42-50 yıllık (ne kadar üst üste binerse).

Output: reports/lab/sec11_final_stack.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import _gather, TOP_10, SYMBOLS_11
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip
from price_action.signals.filters import volume_zscore

# TOP_11 with FVG
TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]


def gather_with_engine(module_name, class_name, *,
                       runner_trail_mult=1.0, trail_activate_stage=2,
                       tp1_R=1.0, tp2_R=2.0, tp1_close_pct=0.30, tp2_close_pct=0.30):
    """Engine parametre override ile trade pool gen — A+B+E stack."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name}: {e}")
        return []

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf='1d')
            if df is None or df.empty:
                continue
            df = df.sort_values('ts').reset_index(drop=True)
            df['symbol'] = sym
            df['venue'] = 'binance'
            df['timeframe'] = '1d'
            try:
                df['vol_z_pre'] = volume_zscore(df['volume'], period=20)
            except Exception:
                rolling = df['volume'].rolling(20)
                df['vol_z_pre'] = (df['volume'] - rolling.mean()) / rolling.std()

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(
                risk_officer=None, store_load=None,
                runner_trail_mult=runner_trail_mult,
                trail_activate_stage=trail_activate_stage,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
            )
            r = e.run(
                s, [sym],
                start=df['ts'].iloc[0].to_pydatetime(),
                end=df['ts'].iloc[-1].to_pydatetime(),
                timeframe='1d', initial_capital=10_000.0,
                fees={'taker': 0.00075, 'maker': -0.00010}, slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df['ts'], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t['confluence_score']) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t['entry_ts'])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize('UTC')
                ts_x = pd.Timestamp(t['exit_ts'])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize('UTC')
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    val = df['vol_z_pre'].iloc[idx]
                    if pd.notna(val):
                        vz = float(val)
                out.append({
                    'entry_ts': ts_e, 'exit_ts': ts_x,
                    'entry_price': float(t['entry_price']),
                    'initial_sl': float(t['initial_sl']),
                    'R': float(t['realized_r_multiple']),
                    'symbol': sym, 'side': str(t['side']).lower(),
                    'conf': conf, 'strategy': module_name, 'vol_z': vz,
                })
        except Exception as e:
            print(f"  [WARN] {module_name} on {sym}: {e}")
    return out


def main() -> None:
    print('Stack pool gen: A (trail=2.0) + B (tp2_R=1.5) + E (FVG eklendi)')

    # 4 senaryo karşılaştırma
    scenarios = [
        # (label, strats, engine_kwargs)
        ("v1.1 baseline (monthly_dd=0.08)", TOP_10, dict(runner_trail_mult=1.0, tp1_R=1.0, tp2_R=2.0)),
        ("v1.1 + A (trail=2.0)", TOP_10, dict(runner_trail_mult=2.0, tp1_R=1.0, tp2_R=2.0)),
        ("v1.1 + B (tp2_R=1.5)", TOP_10, dict(runner_trail_mult=1.0, tp1_R=1.0, tp2_R=1.5)),
        ("v1.1 + E (FVG)", TOP_11, dict(runner_trail_mult=1.0, tp1_R=1.0, tp2_R=2.0)),
        ("v1.1 + A+B (trail=2.0, tp2_R=1.5)", TOP_10, dict(runner_trail_mult=2.0, tp1_R=1.0, tp2_R=1.5)),
        ("v1.1 + A+E (trail=2.0, FVG)", TOP_11, dict(runner_trail_mult=2.0, tp1_R=1.0, tp2_R=2.0)),
        ("v1.1 + B+E (tp2_R=1.5, FVG)", TOP_11, dict(runner_trail_mult=1.0, tp1_R=1.0, tp2_R=1.5)),
        ("v1.1 + A+B+E (FULL STACK)", TOP_11, dict(runner_trail_mult=2.0, tp1_R=1.0, tp2_R=1.5)),
    ]

    base = ProductionConfig.from_yaml('configs/risk_balanced.yaml')
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({'funding_filter_enabled': True, 'funding_aggregation_mode': '00:00_only'})
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg = base.with_overrides(
        alt_data_skip_long=fund_long, alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS, monthly_dd=0.08,
    )

    # Cache pools
    pool_cache = {}
    def get_pool(strats, kwargs):
        # kwargs key
        k = tuple(sorted(kwargs.items())) + tuple(sorted([s[0] for s in strats]))
        if k in pool_cache:
            return pool_cache[k]
        print(f"\n  Gen pool: strats={len(strats)}, kwargs={kwargs}")
        pool = []
        for m, c in strats:
            ts = gather_with_engine(m, c, **kwargs)
            pool.extend(ts)
        pool.sort(key=lambda x: x['entry_ts'])
        print(f"    -> {len(pool)} trade")
        pool_cache[k] = pool
        return pool

    print(f"\n{'='*100}")
    print(f"{'scenario':<48} {'n_trade':>7} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>7} {'r-adj':>7} {'neg':>5}")
    print('='*100)

    results = []
    for label, strats, eng_kwargs in scenarios:
        pool = get_pool(strats, eng_kwargs)
        if not pool:
            continue
        # 13 pencere
        start = pool[0]['entry_ts']
        end = pool[-1]['exit_ts']
        windows = []
        cur = start
        while cur + pd.Timedelta(days=3 * 365) <= end:
            windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
            cur += pd.Timedelta(days=60)
        anns, dds = [], []
        for ws, we in windows:
            ww_t = [t for t in pool if ws <= t['entry_ts'] < we]
            r = production_replay(ww_t, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            print(f"  {label:<48} bos")
            continue
        ma = mean(anns); md = mean(dds); ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        results.append((label, len(pool), ma, median(anns), min(anns), max(anns), md, ra, neg, len(anns)))
        print(f"  {label:<48} {len(pool):>7d} {ma:>+7.1f}% {median(anns):>+5.1f}% {min(anns):>+5.1f}% {max(anns):>+5.1f}% {md:>+5.1f}% {ra:>6.3f} {neg:>3}/{len(anns)}")

    # Final karar
    print(f"\n{'='*100}")
    print("KARAR")
    print('='*100)
    if results:
        best_return = max(results, key=lambda r: r[2])
        best_radj = max(results, key=lambda r: r[7])
        print(f"En yuksek return: {best_return[0]} -> yillik {best_return[2]:+.1f}% / DD {best_return[6]:+.1f}% / r-adj {best_return[7]:.3f}")
        print(f"En yuksek r-adj:  {best_radj[0]} -> yillik {best_radj[2]:+.1f}% / DD {best_radj[6]:+.1f}% / r-adj {best_radj[7]:.3f}")
        if best_return[2] >= 50:
            print(f"\n*** %50 HEDEF YAKALANDI: {best_return[0]} ({best_return[2]:+.1f}%) ***")
        elif best_return[2] >= 45:
            print(f"\n*** %45+ ULASILDI: {best_return[0]} ({best_return[2]:+.1f}%) — %50'ye yakin ***")


if __name__ == "__main__":
    main()
