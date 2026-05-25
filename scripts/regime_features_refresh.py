"""SEC54.6d — Daily BTC regime features refresh.

Cron: 1 0 * * * (daily 00:01 UTC)
Output: data/regime_features_latest.parquet

Computes BTCFeatures snapshot using t-1 BTC daily close data (CAUSAL — no
lookahead). Feature columns exactly match BTCFeatures dataclass in
regime_filter.py.

Live wiring:
  - RiskOfficer._load_regime_features() reads this parquet.
  - PerStrategyRegimeFilter.evaluate_strategy_regime_filter() uses the features.

Fail-safe design:
  - Any data fetch failure → exits with code 1, parquet unchanged (stale but
    safe; RiskOfficer fail-safe ALLOW handles staleness).
  - F&G fetch failure → fng_value=-1.0 sentinel written (F3 fails open).

Prometheus metric:
  - pa_regime_features_age_minutes gauge updated after successful write.

Usage:
  python scripts/regime_features_refresh.py
  python scripts/regime_features_refresh.py --output data/regime_features_test.parquet
  python scripts/regime_features_refresh.py --dry-run  (print features, no write)

Causal verify:
  ts field = yesterday's date (signal_date - 1 day for 15m bars).
  All features computed from BTC close[date-1] lookback.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Add project src to path
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _compute_features(
    output_path: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Main computation. Returns exit code (0=ok, 1=error)."""
    import pandas as pd

    now_utc = datetime.now(timezone.utc)
    # t-1 date (causal: features for signal arriving today use yesterday's close)
    t1_date = (now_utc - timedelta(days=1)).date()

    print(f"[regime_features_refresh] Computing features for t-1 date: {t1_date}")

    # ----------------------------------------------------------------
    # 1. Load BTC 1d OHLCV from DuckDB / parquet cache
    # ----------------------------------------------------------------
    btc_df: pd.DataFrame | None = None
    try:
        from price_action.data_pipeline import load_ohlcv_duckdb
        btc_df = load_ohlcv_duckdb("BTC/USDT", "1d")
    except Exception as exc:
        print(f"[WARN] DuckDB load failed ({exc}), trying parquet cache...")

    if btc_df is None:
        try:
            cache_path = Path("data/v095_ohlcv_cache.pkl")
            if not cache_path.exists():
                cache_path = Path("data/ohlcv_cache.pkl")
            import pickle
            with open(cache_path, "rb") as f:
                raw = pickle.load(f)
            if isinstance(raw, dict):
                btc_df = raw.get("BTC/USDT", raw.get("BTCUSDT"))
            else:
                btc_df = raw
        except Exception as exc2:
            print(f"[WARN] Pickle cache load failed ({exc2}), trying ccxt direct fetch...")

    # FIX 2026-05-25: ccxt direct fetch fallback (bypasses DuckDB lock conflicts
    # when futures15m daemon holds write-lock, and works when pickle cache absent)
    if btc_df is None:
        try:
            import ccxt
            ex = ccxt.binance({"enableRateLimit": True})
            # Fetch ~120 daily bars (covers all lookback windows: 90d, 30d, 60d, 14d)
            ohlcv = ex.fetch_ohlcv("BTC/USDT", "1d", limit=150)
            btc_df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            btc_df.index = pd.to_datetime(btc_df["timestamp"], unit="ms", utc=True)
            btc_df = btc_df.drop(columns=["timestamp"])
            print(f"[ccxt] Fetched {len(btc_df)} daily BTC bars from Binance")
        except Exception as exc3:
            print(f"[ERROR] All BTC OHLCV sources failed (ccxt: {exc3})")
            return 1

    if btc_df is None or btc_df.empty:
        print("[ERROR] BTC OHLCV dataframe is empty.")
        return 1

    # Normalize index to date
    if not isinstance(btc_df.index, pd.DatetimeIndex):
        btc_df.index = pd.to_datetime(btc_df.index, utc=True)
    btc_df = btc_df.sort_index()

    # Filter up to t-1 (causal — do NOT include today's incomplete bar)
    btc_df = btc_df[btc_df.index.date <= t1_date]
    if btc_df.empty:
        print(f"[ERROR] No BTC data up to {t1_date}")
        return 1

    # ----------------------------------------------------------------
    # 2. Compute features (all causal, using t-1 and prior closes)
    # ----------------------------------------------------------------
    close = btc_df["close"]

    # ATR% raw daily — PARITY: Researcher SEC54.6d backtest uses raw daily atr_pct
    # (not rolling mean). Lab parity verify 2026-05-20 confirmed: live wiring must
    # use raw daily, otherwise F1 filter under-triggers ~30-50%.
    # Reference: reports/lab/2026-05-20_sec54_6d_parity_verify.md §7.A
    # Column name "atr_pct_30d" is legacy from backfill schema (PerStrategyRegimeFilter
    # reads this column name); value is raw daily atr_pct (Researcher semantic).
    if "atr_pct" in btc_df.columns:
        atr_series = btc_df["atr_pct"]
    else:
        # Approximate ATR% using high-low range / close
        hl_pct = (btc_df["high"] - btc_df["low"]) / btc_df["close"] * 100.0
        atr_series = hl_pct

    atr_pct_30d = float(atr_series.iloc[-1])  # raw daily, NOT rolling mean

    # 30-day return (close[t-1] / close[t-31] - 1) * 100
    if "ret_30" in btc_df.columns:
        return_30d = float(btc_df["ret_30"].iloc[-1])
    else:
        if len(close) >= 31:
            return_30d = float((close.iloc[-1] / close.iloc[-31] - 1) * 100)
        else:
            return_30d = 0.0

    return_30d_abs_pct = abs(return_30d)

    # EMA200
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
    close_last = float(close.iloc[-1])
    ema200_distance_pct = (close_last - ema200) / ema200 * 100
    above_ema200 = bool(close_last >= ema200)

    # 7-day realized vol (annualized) = std(daily returns last 7 days) * sqrt(365) * 100
    daily_returns = close.pct_change().dropna()
    if len(daily_returns) >= 7:
        realized_vol_7d_ann = float(daily_returns.iloc[-7:].std() * (365 ** 0.5) * 100)
    else:
        realized_vol_7d_ann = 0.0

    # ----------------------------------------------------------------
    # 3. F&G index (t-1 value)
    # ----------------------------------------------------------------
    fng_value: float = -1.0  # sentinel: missing → fail-safe ALLOW for F3
    try:
        fng_path = Path("data/alt_data/fng_daily.csv")
        if fng_path.exists():
            fng_df = pd.read_csv(fng_path, parse_dates=["date"])
            fng_df = fng_df.sort_values("date")
            # t-1 lookup
            mask = fng_df["date"].dt.date <= t1_date
            if mask.any():
                fng_value = float(fng_df.loc[mask, "value"].iloc[-1])
    except Exception as fng_exc:
        print(f"[WARN] F&G load failed ({fng_exc}), fng_value=-1.0 (F3 fail-safe ALLOW)")

    # ----------------------------------------------------------------
    # 4. Assemble output row
    # ----------------------------------------------------------------
    features = {
        "ts": str(t1_date),                         # t-1 date string
        "atr_pct_30d": atr_pct_30d,
        "return_30d": return_30d,
        "return_30d_abs_pct": return_30d_abs_pct,
        "ema200_distance_pct": ema200_distance_pct,
        "above_ema200": above_ema200,
        "fng_value": fng_value,
        "realized_vol_7d_annualized": realized_vol_7d_ann,
        "fetched_at": now_utc.isoformat(),
    }

    print(f"[regime_features_refresh] Features (t-1={t1_date}):")
    for k, v in features.items():
        print(f"  {k}: {v}")

    if dry_run:
        print("[DRY-RUN] No parquet written.")
        return 0

    # ----------------------------------------------------------------
    # 5. Write parquet
    # ----------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_df = pd.DataFrame([features])
    row_df.to_parquet(output_path, index=False)
    print(f"[regime_features_refresh] Written: {output_path}")

    # ----------------------------------------------------------------
    # 6. Prometheus telemetry
    # ----------------------------------------------------------------
    try:
        from price_action.api.prometheus_metrics import regime_features_age_minutes
        regime_features_age_minutes.set(0.0)
        print("[regime_features_refresh] Prometheus metric updated: pa_regime_features_age_minutes=0")
    except Exception as prom_exc:
        print(f"[WARN] Prometheus metric update failed: {prom_exc}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="SEC54.6d — Daily BTC regime features refresh")
    parser.add_argument(
        "--output",
        default="data/regime_features_latest.parquet",
        help="Output parquet path (default: data/regime_features_latest.parquet)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute features but do not write parquet",
    )
    args = parser.parse_args()

    exit_code = _compute_features(
        output_path=Path(args.output),
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
