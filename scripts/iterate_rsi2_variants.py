"""rsi2-extreme-fade için 6 iterate varyant denemesi.

Faz 14.23 (2026-05-27): User talebi — pozitif edge'li ama DD kötü olan
rsi2-extreme-fade (+13.61% aylık, -79% DD) için gerçek iterate çalışması.

Varyantlar:
  v1 (baseline)        : risk 0.005, no filter, SL/TP/24h
  v2 risk_reduction    : risk 0.002, daily DD halt 2%
  v3 trade_quality     : confluence > 2.5 filter
  v4 position_mgmt     : BE-protect (1R → SL=entry)
  v5 regime_filter     : BTC EMA200 — sadece trend yönü
  v6 combo             : v2+v3+v4 best birlikte

Her varyant için:
  - Strategy.generate_signals
  - Filter (varyanta göre)
  - Custom exit (SL/TP/BE/time)
  - Equity sim (lower risk_pct + DD halt)
  - Monthly aggregate
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ.setdefault("PA_LOG_QUIET", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import numpy as np
import pandas as pd

from price_action.strategies.base import StrategyManifest
from price_action.strategies.rsi2_extreme_fade import RSI2ExtremeFadeStrategy

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _load_ohlcv(symbol: str, tf: str = "15m") -> pd.DataFrame:
    import duckdb
    snapshot = Path("/tmp/market_snapshot.duckdb")
    db_path = snapshot if snapshot.exists() else (ROOT / "data" / "market.duckdb")
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
        [symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    return df


def _exit_with_be(
    df: pd.DataFrame,
    i0: int,
    entry: float,
    sl: float,
    tp_r: float,
    direction: str,
    *,
    max_bars: int = 96,
    be_protect: bool = False,
    trail_pct: float | None = None,
) -> tuple[float, float, int]:
    """SL/TP/BE/time exit detection.

    BE-protect: 1R'ye ulaşıldığında SL = entry'ye çek.
    Trail: peak'ten X% geri trail (None ise yok).
    Returns: (R, exit_price, exit_idx_offset)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0, entry, 0
    if direction == "long":
        tp = entry + tp_r * risk
        be_trigger = entry + 1.0 * risk
    else:
        tp = entry - tp_r * risk
        be_trigger = entry - 1.0 * risk

    sl_active = sl
    peak = entry
    be_armed = False

    end_i = min(i0 + 1 + max_bars, len(df))
    for j in range(i0 + 1, end_i):
        h, lo, c = float(df["high"].iloc[j]), float(df["low"].iloc[j]), float(df["close"].iloc[j])
        # BE-protect aktive
        if be_protect and not be_armed:
            if direction == "long" and h >= be_trigger:
                sl_active = max(sl_active, entry)
                be_armed = True
            elif direction == "short" and lo <= be_trigger:
                sl_active = min(sl_active, entry)
                be_armed = True
        # Trail
        if trail_pct is not None:
            if direction == "long":
                peak = max(peak, h)
                trail_sl = peak * (1 - trail_pct)
                sl_active = max(sl_active, trail_sl)
            else:
                peak = min(peak, lo)
                trail_sl = peak * (1 + trail_pct)
                sl_active = min(sl_active, trail_sl)
        # SL hit
        if direction == "long":
            if lo <= sl_active:
                r = (sl_active - entry) / risk
                return r, sl_active, j - i0
            if h >= tp:
                return tp_r, tp, j - i0
        else:
            if h >= sl_active:
                r = (entry - sl_active) / risk
                return r, sl_active, j - i0
            if lo <= tp:
                return tp_r, tp, j - i0
    # Time exit
    last_close = float(df["close"].iloc[end_i - 1])
    if direction == "long":
        r = (last_close - entry) / risk
    else:
        r = (entry - last_close) / risk
    return r, last_close, end_i - 1 - i0


def _equity_sim_with_dd_halt(
    trades_df: pd.DataFrame,
    *,
    initial_capital: float = 10_000.0,
    risk_pct: float = 0.005,
    daily_dd_halt: float | None = None,
    max_concurrent: int = 999,
) -> tuple[pd.Series, float, int]:
    """Sequentially equity sim + opsiyonel daily DD halt.

    daily_dd_halt: 0.02 = günlük equity %2 düşerse o gün halt (yeni trade alma).
    max_concurrent: aynı anda max kaç open pozisyon (overlap kontrol).

    Returns: (equity_series, final_equity, trades_taken)
    """
    if trades_df.empty:
        return pd.Series(dtype=float), initial_capital, 0
    sorted_trades = trades_df.sort_values("entry_ts").reset_index(drop=True)
    equity = initial_capital
    eq_data = []
    n_taken = 0
    halted_dates = set()
    day_start_equity = {}
    open_positions: list[dict] = []
    for _, t in sorted_trades.iterrows():
        entry_ts = pd.Timestamp(t["entry_ts"])
        exit_ts = pd.Timestamp(t["exit_ts"])
        day_key = entry_ts.date()
        # Daily DD halt check
        if daily_dd_halt:
            if day_key not in day_start_equity:
                day_start_equity[day_key] = equity
            if day_key in halted_dates:
                continue
        # Concurrent cap — close finished positions
        open_positions = [p for p in open_positions if p["exit_ts"] > entry_ts]
        if len(open_positions) >= max_concurrent:
            continue
        # Take trade
        risk_dollars = equity * risk_pct
        pnl = risk_dollars * float(t["R"])
        equity += pnl
        n_taken += 1
        eq_data.append({"ts": exit_ts, "equity": equity})
        open_positions.append({"exit_ts": exit_ts})
        # Daily DD halt
        if daily_dd_halt:
            day_dd = (equity - day_start_equity[day_key]) / day_start_equity[day_key]
            if day_dd <= -daily_dd_halt:
                halted_dates.add(day_key)
    if not eq_data:
        return pd.Series(dtype=float), initial_capital, n_taken
    eq_df = pd.DataFrame(eq_data)
    eq_series = pd.Series(eq_df["equity"].values, index=pd.to_datetime(eq_df["ts"], utc=True))
    return eq_series, equity, n_taken


def _compute_metrics(eq_series: pd.Series, initial_capital: float) -> dict:
    if eq_series.empty:
        return {"monthly_roi": 0, "neg_count": 0, "total_months": 0, "max_dd": 0, "annualized": 0}
    eq = eq_series.copy()
    monthly = eq.resample("ME").last()
    monthly_prev = monthly.shift(1, fill_value=initial_capital)
    monthly_ret = (monthly / monthly_prev - 1.0).dropna()
    running_peak = eq.cummax()
    dd = (eq - running_peak) / running_peak
    max_dd = float(dd.min())
    period_sec = (eq.index[-1] - eq.index[0]).total_seconds()
    period_years = period_sec / (365.25 * 86400) if period_sec > 0 else 0
    final_equity = float(eq.iloc[-1])
    annualized = (final_equity / initial_capital) ** (1 / period_years) - 1 if period_years > 0 else 0
    return {
        "monthly_roi": float(monthly_ret.mean()) * 100,
        "neg_count": int((monthly_ret < 0).sum()),
        "total_months": int(len(monthly_ret)),
        "max_dd": max_dd * 100,
        "annualized": annualized * 100,
        "worst_month": float(monthly_ret.min()) * 100 if len(monthly_ret) > 0 else 0,
    }


def _get_btc_regime_filter(timeframe: str = "1d"):
    """BTC EMA200 trend: True = bull (BTC > EMA200), False = bear."""
    df = _load_ohlcv("BTC/USDT", timeframe)
    if df.empty:
        return None
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["regime"] = df["close"] > df["ema200"]
    df = df[["ts", "regime"]].set_index("ts")
    return df


def collect_signals_and_trades(
    *,
    confluence_min: float = 0.0,
    be_protect: bool = False,
    trail_pct: float | None = None,
    regime_filter: pd.DataFrame | None = None,
    tp_r: float = 1.5,
) -> pd.DataFrame:
    """rsi2-extreme-fade için tüm sembollerden trade'leri topla."""
    manifest = StrategyManifest(name="rsi2_extreme_fade", version="iterate-1.0")
    strategy = RSI2ExtremeFadeStrategy(manifest)
    all_trades = []
    for sym in SYMBOLS:
        df = _load_ohlcv(sym, "15m")
        if df.empty:
            continue
        try:
            df_feats = strategy.prepare_features(df)
            signals = strategy.generate_signals(df_feats)
        except Exception:
            continue
        df_feats = df_feats.reset_index(drop=True)
        for sig in signals:
            # Confluence filter
            if sig.confluence_score < confluence_min:
                continue
            sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
            if len(sig_idx) == 0:
                continue
            i0 = sig_idx[0]
            if i0 >= len(df_feats) - 1:
                continue
            entry = float(df_feats["close"].iloc[i0])
            # Regime filter (BTC trend)
            if regime_filter is not None and sym != "BTC/USDT":
                # Sinyal tarihindeki BTC regime
                sig_day = pd.Timestamp(sig.ts).floor("1D")
                if sig_day in regime_filter.index:
                    is_bull = bool(regime_filter.loc[sig_day, "regime"])
                else:
                    nearest = regime_filter.index.searchsorted(sig_day)
                    if nearest == 0 or nearest >= len(regime_filter):
                        continue
                    is_bull = bool(regime_filter.iloc[nearest - 1]["regime"])
                # Bull regime → sadece long; bear → sadece short
                if is_bull and sig.direction != "long":
                    continue
                if not is_bull and sig.direction != "short":
                    continue
            R, exit_price, exit_offset = _exit_with_be(
                df_feats, i0, entry, sig.sl_price,
                tp_r=tp_r, direction=sig.direction,
                be_protect=be_protect, trail_pct=trail_pct,
            )
            all_trades.append({
                "entry_ts": sig.ts,
                "exit_ts": df_feats["ts"].iloc[i0 + exit_offset] if i0 + exit_offset < len(df_feats) else df_feats["ts"].iloc[-1],
                "entry_price": entry,
                "exit_price": exit_price,
                "R": float(R),
                "symbol": sym,
                "side": sig.direction,
                "confluence": float(sig.confluence_score),
            })
    return pd.DataFrame(all_trades)


VARIANTS = [
    {
        "name": "v1_baseline",
        "label": "Baseline (no filter, no BE)",
        "trades_args": {"confluence_min": 0, "be_protect": False, "tp_r": 1.5},
        "equity_args": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 999},
    },
    {
        "name": "v2_risk_reduction",
        "label": "risk_pct 0.005→0.002 + daily DD halt 2%",
        "trades_args": {"confluence_min": 0, "be_protect": False, "tp_r": 1.5},
        "equity_args": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 999},
    },
    {
        "name": "v3_trade_quality",
        "label": "Confluence > 2.5",
        "trades_args": {"confluence_min": 2.5, "be_protect": False, "tp_r": 1.5},
        "equity_args": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 999},
    },
    {
        "name": "v4_be_protect",
        "label": "BE-protect (1R → SL=entry)",
        "trades_args": {"confluence_min": 0, "be_protect": True, "tp_r": 1.5},
        "equity_args": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 999},
    },
    {
        "name": "v5_regime_filter",
        "label": "BTC EMA200 regime (long bull, short bear)",
        "trades_args": {"confluence_min": 0, "be_protect": False, "tp_r": 1.5, "regime_filter": True},
        "equity_args": {"risk_pct": 0.005, "daily_dd_halt": None, "max_concurrent": 999},
    },
    {
        "name": "v6_combo",
        "label": "v2+v3+v4 combo (risk + confluence + BE)",
        "trades_args": {"confluence_min": 2.5, "be_protect": True, "tp_r": 1.5},
        "equity_args": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 999},
    },
]


def main() -> int:
    print("=== rsi2-extreme-fade — 6 İterate Varyant ===")
    print()
    print(f"{'Varyant':30} {'aylık':>8} {'neg':>7} {'DD':>8} {'yıllık':>9} {'n_tr':>6}  Sonuç")
    print("-" * 110)

    # Champion baseline reference
    champion = {"monthly": 12.99, "dd": -15.48, "neg": "4/61"}
    print(f"{'LIVE bot (vsa widestop)':30} {'+12.99%':>8} {'4/61':>7} {'-15.48%':>8} {'+329%':>9} {'4458':>6}  🟢 baseline")
    print("-" * 110)

    # BTC regime filter (v5 için)
    btc_regime = _get_btc_regime_filter("1d")

    out_dir = ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for v in VARIANTS:
        targs = dict(v["trades_args"])
        if targs.pop("regime_filter", False):
            trades_df = collect_signals_and_trades(regime_filter=btc_regime, **targs)
        else:
            trades_df = collect_signals_and_trades(**targs)
        if trades_df.empty:
            print(f"{v['name']:30} NO_TRADES")
            continue
        eq_series, final_eq, n_taken = _equity_sim_with_dd_halt(trades_df, **v["equity_args"])
        m = _compute_metrics(eq_series, 10_000.0)
        # Promotable?
        promote = (
            m["monthly_roi"] >= 4.0
            and m["max_dd"] >= -25.0
            and m["neg_count"] <= 20
        )
        flag = "✅ PROMOTE" if promote else (
            "🟡 marginal" if m["monthly_roi"] > 0 and m["max_dd"] > -50 else "❌ reject"
        )
        print(f"{v['name']:30} "
              f"{m['monthly_roi']:>+7.2f}% "
              f"{m['neg_count']:>2}/{m['total_months']:<3} "
              f"{m['max_dd']:>+7.2f}% "
              f"{m['annualized']:>+8.2f}% "
              f"{n_taken:>6}  {flag} ({v['label']})")
        results.append({
            "variant": v["name"],
            "label": v["label"],
            "trades_args": v["trades_args"],
            "equity_args": v["equity_args"],
            "n_trades_raw": len(trades_df),
            "n_trades_taken": n_taken,
            "monthly_roi": m["monthly_roi"],
            "max_dd": m["max_dd"],
            "neg_count": m["neg_count"],
            "total_months": m["total_months"],
            "annualized": m["annualized"],
            "worst_month": m["worst_month"],
            "final_equity": final_eq,
            "promote": promote,
        })

    # JSON dump
    out_path = out_dir / "rsi2-iterate-comparison.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "champion_baseline": champion,
        "variants": results,
    }, indent=2, default=str), encoding="utf-8")
    print()
    print(f"Detay: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
