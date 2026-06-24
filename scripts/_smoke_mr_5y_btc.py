"""Smoke: 3 MR strategies on BTC 15m FULL 5y - frequency check.

If RSI-extreme yields <500 trades over 5y -> archive without ensemble retest.
"""
from __future__ import annotations
import io, os, sys, time
from pathlib import Path

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from scripts.run_real_backtest import _load_symbol_ohlcv
from price_action.strategies.bollinger_fade_mr import (
    BollingerFadeMRStrategy, _default_manifest as bb_man,
)
from price_action.strategies.rsi_extreme_mr import (
    RSIExtremeMRStrategy, _default_manifest as rsi_man,
)
from price_action.strategies.range_bo_failure_mr import (
    RangeBOFailureMRStrategy, _default_manifest as bo_man,
)


def freq(name, strategy, df):
    t0 = time.time()
    feat = strategy.prepare_features(df)
    sigs = strategy.generate_signals(feat)
    elapsed = time.time() - t0
    print(f"  {name}: {len(sigs)} signals in {elapsed:.1f}s "
          f"(long={sum(1 for s in sigs if s.direction=='long')}, "
          f"short={sum(1 for s in sigs if s.direction=='short')})")
    return len(sigs)


def main():
    sym = "BTC/USDT"
    print(f"[load] {sym} 15m FULL 5y")
    df = _load_symbol_ohlcv(sym, tf="15m")
    df["symbol"] = sym; df["venue"] = "binance"; df["timeframe"] = "15m"
    print(f"  bars: {len(df):,}")
    print(f"  range: {df['ts'].iloc[0]} -> {df['ts'].iloc[-1]}")

    n_bb = freq("Bollinger Fade MR (default)", BollingerFadeMRStrategy(bb_man()), df)
    n_rsi = freq("RSI Extreme MR (default 25/75 pctile=0.30)", RSIExtremeMRStrategy(rsi_man()), df)
    n_bo = freq("Range BO Failure MR (default)", RangeBOFailureMRStrategy(bo_man()), df)

    # ----- alt parametre sanity (literatur standart 30/70, percentile=0.50) -----
    print()
    print('Alt RSI parameters (literature standard, single retest only):')
    rsi_alt = rsi_man()
    for p in rsi_alt.signals.patterns:
        if p.id == 'rsi_ext_long':
            p.params['rsi_oversold'] = 30.0
            p.params['atr_pct_pctile_thr'] = 0.50
        elif p.id == 'rsi_ext_short':
            p.params['rsi_overbought'] = 70.0
            p.params['atr_pct_pctile_thr'] = 0.50
    n_rsi_alt = freq("RSI Extreme MR (alt 30/70 pctile=0.50)", RSIExtremeMRStrategy(rsi_alt), df)

    # also: relax BB ADX from 20 to 25
    print()
    print('Alt BB parameters (ADX<25 - Wilder explicit alt):')
    bb_alt = bb_man()
    for p in bb_alt.signals.patterns:
        p.params['adx_threshold'] = 25.0
    n_bb_alt = freq("BB Fade MR (alt ADX<25)", BollingerFadeMRStrategy(bb_alt), df)

    print()
    print(f"Projection (×10 sym):")
    print(f"  BB-fade:   ~{n_bb*10:,}")
    print(f"  RSI-extr:  ~{n_rsi*10:,}")
    print(f"  Range-BOF: ~{n_bo*10:,}")
    print(f"Gate: n>=1000 (BB,RSI), n>=500 (BO)")


if __name__ == "__main__":
    main()
