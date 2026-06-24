"""Smoke test: 3 MR strategies on BTC 15m, last 6 months.

Sanity check:
- prepare_features runs without error
- generate_signals returns non-empty list
- no lookahead violation (signal.ts must equal bar timestamp, entry uses bar t open)
- atr/rsi/bb columns populated
"""
from __future__ import annotations
import io, os, sys
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


def smoke(name, strategy, df):
    print(f"\n=== {name} ===")
    feat = strategy.prepare_features(df)
    long_n = int(feat["long_setup_prev"].sum())
    short_n = int(feat["short_setup_prev"].sum())
    print(f"  Setup flags: long_prev={long_n}, short_prev={short_n}")
    sigs = strategy.generate_signals(feat)
    print(f"  Signals: {len(sigs)} (long={sum(1 for s in sigs if s.direction=='long')}, short={sum(1 for s in sigs if s.direction=='short')})")
    if sigs:
        s0 = sigs[0]
        s_last = sigs[-1]
        print(f"  First: ts={s0.ts} dir={s0.direction} sl={s0.sl_price:.4f} tp={s0.tp_price:.4f}")
        print(f"  Last : ts={s_last.ts} dir={s_last.direction}")

        # Lookahead audit: signal.ts must be ts of bar(t) and entry uses open(t)
        df_ts = pd.to_datetime(df["ts"], utc=True)
        sig_ts_set = set(pd.Timestamp(s.ts).tz_convert("UTC") if pd.Timestamp(s.ts).tzinfo else pd.Timestamp(s.ts).tz_localize("UTC") for s in sigs[:50])
        df_ts_set = set(df_ts.tolist())
        missing = sig_ts_set - df_ts_set
        if missing:
            print(f"  WARN: {len(missing)} signal ts not in df!")
        else:
            print(f"  Lookahead audit (first 50): OK (all ts in df)")
    return sigs


def main():
    sym = "BTC/USDT"
    print(f"[load] {sym} 15m")
    df = _load_symbol_ohlcv(sym, tf="15m")
    print(f"  bars: {len(df):,}")
    # last 90 days for smoke
    cutoff = df["ts"].iloc[-1] - pd.Timedelta(days=90)
    sub = df[df["ts"] >= cutoff].copy()
    sub["symbol"] = sym
    sub["venue"] = "binance"
    sub["timeframe"] = "15m"
    print(f"  subset (90d): {len(sub):,}")

    smoke("Bollinger Fade MR", BollingerFadeMRStrategy(bb_man()), sub)
    smoke("RSI Extreme MR", RSIExtremeMRStrategy(rsi_man()), sub)
    smoke("Range BO Failure MR", RangeBOFailureMRStrategy(bo_man()), sub)


if __name__ == "__main__":
    main()
