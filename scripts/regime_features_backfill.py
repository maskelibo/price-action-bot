"""SEC54.6d parity — Backfill BTC regime features for the full 5y pool range.

Generates a daily parquet (one row per BTC daily close date) with the same
schema as `data/regime_features_latest.parquet` (live snapshot) so that the
live `PerStrategyRegimeFilter` can be exercised against every historical
trade timestamp via t-1 daily lookup.

Schema (matches BTCFeatures dataclass + parquet writer in
regime_features_refresh.py):

  ts                                date (t-1 daily close date)
  atr_pct_30d                       float (BTC 30g rolling mean of atr_pct)
  return_30d                        float (BTC 30g return %, causal)
  return_30d_abs_pct                float
  ema200_distance_pct               float
  above_ema200                      bool
  fng_value                         float (-1 sentinel if missing → fail-safe)
  realized_vol_7d_annualized        float (std(daily_ret_7d) * sqrt(365) * 100)
  fetched_at                        datetime (now UTC, all rows same value)

CAUSAL: every row represents the snapshot AS IF taken at 00:01 UTC the day
after the `ts` date — i.e. exactly what `regime_features_refresh.py` would
have produced if run on that day. Replay caller then looks up
`entry_ts.date() - 1 day` and gets t-1 features.

Output: data/regime_features_backfill_5y.parquet
"""
from __future__ import annotations

import argparse
import math
import pickle
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd


def build_backfill(
    ohlcv_path: Path,
    fng_path: Path,
    output_path: Path,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    print(f"[backfill] Loading BTC OHLCV: {ohlcv_path}")
    with ohlcv_path.open("rb") as f:
        cache = pickle.load(f)
    btc = cache["BTC/USDT"].copy()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    btc["date"] = btc["ts"].dt.normalize().dt.date
    btc = btc.sort_values("date").reset_index(drop=True)
    print(f"  BTC daily rows: {len(btc):,}  range {btc['date'].min()} -> {btc['date'].max()}")

    # F&G
    print(f"[backfill] Loading F&G: {fng_path}")
    fng = pd.read_csv(fng_path, parse_dates=["date"])
    fng["date"] = fng["date"].dt.tz_localize("UTC", nonexistent="shift_forward").dt.normalize().dt.date
    fng = fng.sort_values("date")
    print(f"  F&G rows: {len(fng):,}  range {fng['date'].min()} -> {fng['date'].max()}")
    fng_map = dict(zip(fng["date"], fng["value"]))

    # Compute features per row (causal, using only data up to that row's date)
    # Strategy: for each ts (= row's date, treated as t-1 close), compute the
    # snapshot. Since features already live in the cache for atr_pct, ret_30,
    # above_ema200, we can use them directly. We add:
    #   - atr_pct_30d (rolling 30 mean of atr_pct, matches refresh script)
    #   - realized_vol_7d_annualized (std(daily_ret_7d) * sqrt(365) * 100)
    #   - return_30d_abs_pct
    #   - ema200_distance_pct (compute from close & ema200)
    btc["daily_ret"] = btc["close"].pct_change()
    btc["vol_7d_std"] = btc["daily_ret"].rolling(7).std()
    btc["realized_vol_7d_annualized"] = btc["vol_7d_std"] * math.sqrt(365) * 100.0
    # atr_pct_30d — PARITY NOTE: Researcher SEC54.6d script (sec54_6d_regime_filter_replay.py
    # build_btc_regime_table) used the RAW DAILY `atr_pct` field (close-of-day ATR14/close),
    # NOT a 30-day rolling mean, when applying F1 threshold (`atr_pct<3.0`).
    # The live wiring `PerStrategyRegimeFilter` reads the column named `atr_pct_30d` (per
    # BTCFeatures schema), so for parity we WRITE the raw daily atr_pct into that column.
    # Live refresh script (`regime_features_refresh.py`) uses rolling(30).mean(); that is a
    # SEPARATE SEMANTIC for live, not used for parity here. (TODO: align live refresh to
    # raw daily as well, or change Researcher script to use rolling — Engineering ticket.)
    btc["atr_pct_30d"] = btc["atr_pct"]  # raw daily — Researcher semantic
    btc["return_30d_abs_pct"] = btc["ret_30"].abs()
    # ema200_distance_pct
    if "ema200" in btc.columns:
        btc["ema200_distance_pct"] = (btc["close"] - btc["ema200"]) / btc["ema200"] * 100.0
    else:
        btc["ema200_distance_pct"] = 0.0

    # F&G column
    btc["fng_value"] = btc["date"].map(lambda d: fng_map.get(d, None))
    # Forward-fill F&G (CAUSAL — only carries last known value forward)
    btc["fng_value"] = btc["fng_value"].ffill()
    # Missing sentinel
    btc["fng_value"] = btc["fng_value"].fillna(-1.0)

    # Filter date range if requested
    if start is not None:
        btc = btc[btc["date"] >= start]
    if end is not None:
        btc = btc[btc["date"] <= end]

    # Build output rows
    # fetched_at = now (researcher backfill — staleness check disabled in parity)
    now_iso = datetime.now(timezone.utc)

    out = pd.DataFrame({
        "ts": [d for d in btc["date"]],  # date object → parquet stores as date32
        "atr_pct_30d": btc["atr_pct_30d"].astype(float).values,
        "return_30d": btc["ret_30"].astype(float).values,
        "return_30d_abs_pct": btc["return_30d_abs_pct"].astype(float).values,
        "ema200_distance_pct": btc["ema200_distance_pct"].astype(float).values,
        "above_ema200": btc["above_ema200"].astype(bool).values,
        "fng_value": btc["fng_value"].astype(float).values,
        "realized_vol_7d_annualized": btc["realized_vol_7d_annualized"].astype(float).values,
        "fetched_at": [now_iso] * len(btc),
    })

    # PARITY: Researcher script built regime_tbl WITHOUT dropping NaN rows — when
    # a feature was NaN at a given date, the inline filter functions treated it as
    # "missing → don't skip" (fail-safe). To match that behavior under the live
    # PerStrategyRegimeFilter, we keep all rows but FILL critical fields with
    # sentinels that the live class will NOT trigger on:
    #   - atr_pct_30d NaN → 999.0 (always >= F1 threshold 3.0 → never triggers F1)
    #   - return_30d NaN → 0.0 (|0|<3 → COULD trigger F1; but F1 also requires
    #     atr_pct_30d<3 so with 999.0 it stays safe; F2/F3 use ret30 directly,
    #     0 doesn't satisfy >+5 or <-10 → safe)
    #   - return_30d_abs_pct NaN → 0.0 (|0|<3 → could trigger F1 if atr<3, but
    #     atr=999 saves us)
    #   - realized_vol_7d_annualized NaN → 0.0 (0<100 → never triggers F4)
    #   - fng_value NaN → -1.0 (sentinel for live F3 fail-safe ALLOW path)
    # This mirrors the Researcher's "if regime['x'] is None: return False (don't skip)"
    # branches.
    pre_n = len(out)
    out["atr_pct_30d"] = out["atr_pct_30d"].fillna(999.0)
    out["return_30d"] = out["return_30d"].fillna(0.0)
    out["return_30d_abs_pct"] = out["return_30d_abs_pct"].fillna(0.0)
    out["realized_vol_7d_annualized"] = out["realized_vol_7d_annualized"].fillna(0.0)
    out["fng_value"] = out["fng_value"].fillna(-1.0)
    print(f"  Rows kept: {len(out):,} / {pre_n:,} (NaN -> safe sentinels)")

    # Write parquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(output_path, index=False)
    print(f"[backfill] Written: {output_path}  ({len(out):,} rows)")

    # Diagnostics
    print(f"  atr_pct_30d:  mean={out['atr_pct_30d'].mean():.2f}  range=[{out['atr_pct_30d'].min():.2f}, {out['atr_pct_30d'].max():.2f}]")
    print(f"  return_30d:   mean={out['return_30d'].mean():.2f}  range=[{out['return_30d'].min():.2f}, {out['return_30d'].max():.2f}]")
    print(f"  vol_7d_ann:   mean={out['realized_vol_7d_annualized'].mean():.1f}  range=[{out['realized_vol_7d_annualized'].min():.1f}, {out['realized_vol_7d_annualized'].max():.1f}]")
    print(f"  fng_value:    mean={out['fng_value'].mean():.1f}  range=[{out['fng_value'].min():.0f}, {out['fng_value'].max():.0f}]")
    print(f"  above_ema200: True={int(out['above_ema200'].sum())}  False={int((~out['above_ema200']).sum())}")

    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ohlcv", default=str(ROOT / "data" / "v095_ohlcv_cache.pkl"))
    p.add_argument("--fng",   default=str(ROOT / "data" / "alt_data" / "fng_daily.csv"))
    p.add_argument("--output",default=str(ROOT / "data" / "regime_features_backfill_5y.parquet"))
    p.add_argument("--start", default="2021-05-16", help="ISO date inclusive")
    p.add_argument("--end",   default="2026-05-16", help="ISO date inclusive")
    args = p.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    build_backfill(
        ohlcv_path=Path(args.ohlcv),
        fng_path=Path(args.fng),
        output_path=Path(args.output),
        start=start,
        end=end,
    )


if __name__ == "__main__":
    main()
