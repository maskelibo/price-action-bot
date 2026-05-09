"""OBV + F&G Compound Filter Backtest — H20.

4 senaryo karsilastirmasi (10 sembol x 1d x 3y, real data):
    A) Engulfing solo          (baseline ~%44 win rate)
    B) Engulfing + F&G alone   (mevcut PROMOTE: ~%50.6, 166->89 sinyal)
    C) Engulfing + OBV alone   (mevcut PROMOTE: yuksek WR, az sinyal)
    D) Engulfing + F&G + OBV   (compound — hipotez H20)

Promote kriterleri (D vs B):
    Win rate uplift >= +5pp  (D'nin B'den daha iyi olmasi)
    Sinyal azalmasi: kabul edilebilir (<= %75 reduction vs A)
    Yillik getiri: D >= B - 3pp (dramatik bozulma yok)

Lookahead garantisi:
    - F&G: shift(1) — filter_engulfing_with_fng() icinde
    - OBV: shift(1) implicit — _linreg_slope [i-window..i-1] kullaniyor
    - HER IKISI de t aninda t-1 degerini kullanir

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_obv_fng_compound_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# F&G veri yukleyici
# ---------------------------------------------------------------------------

def _load_fng_data() -> pd.DataFrame:
    """DuckDB veya alternative.me API'den F&G yukle."""
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
        if v < 25:
            return "Extreme Fear"
        if v < 50:
            return "Fear"
        if v < 75:
            return "Greed"
        return "Extreme Greed"

    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": [classify(v) for v in values],
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
# Manifest fabrika
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
# OBV filter — wraps filter_with_obv_divergence using raw OHLCV df
# ---------------------------------------------------------------------------

def _apply_obv_filter(
    signals: list,
    df_feats: pd.DataFrame,
    obv_lookback: int = 20,
) -> tuple[list, int]:
    """Apply OBV divergence filter to engulfing signals.

    Uses filter_with_obv_divergence() from obv_engulfing_confluence.
    The OBV slope is computed on [i-lookback..i-1] — lookahead-free.

    Parameters
    ----------
    signals:
        Raw engulfing signals.
    df_feats:
        Prepared OHLCV DataFrame (must include close, volume, ts columns).
    obv_lookback:
        OBV slope window (bars). Default 20.

    Returns
    -------
    (filtered_signals, n_rejected)
    """
    from price_action.strategies.obv_engulfing_confluence import filter_with_obv_divergence

    if not signals or df_feats.empty:
        return signals, 0

    return filter_with_obv_divergence(signals, df_feats, lookback=obv_lookback)


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
# Per-symbol scenario runner
# ---------------------------------------------------------------------------

def _run_scenario(
    symbol: str,
    manifest,
    df_feats: pd.DataFrame,
    raw_signals: list,
    fng_df: pd.DataFrame | None,
    scenario: str,  # "A" | "B" | "C" | "D"
    initial_capital: float = 10_000.0,
    obv_lookback: int = 20,
) -> dict:
    """Run one scenario for one symbol.

    A: Engulfing solo
    B: Engulfing + F&G
    C: Engulfing + OBV divergence
    D: Engulfing + F&G + OBV (compound)
    """
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

    n_raw = len(raw_signals)

    if scenario == "A":
        # Solo — no filter
        signals = raw_signals
        filter_meta = {
            "n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0,
            "n_rejected_fng": 0, "n_rejected_obv": 0,
        }

    elif scenario == "B":
        # F&G only — strict shift(1)
        if fng_df is None or fng_df.empty:
            signals = raw_signals
            filter_meta = {
                "n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0,
                "n_rejected_fng": 0, "n_rejected_obv": 0, "note": "no_fng",
            }
        else:
            signals, n_rej_fng = filter_engulfing_with_fng(
                raw_signals, fng_df,
                long_max_fng=60.0,
                short_min_fng=40.0,
            )
            filter_meta = {
                "n_raw": n_raw, "n_filtered": len(signals),
                "n_rejected": n_rej_fng, "n_rejected_fng": n_rej_fng, "n_rejected_obv": 0,
            }

    elif scenario == "C":
        # OBV only — shift(1) implicit in _linreg_slope [i-window..i-1]
        if df_feats.empty:
            signals = raw_signals
            filter_meta = {
                "n_raw": n_raw, "n_filtered": n_raw, "n_rejected": 0,
                "n_rejected_fng": 0, "n_rejected_obv": 0, "note": "no_data",
            }
        else:
            signals, n_rej_obv = _apply_obv_filter(
                raw_signals, df_feats, obv_lookback=obv_lookback
            )
            filter_meta = {
                "n_raw": n_raw, "n_filtered": len(signals),
                "n_rejected": n_rej_obv, "n_rejected_fng": 0, "n_rejected_obv": n_rej_obv,
            }

    elif scenario == "D":
        # Compound: F&G first, then OBV on survivors — both shift(1)
        n_rej_fng = 0
        n_rej_obv = 0

        # Step 1: F&G filter
        if fng_df is not None and not fng_df.empty:
            after_fng, n_rej_fng = filter_engulfing_with_fng(
                raw_signals, fng_df,
                long_max_fng=60.0,
                short_min_fng=40.0,
            )
        else:
            after_fng = raw_signals

        # Step 2: OBV filter on F&G survivors
        if not df_feats.empty and after_fng:
            signals, n_rej_obv = _apply_obv_filter(
                after_fng, df_feats, obv_lookback=obv_lookback
            )
        else:
            signals = after_fng

        n_total_rej = n_raw - len(signals)
        filter_meta = {
            "n_raw": n_raw,
            "n_after_fng": len(after_fng),
            "n_filtered": len(signals),
            "n_rejected": n_total_rej,
            "n_rejected_fng": n_rej_fng,
            "n_rejected_obv": n_rej_obv,
        }

    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    result = _run_backtest_with_signals(
        symbol, manifest, df_feats, signals, initial_capital
    )
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
            "total_raw_signals": 0, "total_filt_signals": 0, "rej_rate_pct": 0.0,
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
    print(f"  Raw signals            : {total_raw} -> {total_filt} (-%{rej_rate:.0f} elenme)")
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
    header = (
        f"  {'SYMBOL':<10} {'RAW_S':>5} {'FILT_S':>6} {'REJ%':>5} {'TRD':>4} "
        f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}"
    )
    print(f"\n[{scenario_label}]")
    print(header)
    print("  " + "-" * 88)

    for r in results:
        if "error" in r:
            print(f"  {r['symbol']:<10} FAIL: {r['error']}")
            continue
        rej_pct = r.get("rejection_rate", 0.0) * 100
        print(
            f"  {r['symbol']:<10} {r.get('n_raw_signals',0):>5} "
            f"{r.get('n_filtered_signals',0):>6} "
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

OBV_LOOKBACK = 20  # OBV slope penceresi (bar)


def main() -> int:
    print("\n" + "=" * 72)
    print("H20 — OBV + F&G Compound Filter Backtest")
    print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("4 senaryo: A=Solo, B=FNG, C=OBV, D=Compound(FNG+OBV)")
    print(f"OBV lookback: {OBV_LOOKBACK} bar")
    print("=" * 72)

    # --- Veri yukle ---
    print("\n[0] Veri Yukleme")
    fng_df = _load_fng_data()
    has_fng = not fng_df.empty
    print(f"  F&G: {'OK (' + str(len(fng_df)) + ' gun)' if has_fng else 'MISSING (mock)'}")

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
            print(f"  {sym:<12} {status}  signals={n}  bars={len(df_feats)}")
        except Exception as exc:
            print(f"  {sym:<12} ERROR: {exc}")
            symbol_data[sym] = (pd.DataFrame(), pd.DataFrame(), [])

    # --- Run 4 scenarios ---
    results: dict[str, list[dict]] = {"A": [], "B": [], "C": [], "D": []}

    print("\n[2] 4 senaryo calistiriliyor...")
    for scenario in ("A", "B", "C", "D"):
        use_fng = fng_df if scenario in ("B", "D") else None

        print(f"  Senaryo {scenario}:")
        for sym in SYMBOLS:
            df_raw, df_feats, raw_sigs = symbol_data.get(
                sym, (pd.DataFrame(), pd.DataFrame(), [])
            )
            try:
                r = _run_scenario(
                    sym, eng_manifest, df_feats, raw_sigs,
                    fng_df=use_fng,
                    scenario=scenario,
                    obv_lookback=OBV_LOOKBACK,
                )
                results[scenario].append(r)
                print(
                    f"    {sym:<12} raw={r.get('n_raw_signals',0):>3} "
                    f"filt={r.get('n_filtered_signals',0):>3} "
                    f"trd={r.get('n_trades',0):>3} "
                    f"WR={r.get('win_rate',0)*100:>5.1f}%"
                )
            except Exception as exc:
                print(f"    {sym:<12} EXCEPTION: {exc}")
                traceback.print_exc()
                results[scenario].append(
                    {"symbol": sym, "scenario": scenario, "error": str(exc)}
                )

    # --- Per-scenario tables ---
    scenario_labels = {
        "A": "A: Engulfing Solo (baseline)",
        "B": "B: Engulfing + F&G alone",
        "C": "C: Engulfing + OBV divergence",
        "D": "D: Engulfing + F&G + OBV (compound)",
    }
    for s in ("A", "B", "C", "D"):
        _print_symbol_table(results[s], scenario_labels[s])

    # --- Aggregate ---
    aggs: dict[str, dict] = {}
    for s in ("A", "B", "C", "D"):
        aggs[s] = _aggregate(results[s], scenario_labels[s])

    # --- Comparison table ---
    print("\n\n" + "=" * 72)
    print("KARSILASTIRMA TABLOSU — H20 OBV + F&G Compound Filter")
    print("=" * 72)
    hdr = (
        f"  {'Metrik':<26} {'A: Solo':>10} {'B: F&G':>10} "
        f"{'C: OBV':>10} {'D: Compound':>12}"
    )
    print(hdr)
    print("  " + "-" * 72)

    def row(label: str, key: str, fmt: str = ".1f", scale: float = 1.0, suffix: str = "") -> None:
        vals = [aggs[s].get(key, 0.0) * scale for s in ("A", "B", "C", "D")]
        cols = [f"{v:{fmt}}{suffix}" for v in vals]
        print(f"  {label:<26} {cols[0]:>10} {cols[1]:>10} {cols[2]:>10} {cols[3]:>12}")

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
        raw = aggs[s].get("total_raw_signals", 0)
        filt = aggs[s].get("total_filt_signals", raw)
        rej = aggs[s].get("rej_rate_pct", 0.0)
        print(f"    [{s}] Raw: {raw}, Filtered: {filt}, Eleme: {rej:.1f}%")

    # --- Win rate uplift analysis ---
    wr_a = aggs["A"].get("avg_win", 0.0) * 100
    wr_b = aggs["B"].get("avg_win", 0.0) * 100
    wr_c = aggs["C"].get("avg_win", 0.0) * 100
    wr_d = aggs["D"].get("avg_win", 0.0) * 100

    ann_a = aggs["A"].get("annual", 0.0)
    ann_b = aggs["B"].get("annual", 0.0)
    ann_c = aggs["C"].get("annual", 0.0)
    ann_d = aggs["D"].get("annual", 0.0)

    wr_d_vs_b = wr_d - wr_b
    wr_d_vs_c = wr_d - wr_c
    ann_d_vs_b = ann_d - ann_b

    print(f"\n  Win Rate Uplift:")
    print(f"    A (solo)    : {wr_a:.1f}%")
    print(f"    B (F&G)     : {wr_b:.1f}%  (delta vs A: {wr_b - wr_a:+.1f}pp)")
    print(f"    C (OBV)     : {wr_c:.1f}%  (delta vs A: {wr_c - wr_a:+.1f}pp)")
    print(f"    D (compound): {wr_d:.1f}%  "
          f"(delta vs A: {wr_d - wr_a:+.1f}pp, "
          f"vs B: {wr_d_vs_b:+.1f}pp, "
          f"vs C: {wr_d_vs_c:+.1f}pp)")
    print(f"  Yillik Uplift (compound vs F&G alone): {ann_d_vs_b:+.1f}pp")

    # Per-symbol compound filter breakdown
    print(f"\n  Per-symbol filtre dagitimi (D = compound):")
    for r in results["D"]:
        if "error" in r:
            continue
        fm = r.get("filter_meta", {})
        n_raw = fm.get("n_raw", 0)
        n_after_fng = fm.get("n_after_fng", "N/A")
        n_filt = fm.get("n_filtered", 0)
        n_rej_fng = fm.get("n_rejected_fng", 0)
        n_rej_obv = fm.get("n_rejected_obv", 0)
        print(
            f"    {r['symbol']:<12} raw={n_raw:>3}  "
            f"after_fng={str(n_after_fng):>3}  "
            f"final={n_filt:>3}  "
            f"[fng_rej={n_rej_fng} obv_rej={n_rej_obv}]  "
            f"WR={r.get('win_rate',0)*100:.1f}%"
        )

    # --- VERDICT ---
    print("\n\n" + "=" * 72)
    print("VERDICT — H20 OBV + F&G Compound Filter")
    print("=" * 72)

    total_raw_a = aggs["A"].get("total_raw_signals", 0)
    total_filt_d = aggs["D"].get("total_filt_signals", 0)
    sig_reduction_d = (total_raw_a - total_filt_d) / max(1, total_raw_a) * 100

    # Promote criteria:
    # 1. Compound WR >= F&G alone + 5pp (main gate — honesty principle)
    # 2. Annual D >= B - 3pp (not destroying returns)
    # 3. Signal count not collapsed (< 75% reduction)
    gates = [
        ("WR D >= B + 5pp",         wr_d_vs_b,        5.0,  ">="),
        ("Annual D >= B - 3pp",     ann_d_vs_b,       -3.0, ">="),
        ("Signal reduction <= 75%", sig_reduction_d,  75.0, "<="),
    ]

    n_pass = 0
    print("\n  Compound vs F&G-alone Gates:")
    for lbl, val, tgt, op in gates:
        ok = (val >= tgt) if op == ">=" else (val <= tgt)
        stat = "[PASS]" if ok else "[FAIL]"
        if ok:
            n_pass += 1
        print(f"    {lbl:<30} val={val:>+8.1f}  target={tgt:>+6.1f}  {stat}")

    # Context lines
    print(f"\n  F&G alone uplift (B vs A)  : win {wr_b - wr_a:+.1f}pp, annual {ann_b - ann_a:+.1f}pp")
    print(f"  OBV alone uplift (C vs A)  : win {wr_c - wr_a:+.1f}pp, annual {ann_c - ann_a:+.1f}pp")
    print(f"  Compound uplift (D vs B)   : win {wr_d_vs_b:+.1f}pp, annual {ann_d_vs_b:+.1f}pp")
    print(f"  Compound uplift (D vs C)   : win {wr_d_vs_c:+.1f}pp")
    print(f"  Sinyal elenme (D vs A)     : {sig_reduction_d:.0f}%")

    if n_pass == 3:
        verdict = "PROMOTE"
        reason = (
            f"Compound filter (D) wins on all 3 gates. "
            f"Win rate uplift vs F&G alone: {wr_d_vs_b:+.1f}pp (>= +5pp). "
            f"F&G and OBV are orthogonal filters — both contribute independently. "
            f"Deploy compound filter for engulfing strategy."
        )
    elif n_pass == 2 and wr_d_vs_b >= 5.0:
        verdict = "PROMOTE_WITH_WARNING"
        reason = (
            f"Compound passes win rate gate ({wr_d_vs_b:+.1f}pp) but 2/3 structural gates. "
            f"Monitor signal count ({sig_reduction_d:.0f}% reduction). "
            f"Deploy with caution; review after 3 more months of live data."
        )
    elif n_pass == 2:
        verdict = "DEFER"
        reason = (
            f"Compound passes 2/3 gates. "
            f"Win rate uplift D vs B: {wr_d_vs_b:+.1f}pp (target +5pp — MISS by "
            f"{5.0 - wr_d_vs_b:.1f}pp). "
            f"Consider OBV lookback tuning or extending test window to 5y."
        )
    elif wr_d_vs_b >= 0 and ann_d_vs_b >= 0:
        verdict = "KEEP_SEPARATE"
        reason = (
            f"Compound marginally better than F&G alone ({wr_d_vs_b:+.1f}pp) "
            f"but below +5pp threshold. "
            f"Overlap between F&G and OBV signals is too high. "
            f"KEEP F&G + OBV as separate independent strategies."
        )
    else:
        verdict = "REJECT_COMPOUND"
        reason = (
            f"Compound does NOT improve over F&G alone. "
            f"Win rate D vs B: {wr_d_vs_b:+.1f}pp (target +5pp — FAIL). "
            f"OBV filter adds no incremental value on top of F&G on this universe. "
            f"Run F&G and OBV strategies independently; do not compound them."
        )

    print(f"\n  VERDICT: {verdict}")
    print(f"  Gerekce: {reason}")

    if sig_reduction_d > 75:
        print(
            f"\n  UYARI: Compound sinyal sayisi cok dusuk — "
            f"{sig_reduction_d:.0f}% elenme (limit: 75%). "
            f"Istatistiksel guvenilirlik icin yetersiz sample. "
            f"OBV lookback'i azalt (20 -> 10) veya slope threshold'u gevset."
        )
    else:
        print(f"\n  Sinyal elenme: {sig_reduction_d:.0f}% — kabul edilebilir aralik.")

    # --- Save report ---
    report = {
        "hypothesis": "H20",
        "title": "OBV + F&G Compound Filter on Engulfing",
        "run_ts": datetime.now(timezone.utc).isoformat(),
        "obv_lookback": OBV_LOOKBACK,
        "scenarios": {s: results[s] for s in ("A", "B", "C", "D")},
        "aggregates": {s: aggs[s] for s in ("A", "B", "C", "D")},
        "verdict": verdict,
        "verdict_reason": reason,
        "wr_uplift_D_vs_B_pp": wr_d_vs_b,
        "wr_uplift_D_vs_C_pp": wr_d_vs_c,
        "annual_uplift_D_vs_B_pp": ann_d_vs_b,
        "signal_reduction_pct": sig_reduction_d,
        "gates_passed": n_pass,
        "gates_total": len(gates),
    }

    rp = (
        ROOT / "reports" / "backtests" /
        f"h20_obv_fng_compound_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {rp}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
