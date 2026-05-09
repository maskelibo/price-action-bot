"""Compound F&G + MVRV Filter Backtest — H19.

4 senaryo karsilastirmasi (10 sembol x 1d x 3y):
    A) Engulfing solo          (baseline ~+%68 yillik)
    B) Engulfing + F&G alone   (promoted: win rate %50.6)
    C) Engulfing + MVRV alone  (BTC: real MVRV, alt'lar: skip filter)
    D) Engulfing + F&G + MVRV  (compound — hipotez H19)

Promote kriterleri (D vs B):
    Win rate uplift >= +5pp (yani B'nin %50.6 → D'de %55+)
    Sinyal azalmasi: 89 → 30-40 araliginda kabul edilebilir (max %60 azalma)

BTC MVRV: Coin Metrics Community API (canli; mock da kullanilabilir)
Alt'lar: MVRV yoktur, sadece F&G filtresi uygulanir.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_compound_filter_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# F&G veri yukleyici
# ---------------------------------------------------------------------------

def _load_fng_data() -> pd.DataFrame:
    """DuckDB veya API'den F&G yukle."""
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
    """Deterministik mock F&G (test amacli)."""
    rng = np.random.default_rng(42)
    days = pd.date_range("2018-01-01", periods=2500, freq="1D", tz="UTC")
    t = np.arange(len(days))
    base = 50 + 30 * np.sin(2 * np.pi * t / 365) + 15 * np.sin(2 * np.pi * t / 90)
    noise = rng.normal(0, 8, len(days))
    values = np.clip(base + noise, 0, 100).astype(int)

    def classify(v: int) -> str:
        if v < 25: return "Extreme Fear"
        if v < 50: return "Fear"
        if v < 75: return "Greed"
        return "Extreme Greed"

    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": [classify(v) for v in values],
    })


# ---------------------------------------------------------------------------
# MVRV veri yukleyici — BTC only
# ---------------------------------------------------------------------------

def _load_mvrv_data() -> pd.DataFrame:
    """Coin Metrics'ten BTC MVRV yukle. Basarisizsa mock."""
    try:
        from price_action.data.onchain_ingest import fetch_and_prepare_btc_onchain
        print("  MVRV: Coin Metrics API'den BTC on-chain verisi cekiliyor...")
        df = fetch_and_prepare_btc_onchain(years=4)
        if not df.empty and "CapMVRVCur" in df.columns:
            valid = df["CapMVRVCur"].notna().sum()
            print(f"  MVRV: {len(df)} gun cekildi, {valid} gecerli MVRV degeri "
                  f"({df['ts'].min().date()} - {df['ts'].max().date()})")
            return df
        print("  UYARI: MVRV bos geldi — mock veri kullaniliyor.")
    except Exception as exc:
        print(f"  UYARI: MVRV API hatasi: {exc}. Mock veri kullaniliyor.")

    return _mock_mvrv()


def _mock_mvrv() -> pd.DataFrame:
    """Deterministik mock MVRV (BTC cycle dinamiklerini yansitir)."""
    rng = np.random.default_rng(123)
    days = pd.date_range("2018-01-01", periods=2500, freq="1D", tz="UTC")
    t = np.arange(len(days))
    # Simulate BTC MVRV cycle: 4y halving cycle, range roughly 0.5-5
    cycle = 2.0 + 1.8 * np.sin(2 * np.pi * t / (4 * 365)) + 0.5 * np.sin(2 * np.pi * t / 365)
    noise = rng.normal(0, 0.15, len(days))
    mvrv = np.clip(cycle + noise, 0.4, 5.5)
    return pd.DataFrame({
        "ts": days,
        "CapMVRVCur": mvrv,
        "asset": "btc",
    })


# ---------------------------------------------------------------------------
# OHLCV yukleyici
# ---------------------------------------------------------------------------

def _load_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return pd.DataFrame()
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            [venue, symbol, tf],
        ).fetchdf()
        con.close()
    except Exception:
        return pd.DataFrame()

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


# ---------------------------------------------------------------------------
# Engulfing raw signal generator
# ---------------------------------------------------------------------------

def _get_engulfing_signals(symbol: str, manifest) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Returns (df_raw, df_feats, raw_signals). Empty on error."""
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_ohlcv(symbol, tf="1d")
    if df.empty:
        return df, df, []

    strategy = EngulfingContinuationStrategy(manifest)
    df_feats = strategy.prepare_features(df)
    raw_signals = strategy.generate_signals(df_feats)
    return df, df_feats, raw_signals


# ---------------------------------------------------------------------------
# Backtest runner — filtered signal injection pattern
# ---------------------------------------------------------------------------

def _run_backtest_with_signals(
    symbol: str,
    manifest,
    df_feats: pd.DataFrame,
    signals: list,
    initial_capital: float = 10_000.0,
) -> dict:
    """Run backtest with pre-filtered signals injected."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    if df_feats.empty:
        return {"symbol": symbol, "error": "no_data"}
    if not signals:
        return {
            "symbol": symbol, "n_bars": len(df_feats), "n_signals": 0,
            "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "max_drawdown": 0.0, "sharpe": 0.0, "cagr": 0.0,
            "net_pnl": 0.0, "equity_final": initial_capital, "elapsed_sec": 0.0,
        }

    # Inject pre-filtered signals via subclass override
    _injected = list(signals)

    class _FilteredStrategy(EngulfingContinuationStrategy):
        def generate_signals(self, df_inner):  # type: ignore[override]
            return list(_injected)

    filt_strategy = _FilteredStrategy(manifest)

    def ohlcv_provider(_s, _t, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    try:
        result = engine.run(
            filt_strategy,
            [symbol],
            start=df_feats["ts"].iloc[0].to_pydatetime(),
            end=df_feats["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=initial_capital,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=ohlcv_provider,
        )
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}

    k = result.kpis
    _cagr = float(k.get("cagr", 0.0))
    _net = float(k.get("net_pnl", 0.0))
    if _net == 0.0 and _cagr != 0.0:
        _net = initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "n_bars": len(df_feats),
        "n_signals": len(signals),
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
# Per-symbol compound filter runner
# ---------------------------------------------------------------------------

def _run_scenario(
    symbol: str,
    manifest,
    df_feats: pd.DataFrame,
    raw_signals: list,
    fng_df: pd.DataFrame | None,
    mvrv_df: pd.DataFrame | None,
    scenario: str,  # "A" | "B" | "C" | "D"
    initial_capital: float = 10_000.0,
) -> dict:
    """Run one scenario for one symbol. Returns result dict + filter metadata."""
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng
    from price_action.strategies.compound_sentiment_filter import compound_filter_engulfing

    n_raw = len(raw_signals)

    if scenario == "A":
        # Engulfing solo — no filter
        signals = raw_signals
        filter_meta = {"n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0}
    elif scenario == "B":
        # F&G only
        if fng_df is None or fng_df.empty:
            signals = raw_signals
            filter_meta = {"n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0, "note": "no_fng"}
        else:
            signals, n_rejected = filter_engulfing_with_fng(
                raw_signals, fng_df, long_max_fng=60.0, short_min_fng=40.0
            )
            filter_meta = {"n_raw": n_raw, "n_filtered": len(signals), "n_rejected": n_rejected}
    elif scenario == "C":
        # MVRV only (BTC: real; alt: no filter)
        if mvrv_df is None or mvrv_df.empty:
            signals = raw_signals
            filter_meta = {"n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0, "note": "no_mvrv"}
        else:
            filtered, stats, _ = compound_filter_engulfing(
                raw_signals,
                fng_df=None,        # F&G disabled
                mvrv_df=mvrv_df,
                fng_long_max=60.0,
                fng_short_min=40.0,
                mvrv_long_max=2.5,
                mvrv_short_min=1.5,
            )
            signals = filtered
            filter_meta = stats.to_dict()
            filter_meta["n_raw"] = n_raw
            filter_meta["n_filtered"] = len(signals)
    elif scenario == "D":
        # Compound: F&G + MVRV
        filtered, stats, _ = compound_filter_engulfing(
            raw_signals,
            fng_df=fng_df,
            mvrv_df=mvrv_df,
            fng_long_max=60.0,
            fng_short_min=40.0,
            mvrv_long_max=2.5,
            mvrv_short_min=1.5,
        )
        signals = filtered
        filter_meta = stats.to_dict()
        filter_meta["n_raw"] = n_raw
        filter_meta["n_filtered"] = len(signals)
    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    result = _run_backtest_with_signals(symbol, manifest, df_feats, signals, initial_capital)
    result["scenario"] = scenario
    result["filter_meta"] = filter_meta
    result["n_raw_signals"] = n_raw
    result["n_filtered_signals"] = len(signals)
    result["n_rejected"] = n_raw - len(signals)
    result["rejection_rate"] = (n_raw - len(signals)) / max(1, n_raw)
    return result


# ---------------------------------------------------------------------------
# Aggregate reporter
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict], label: str, cap_per_sym: float = 10_000.0) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print(f"\n{'='*72}")
    print(f"PORTFOLIO AGREGATE — {label}")
    print(f"{'='*72}")
    if not valid:
        print("  Hicbir sembolde trade yok.")
        return {
            "avg_sharpe": 0.0, "annual": 0.0, "avg_dd": 0.0, "n_trades": 0,
            "avg_win": 0.0, "avg_cagr": 0.0, "net_pnl": 0.0, "valid_symbols": 0,
        }

    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting_equity = cap_per_sym * len(valid)
    total_return = net_pnl / starting_equity
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

    total_raw = sum(r.get("n_raw_signals", 0) for r in results if "error" not in r)
    total_filt = sum(r.get("n_filtered_signals", 0) for r in results if "error" not in r)
    rej_rate = (total_raw - total_filt) / max(1, total_raw) * 100

    print(f"  Sembol sayisi          : {len(valid)}/{len(results)}")
    print(f"  Toplam trade           : {n_trades}")
    print(f"  Raw signals            : {total_raw} → {total_filt} (-%{rej_rate:.0f} elenme)")
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
        "total_raw_signals": total_raw, "total_filt_signals": total_filt,
        "rej_rate_pct": rej_rate,
    }


# ---------------------------------------------------------------------------
# Table printer
# ---------------------------------------------------------------------------

def _print_symbol_table(results: list[dict], scenario_label: str) -> None:
    header = (f"  {'SYMBOL':<10} {'RAW_S':>5} {'FILT_S':>6} {'REJ%':>5} {'TRD':>4} "
              f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
    print(f"\n[{scenario_label}]")
    print(header)
    print("  " + "-" * 88)
    for r in results:
        if "error" in r:
            print(f"  {r['symbol']:<10} FAIL: {r['error']}")
            continue
        rej_pct = r.get("rejection_rate", 0.0) * 100
        print(
            f"  {r['symbol']:<10} {r.get('n_raw_signals',0):>5} {r.get('n_filtered_signals',0):>6} "
            f"{rej_pct:>5.0f}% {r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
            f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
            f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
            f"{r['net_pnl']:>+9.0f}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]


def main() -> int:
    print("\n" + "=" * 72)
    print("H19 — Compound F&G + MVRV Filter Backtest")
    print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("4 senaryo: A=Solo, B=FNG, C=MVRV, D=Compound")
    print("=" * 72)

    # --- Veri yukle ---
    print("\n[0] Veri Yukleme")
    fng_df = _load_fng_data()
    mvrv_df = _load_mvrv_data()
    has_fng = not fng_df.empty
    has_mvrv = not mvrv_df.empty
    print(f"  F&G: {'OK' if has_fng else 'MISSING (mock)'}  "
          f"MVRV: {'OK' if has_mvrv else 'MISSING (mock)'}")

    eng_manifest = _make_engulfing_manifest()

    # --- Pre-compute engulfing signals per symbol ---
    print("\n[1] Engulfing sinyalleri hesaplaniyor...")
    symbol_data: dict[str, tuple] = {}
    for sym in SYMBOLS:
        try:
            df_raw, df_feats, raw_sigs = _get_engulfing_signals(sym, eng_manifest)
            symbol_data[sym] = (df_raw, df_feats, raw_sigs)
            n = len(raw_sigs) if raw_sigs else 0
            status = "OK" if not df_feats.empty else "NO_DATA"
            print(f"  {sym:<12} {status}  signals={n}")
        except Exception as exc:
            print(f"  {sym:<12} ERROR: {exc}")
            symbol_data[sym] = (pd.DataFrame(), pd.DataFrame(), [])

    # --- Run 4 scenarios ---
    results: dict[str, list[dict]] = {"A": [], "B": [], "C": [], "D": []}

    for scenario in ("A", "B", "C", "D"):
        use_fng = fng_df if scenario in ("B", "D") else None
        use_mvrv = mvrv_df if scenario in ("C", "D") else None

        for sym in SYMBOLS:
            df_raw, df_feats, raw_sigs = symbol_data.get(sym, (pd.DataFrame(), pd.DataFrame(), []))
            try:
                r = _run_scenario(
                    sym, eng_manifest, df_feats, raw_sigs,
                    fng_df=use_fng,
                    mvrv_df=use_mvrv,
                    scenario=scenario,
                )
                results[scenario].append(r)
            except Exception as exc:
                print(f"  [{scenario}] {sym} EXCEPTION: {exc}")
                traceback.print_exc()
                results[scenario].append({"symbol": sym, "scenario": scenario, "error": str(exc)})

    # --- Per-scenario tables ---
    scenario_labels = {
        "A": "A: Engulfing Solo (baseline)",
        "B": "B: Engulfing + F&G alone",
        "C": "C: Engulfing + MVRV alone (BTC real, alt'lar skip)",
        "D": "D: Engulfing + F&G + MVRV compound",
    }
    for s in ("A", "B", "C", "D"):
        _print_symbol_table(results[s], scenario_labels[s])

    # --- Aggregate ---
    aggs: dict[str, dict] = {}
    for s in ("A", "B", "C", "D"):
        aggs[s] = _aggregate(results[s], scenario_labels[s])

    # --- Comparison table ---
    print("\n\n" + "=" * 72)
    print("KARSILASTIRMA TABLOSU — H19 Compound F&G + MVRV")
    print("=" * 72)
    hdr = f"  {'Metrik':<26} {'A: Solo':>10} {'B: F&G':>10} {'C: MVRV':>10} {'D: Compound':>12}"
    print(hdr)
    print("  " + "-" * 70)

    def row(label: str, key: str, fmt: str = ".1f", scale: float = 1.0, suffix: str = "") -> None:
        vals = [aggs[s].get(key, 0.0) * scale for s in ("A", "B", "C", "D")]
        col_a, col_b, col_c, col_d = (f"{v:{fmt}}{suffix}" for v in vals)
        print(f"  {label:<26} {col_a:>10} {col_b:>10} {col_c:>10} {col_d:>12}")

    def row_int(label: str, key: str) -> None:
        vals = [int(aggs[s].get(key, 0)) for s in ("A", "B", "C", "D")]
        print(f"  {label:<26} {vals[0]:>10d} {vals[1]:>10d} {vals[2]:>10d} {vals[3]:>12d}")

    row("Avg Sharpe", "avg_sharpe", ".2f")
    row("Yillik (%)", "annual", ".1f", suffix="%")
    row("Avg MaxDD (%)", "avg_dd", ".1f", scale=100.0, suffix="%")
    row_int("Toplam Trade", "n_trades")
    row("Avg Win Rate (%)", "avg_win", ".1f", scale=100.0, suffix="%")
    row("Avg CAGR (%)", "avg_cagr", ".1f", scale=100.0, suffix="%")
    row_int("Gecerli Sembol", "valid_symbols")

    # Signal reduction
    print(f"\n  {'Sinyal Analizi':<26}")
    for s in ("A", "B", "C", "D"):
        raw = aggs[s].get("total_raw_signals", aggs[s].get("n_trades", 0) * 2)
        filt = aggs[s].get("total_filt_signals", raw)
        rej = aggs[s].get("rej_rate_pct", 0.0)
        print(f"    [{s}] Raw: {raw}, Filtered: {filt}, Eleme: {rej:.1f}%")

    # --- Win rate uplift analysis ---
    wr_a = aggs["A"].get("avg_win", 0.0) * 100
    wr_b = aggs["B"].get("avg_win", 0.0) * 100
    wr_c = aggs["C"].get("avg_win", 0.0) * 100
    wr_d = aggs["D"].get("avg_win", 0.0) * 100
    wr_d_vs_b = wr_d - wr_b
    wr_d_vs_a = wr_d - wr_a

    ann_a = aggs["A"].get("annual", 0.0)
    ann_b = aggs["B"].get("annual", 0.0)
    ann_d = aggs["D"].get("annual", 0.0)
    ann_d_vs_b = ann_d - ann_b

    print(f"\n  Win Rate Uplift:")
    print(f"    A (solo)   : {wr_a:.1f}%")
    print(f"    B (F&G)    : {wr_b:.1f}%  (delta vs A: {wr_b - wr_a:+.1f}pp)")
    print(f"    C (MVRV)   : {wr_c:.1f}%  (delta vs A: {wr_c - wr_a:+.1f}pp)")
    print(f"    D (compound): {wr_d:.1f}%  (delta vs A: {wr_d_vs_a:+.1f}pp, vs B: {wr_d_vs_b:+.1f}pp)")
    print(f"  Yillik Uplift (compound vs F&G alone): {ann_d_vs_b:+.1f}pp")

    # BTC signal count analysis
    btc_results = {s: next((r for r in results[s] if r.get("symbol") == "BTC/USDT"), {}) for s in ("A", "B", "C", "D")}
    print(f"\n  BTC sinyal analizi (compound fully active):")
    for s in ("A", "B", "C", "D"):
        br = btc_results[s]
        if "error" not in br and br:
            print(f"    [{s}] raw={br.get('n_raw_signals',0)}, filtered={br.get('n_filtered_signals',0)}, "
                  f"eleme={br.get('rejection_rate',0)*100:.0f}%  "
                  f"WR={br.get('win_rate',0)*100:.1f}%  CAGR={br.get('cagr',0)*100:.1f}%")

    # --- VERDICT ---
    print("\n\n" + "=" * 72)
    print("VERDICT — H19 Compound F&G + MVRV Filter")
    print("=" * 72)

    # Promote criteria for compound:
    # 1. Win rate D >= B + 5pp  (main hypothesis)
    # 2. Annual D >= B - 5pp    (not dramatically worse)
    # 3. Signal count: not collapsed (< 60% reduction vs A)
    total_raw_a = aggs["A"].get("total_raw_signals", 0)
    total_filt_d = aggs["D"].get("total_filt_signals", 0)
    sig_reduction_pct = (total_raw_a - total_filt_d) / max(1, total_raw_a) * 100

    gates = [
        ("Win rate D >= B + 5pp",    wr_d_vs_b,      5.0,  ">="),
        ("Annual D >= B - 5pp",      ann_d_vs_b,    -5.0,  ">="),
        ("Signal reduction <= 60%",  sig_reduction_pct, 60.0, "<="),
    ]

    n_pass = 0
    print("\n  Compound vs F&G-alone Gates:")
    for lbl, val, tgt, op in gates:
        ok = (val >= tgt) if op == ">=" else (val <= tgt)
        stat = "[PASS]" if ok else "[FAIL]"
        if ok:
            n_pass += 1
        print(f"    {lbl:<30} val={val:>+8.1f}  target={tgt:>+6.1f}  {stat}")

    # Addl context
    print(f"\n  F&G alone uplift (B vs A): win {wr_b - wr_a:+.1f}pp, annual {ann_b - ann_a:+.1f}pp")
    print(f"  MVRV alone uplift (C vs A): win {wr_c - wr_a:+.1f}pp")

    if n_pass == 3:
        verdict = "PROMOTE"
        reason = (
            f"Compound filter (D) wins on all 3 gates. "
            f"Win rate uplift vs F&G alone: {wr_d_vs_b:+.1f}pp. "
            f"Both F&G and MVRV contribute independent signal quality."
        )
    elif n_pass == 2:
        verdict = "DEFER"
        reason = (
            f"Compound filter passes 2/3 gates. "
            f"Win rate uplift D vs B: {wr_d_vs_b:+.1f}pp (target +5pp). "
            f"Consider threshold tuning or longer test window."
        )
    elif wr_d_vs_b >= 0 and ann_d_vs_b >= 0:
        verdict = "MARGINAL_PROMOTE"
        reason = (
            f"Compound marginally better than F&G alone but below +5pp threshold. "
            f"Win rate D vs B: {wr_d_vs_b:+.1f}pp. "
            f"KEEP F&G alone until more data confirms compound edge."
        )
    else:
        verdict = "KEEP_FNG_ALONE"
        reason = (
            f"Compound does NOT improve over F&G alone. "
            f"Win rate D vs B: {wr_d_vs_b:+.1f}pp (target +5pp — MISS). "
            f"MVRV is redundant on this universe. Keep F&G alone."
        )

    print(f"\n  VERDICT: {verdict}")
    print(f"  Gerekce: {reason}")

    # Signal collapse warning
    if sig_reduction_pct > 60:
        print(f"\n  UYARI: Sinyal sayisi cok dusuk — {sig_reduction_pct:.0f}% elenme (limit: 60%).")
        print(f"  Compound, istatistiksel guvenilirlik icin yetersiz sample uretiyor.")
        print(f"  MVRV esiklerini gevset veya sadece F&G'yi kullan.")
    else:
        print(f"\n  Sinyal elenme: {sig_reduction_pct:.0f}% — kabul edilebilir aralik icerisinde.")

    # --- Save report ---
    report = {
        "hypothesis": "H19",
        "title": "Compound F&G + MVRV Filter",
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "scenarios": {s: results[s] for s in ("A", "B", "C", "D")},
        "aggregates": {s: aggs[s] for s in ("A", "B", "C", "D")},
        "verdict": verdict,
        "verdict_reason": reason,
        "wr_uplift_D_vs_B_pp": wr_d_vs_b,
        "annual_uplift_D_vs_B_pp": ann_d_vs_b,
        "signal_reduction_pct": sig_reduction_pct,
    }
    rp = (ROOT / "reports" / "backtests" /
          f"h19_compound_filter_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
