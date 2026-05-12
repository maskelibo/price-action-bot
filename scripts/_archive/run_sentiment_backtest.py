"""Fear & Greed Sentiment Backtest — H18.

3 senaryo karsilastirmasi:
    S1: Engulfing solo (baseline ~+%68 yillik)
    S2: F&G standalone (extreme fear/greed signals)
    S3: Engulfing + F&G filtre (greed zirvelerinde long, fear diblerinde short yok)

BTC/USDT 1d: S2 (standalone FNG)
10 sembol 1d: S1 ve S3 (engulfing solo vs engulfing+fng)

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_sentiment_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# F&G veri yukleyici
# ---------------------------------------------------------------------------

def _load_fng_data() -> pd.DataFrame:
    """Oncelikle DuckDB'den oku; yoksa API'den cek."""
    from price_action.data.sentiment_ingest import FngStore, fetch_fear_greed_history

    store = FngStore()
    count = store.count()
    if count < 100:
        print(f"  F&G DB bos/az ({count} rows) — API'den cekiliyor...")
        try:
            df = fetch_fear_greed_history(limit=2000)
            if not df.empty:
                store.upsert(df)
                print(f"  F&G: {len(df)} gun indirildi ve kaydedildi.")
            else:
                print("  UYARI: F&G API bos dondu — mock veri kullaniliyor.")
                return _mock_fng()
        except Exception as exc:
            print(f"  UYARI: F&G API hatasi: {exc}. Mock veri kullaniliyor.")
            return _mock_fng()

    df = store.read()
    print(f"  F&G: {len(df)} gun DB'den yuklendi "
          f"({df['ts'].min().date()} - {df['ts'].max().date()})")
    return df


def _mock_fng() -> pd.DataFrame:
    """API mevcut degilse deterministik mock F&G uretir (test amacli)."""
    import numpy as np
    rng = np.random.default_rng(42)
    days = pd.date_range("2018-01-01", periods=2000, freq="1D", tz="UTC")
    # Sinusoidal + noise — gercekci ama deterministik
    t = np.arange(len(days))
    base = 50 + 30 * np.sin(2 * np.pi * t / 365) + 15 * np.sin(2 * np.pi * t / 90)
    noise = rng.normal(0, 8, len(days))
    values = np.clip(base + noise, 0, 100).astype(int)

    def classify(v: int) -> str:
        if v < 25:
            return "Extreme Fear"
        if v < 50:
            return "Fear"
        if v < 75:
            return "Greed"
        return "Extreme Greed"

    df = pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": [classify(v) for v in values],
    })
    return df


# ---------------------------------------------------------------------------
# OHLCV yukleyici
# ---------------------------------------------------------------------------

def _load_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


# ---------------------------------------------------------------------------
# Manifest fabrikalar
# ---------------------------------------------------------------------------

def _make_engulfing_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_fng_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "sentiment_filter",
        "version": "1.0.0",
        "description": "F&G standalone sentiment",
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "fng_extreme_fear_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"fng_long_threshold": 25, "fng_exit_neutral_low": 40, "fng_exit_neutral_high": 60},
                },
                {
                    "id": "fng_extreme_greed_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"fng_short_threshold": 75, "fng_exit_neutral_low": 40, "fng_exit_neutral_high": 60},
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 10, "cluster_atr_multiplier": 0.5, "min_touches": 2, "max_age_bars": 10},
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.003, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Tek sembol backtest runner
# ---------------------------------------------------------------------------

def _run_one(symbol: str, manifest, strategy_cls, initial_capital: float = 10_000.0, fng_df=None) -> dict:
    from price_action.backtest.engine import BacktestEngine

    df = _load_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no_data"}

    strategy = strategy_cls(manifest)
    if fng_df is not None and hasattr(strategy, "set_fng_data"):
        strategy.set_fng_data(fng_df)

    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    def ohlcv_provider(_s, _t, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy,
        [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    _cagr = float(k.get("cagr", 0.0))
    _net = float(k.get("net_pnl", 0.0))
    if _net == 0.0 and _cagr != 0.0:
        _net = initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": len(signals),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy": float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": _cagr,
        "net_pnl": _net,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
    }


def _run_engulfing_fng_filtered(
    symbol: str, eng_manifest, fng_df: pd.DataFrame,
    long_max_fng: float = 60.0, short_min_fng: float = 40.0,
    initial_capital: float = 10_000.0,
) -> dict:
    """Engulfing sinyallerini F&G filtresiyle elek + backtest.

    Strateji wrapper: EngulfingContinuationStrategy'nin generate_signals'ini
    override edip filtered sinyalleri dogrudan enjekte eder.
    """
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

    df = _load_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no_data"}

    # Once raw sinyalleri uret, sonra filtrele
    base_strategy = EngulfingContinuationStrategy(eng_manifest)
    df_feats = base_strategy.prepare_features(df)
    raw_signals = base_strategy.generate_signals(df_feats)
    filtered_signals, n_rejected = filter_engulfing_with_fng(
        raw_signals, fng_df, long_max_fng=long_max_fng, short_min_fng=short_min_fng
    )

    # Filtered sinyalleri enjekte eden sarici strateji
    class _FilteredStrategy(EngulfingContinuationStrategy):
        """Sadece filtered sinyalleri doner — prepare_features ayni."""
        _injected: list

        def generate_signals(self, df_inner):  # type: ignore[override]
            return list(self.__class__._injected)

    _FilteredStrategy._injected = filtered_signals
    filt_strategy = _FilteredStrategy(eng_manifest)

    def ohlcv_provider(_s, _t, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        filt_strategy,
        [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    _cagr = float(k.get("cagr", 0.0))
    _net = float(k.get("net_pnl", 0.0))
    if _net == 0.0 and _cagr != 0.0:
        _net = initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "n_bars": len(df),
        "n_raw_signals": len(raw_signals),
        "n_filtered_signals": len(filtered_signals),
        "n_rejected": n_rejected,
        "rejection_rate": n_rejected / max(1, len(raw_signals)),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": _cagr,
        "net_pnl": _net,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
    }


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict], label: str, cap_per_sym: float = 10_000.0) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print(f"\n{'='*70}")
    print(f"PORTFOLIO AGREGATE — {label}")
    print(f"{'='*70}")
    if not valid:
        print("  Hicbir sembolde trade yok.")
        return {"avg_sharpe": 0.0, "annual": 0.0, "avg_dd": 0.0, "n_trades": 0, "avg_win": 0.0}

    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting_equity = cap_per_sym * len(valid)
    total_return = net_pnl / starting_equity
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

    print(f"  Sembol sayisi          : {len(valid)}/{len(results)}")
    print(f"  Toplam trade           : {n_trades}")
    print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
    print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
    print(f"  Yillik (annualized)    : {annual:+.1f}%")
    print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
    print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
    print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
    return {
        "avg_sharpe": avg_sharpe, "annual": annual, "avg_dd": avg_dd,
        "n_trades": n_trades, "avg_win": avg_win, "avg_cagr": avg_cagr,
        "net_pnl": net_pnl, "valid_symbols": len(valid),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]


def main() -> int:
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.sentiment_filter import SentimentFilterStrategy

    print("\n" + "=" * 70)
    print("H18 — Fear & Greed Sentiment Backtest")
    print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # F&G veri yukle
    print("\n[0] F&G Veri Yukleme")
    fng_df = _load_fng_data()
    has_fng = not fng_df.empty

    eng_manifest = _make_engulfing_manifest()
    fng_manifest = _make_fng_manifest()

    # ---- SENARYO 1: Engulfing solo ----
    print("\n\n[S1] Engulfing Solo — 10 sembol x 1d (baseline)")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
    print("  " + "-" * 78)

    eng_results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one(sym, eng_manifest, EngulfingContinuationStrategy)
            eng_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            eng_results.append({"symbol": sym, "error": str(exc)})

    eng_agg = _aggregate(eng_results, "Engulfing SOLO (S1)")

    # ---- SENARYO 2: F&G Standalone (BTC only) ----
    print("\n\n[S2] F&G Standalone — BTC/USDT 1d")
    fng_results: list[dict] = []
    if has_fng:
        try:
            r = _run_one("BTC/USDT", fng_manifest, SentimentFilterStrategy, fng_df=fng_df)
            fng_results.append(r)
            if "error" in r:
                print(f"  BTC/USDT FAIL: {r['error']}")
            else:
                print(f"  BTC/USDT:")
                print(f"    Bars      : {r['n_bars']}")
                print(f"    Signals   : {r['n_signals']}")
                print(f"    Trades    : {r['n_trades']}")
                print(f"    Win Rate  : {r['win_rate']*100:.1f}%")
                print(f"    MaxDD     : {r['max_drawdown']*100:.1f}%")
                print(f"    Sharpe    : {r['sharpe']:.2f}")
                print(f"    CAGR      : {r['cagr']*100:.1f}%")
                print(f"    Net P&L   : ${r['net_pnl']:+,.0f}")
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            fng_results.append({"symbol": "BTC/USDT", "error": str(exc)})
    else:
        print("  SKIP: F&G verisi yok")
        fng_results.append({"symbol": "BTC/USDT", "error": "no_fng_data"})

    fng_agg_solo = {
        "avg_sharpe": fng_results[0].get("sharpe", 0.0) if fng_results and "error" not in fng_results[0] else 0.0,
        "annual": (((1 + fng_results[0].get("cagr", 0.0)) ** 1) - 1) * 100 if fng_results and "error" not in fng_results[0] else 0.0,
        "avg_dd": fng_results[0].get("max_drawdown", 0.0) if fng_results and "error" not in fng_results[0] else 0.0,
        "n_trades": fng_results[0].get("n_trades", 0) if fng_results and "error" not in fng_results[0] else 0,
        "avg_win": fng_results[0].get("win_rate", 0.0) if fng_results and "error" not in fng_results[0] else 0.0,
    }

    # ---- SENARYO 3: Engulfing + F&G Filter ----
    print("\n\n[S3] Engulfing + F&G Filtre — 10 sembol x 1d")
    print(f"  Parametre: long_max_fng=60, short_min_fng=40")

    if has_fng:
        print(f"  {'SYMBOL':<10} {'RAW_S':>5} {'FILT_S':>6} {'REJ%':>5} {'TRD':>4} "
              f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
        print("  " + "-" * 86)

        fng_filt_results: list[dict] = []
        for sym in SYMBOLS:
            try:
                r = _run_engulfing_fng_filtered(sym, eng_manifest, fng_df)
                fng_filt_results.append(r)
                if "error" in r:
                    print(f"  {sym:<10} FAIL: {r['error']}")
                else:
                    rej_pct = r.get("rejection_rate", 0.0) * 100
                    print(
                        f"  {sym:<10} {r['n_raw_signals']:>5} {r['n_filtered_signals']:>6} "
                        f"{rej_pct:>5.0f}% {r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                        f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                        f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                        f"{r['net_pnl']:>+9.0f}"
                    )
            except Exception as exc:
                print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                fng_filt_results.append({"symbol": sym, "error": str(exc)})

        fng_filt_agg = _aggregate(fng_filt_results, "Engulfing + F&G Filter (S3)")
    else:
        print("  SKIP: F&G verisi yok")
        fng_filt_results = []
        fng_filt_agg = {"avg_sharpe": 0.0, "annual": 0.0, "avg_dd": 0.0, "n_trades": 0, "avg_win": 0.0}

    # ---- Karsilastirma Tablosu ----
    print("\n\n" + "=" * 70)
    print("KARSILASTIRMA TABLOSU — H18 Fear & Greed")
    print("=" * 70)
    print(f"  {'Metrik':<28} {'S1: Eng Solo':>14} {'S2: FNG BTConly':>15} {'S3: Eng+FNG':>13}")
    print("  " + "-" * 72)
    print(f"  {'Avg Sharpe':<28} {eng_agg.get('avg_sharpe', 0):>14.2f} "
          f"{fng_agg_solo.get('avg_sharpe', 0):>15.2f} {fng_filt_agg.get('avg_sharpe', 0):>13.2f}")
    print(f"  {'Yillik (annualized %)':<28} {eng_agg.get('annual', 0):>14.1f} "
          f"{fng_agg_solo.get('annual', 0):>15.1f} {fng_filt_agg.get('annual', 0):>13.1f}")
    print(f"  {'Avg MaxDD (%)':<28} {eng_agg.get('avg_dd', 0)*100:>14.1f} "
          f"{fng_agg_solo.get('avg_dd', 0)*100:>15.1f} {fng_filt_agg.get('avg_dd', 0)*100:>13.1f}")
    print(f"  {'Toplam Trade':<28} {eng_agg.get('n_trades', 0):>14d} "
          f"{fng_agg_solo.get('n_trades', 0):>15d} {fng_filt_agg.get('n_trades', 0):>13d}")
    print(f"  {'Avg Win Rate (%)':<28} {eng_agg.get('avg_win', 0)*100:>14.1f} "
          f"{fng_agg_solo.get('avg_win', 0)*100:>15.1f} {fng_filt_agg.get('avg_win', 0)*100:>13.1f}")

    # Signal reduction
    if has_fng and fng_filt_results:
        valid_filt = [r for r in fng_filt_results if "error" not in r]
        valid_eng = [r for r in eng_results if "error" not in r]
        if valid_filt and valid_eng:
            total_raw = sum(r.get("n_raw_signals", 0) for r in valid_filt)
            total_filt = sum(r.get("n_filtered_signals", 0) for r in valid_filt)
            overall_rej = (total_raw - total_filt) / max(1, total_raw) * 100
            print(f"\n  Sinyal Azalmasi (S3 vs S1)")
            print(f"    Raw signals   : {total_raw}")
            print(f"    After filter  : {total_filt}")
            print(f"    Rejection     : {overall_rej:.1f}%")

            # Win rate change
            eng_wr = eng_agg.get("avg_win", 0.0) * 100
            fng_wr = fng_filt_agg.get("avg_win", 0.0) * 100
            wr_delta = fng_wr - eng_wr
            print(f"\n  Win Rate Degisimi  : {eng_wr:.1f}% → {fng_wr:.1f}% "
                  f"({'+'if wr_delta>=0 else ''}{wr_delta:.1f}pp)")

            # Return change
            eng_ann = eng_agg.get("annual", 0.0)
            fng_ann = fng_filt_agg.get("annual", 0.0)
            ret_delta = fng_ann - eng_ann
            print(f"  Yillik Getiri Deg  : {eng_ann:.1f}% → {fng_ann:.1f}% "
                  f"({'+'if ret_delta>=0 else ''}{ret_delta:.1f}pp)")

    # ---- VERDICT ----
    print("\n\n" + "=" * 70)
    print("VERDICT — H18 Fear & Greed Sentiment")
    print("=" * 70)

    # Gate kontrolu
    fng_s = fng_agg_solo.get("avg_sharpe", 0.0)
    fng_ann = fng_agg_solo.get("annual", 0.0)
    fng_dd = fng_agg_solo.get("avg_dd", 0.0)
    fng_win = fng_agg_solo.get("avg_win", 0.0)
    fng_n = fng_agg_solo.get("n_trades", 0)

    filt_s = fng_filt_agg.get("avg_sharpe", 0.0)
    filt_ann = fng_filt_agg.get("annual", 0.0)
    eng_ann_base = eng_agg.get("annual", 0.0)
    filt_delta = filt_ann - eng_ann_base

    print("\n  [S2] F&G Standalone Gates:")
    gates = [
        ("Yillik > 20%", fng_ann, 20.0, ">="),
        ("Sharpe > 0.6", fng_s, 0.6, ">="),
        ("MaxDD < 35%", fng_dd * 100, 35.0, "<="),
        ("Win Rate > 45%", fng_win * 100, 45.0, ">="),
        ("Trade >= 10", float(fng_n), 10.0, ">="),
    ]
    passes_s2 = 0
    for lbl, val, tgt, op in gates:
        ok = (val >= tgt) if op == ">=" else (val <= tgt)
        stat = "[PASS]" if ok else "[FAIL]"
        if ok:
            passes_s2 += 1
        print(f"    {lbl:<20} actual={val:>8.1f}  target={tgt:>5.1f}  {stat}")

    print("\n  [S3] Engulfing + F&G Filter Gates:")
    filter_gates = [
        ("Win rate >= S1", (fng_filt_agg.get("avg_win", 0.0) - eng_agg.get("avg_win", 0.0)) * 100, 0.0, ">="),
        ("Annual >= S1-5pp", filt_delta, -5.0, ">="),
        ("Sharpe >= S1", filt_s - eng_agg.get("avg_sharpe", 0.0), 0.0, ">="),
    ]
    passes_s3 = 0
    for lbl, val, tgt, op in filter_gates:
        ok = (val >= tgt) if op == ">=" else (val <= tgt)
        stat = "[PASS]" if ok else "[FAIL]"
        if ok:
            passes_s3 += 1
        print(f"    {lbl:<25} delta={val:>+8.1f}  target={tgt:>+5.1f}  {stat}")

    print()

    # F&G arbitrajlanmis mi?
    print("  --- F&G Arbitraj Analizi ---")
    if fng_s < 0.3 and fng_ann < 10:
        arb_status = "ARBITRAJLANMIS"
        arb_detail = ("F&G edge istatistiksel olarak anlamsiz. "
                      "Widely-tracked index olarak piyasa bu sinyali fiyatlamis. "
                      "Retail behavioral persistence bu sembolde yeterli degil.")
    elif fng_s >= 0.3 and fng_ann >= 15:
        arb_status = "BEHAVIORAL PERSISTENCE VAR"
        arb_detail = ("F&G extremes hala anlamli edge sagliyor. "
                      "Retail yatirimcilar indeksi biliyor ama duygudan kacamadigi icin "
                      "arbitraj tam gerceklesmemis. Dikkat: bu zamanla azalabilir.")
    else:
        arb_status = "MARGINAL / BELIRSIZ"
        arb_detail = ("F&G orta duzey edge var; net bir sonuc yok. "
                      "Daha uzun veri veya farkli semboller gerekebilir.")

    print(f"  Durum: {arb_status}")
    print(f"  Analiz: {arb_detail}")

    print()

    # Final verdict
    if passes_s3 >= 2:
        verdict_filter = "PROMOTE_FILTER"
        filter_reason = "F&G filtresi engulfing'in win rate/return'unu iyilestiriyor."
    elif passes_s3 == 1:
        verdict_filter = "DEFER_FILTER"
        filter_reason = "F&G filtresi marginal iyilesme sagliyor; refinement gerekiyor."
    else:
        verdict_filter = "REJECT_FILTER"
        filter_reason = "F&G filtresi engulfing performansini iyilestirmiyor."

    if passes_s2 >= 3:
        verdict_standalone = "PROMOTE_STANDALONE"
        sa_reason = "F&G standalone pozitif edge — onchain/price-agnostik katman."
    elif passes_s2 >= 1:
        verdict_standalone = "DEFER_STANDALONE"
        sa_reason = "F&G standalone zayif sinyal — daha fazla veri/parametre gerekiyor."
    else:
        verdict_standalone = "REJECT_STANDALONE"
        sa_reason = "F&G standalone istatistiksel edge gosteremiyor."

    print(f"  [S2] VERDICT: {verdict_standalone}")
    print(f"       Gerekce: {sa_reason}")
    print(f"  [S3] VERDICT: {verdict_filter}")
    print(f"       Gerekce: {filter_reason}")

    # ---- Rapor kaydet ----
    report = {
        "hypothesis": "H18",
        "title": "Fear & Greed Sentiment",
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "s1_engulfing_solo": eng_results,
        "s2_fng_standalone": fng_results,
        "s3_engulfing_fng": fng_filt_results if has_fng else [],
        "aggregates": {
            "s1": eng_agg,
            "s2_btc_only": fng_agg_solo,
            "s3": fng_filt_agg,
        },
        "verdict_standalone": verdict_standalone,
        "verdict_filter": verdict_filter,
        "arbitrage_status": arb_status,
    }
    rp = ROOT / "reports" / "backtests" / f"h18_fear_greed_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
