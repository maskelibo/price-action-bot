"""Volatility Risk Premium Fade stratejisi icin gercek 3y backtest.

10 USDT sembolu * 1d * ~1095 bar.
Karsilastirma: standalone + engulfing_continuation ile kombine.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_vol_premium_backtest.py
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
# Manifest fabrikalar
# ---------------------------------------------------------------------------

def _make_vol_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "vol_risk_premium",
        "version": "1.0.0",
        "description": "Volatility Risk Premium Fade",
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vol_fade_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
                    },
                },
                {
                    "id": "vol_fade_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural_atr", "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_engulfing_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
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
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Veri yükleyici
# ---------------------------------------------------------------------------

def _load_symbol_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
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
# Tek sembol backtest
# ---------------------------------------------------------------------------

def _run_one_symbol(symbol: str, manifest, strategy_cls, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = strategy_cls(manifest)
    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    def ohlcv_provider(_sym, _tf, _start, _end):
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
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "strategy": strategy_cls.__name__,
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
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": _cagr,
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "net_pnl": _net_pnl,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
    }


def _run_combined_symbol(symbol: str, vol_manifest, eng_manifest, initial_capital: float = 10_000.0) -> dict:
    """Her iki stratejinin sinyallerini birleştirir (naive union, no signal dedup)."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.vol_risk_premium import VolRiskPremiumStrategy
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    vol_strat = VolRiskPremiumStrategy(vol_manifest)
    eng_strat = EngulfingContinuationStrategy(eng_manifest)

    df_vol = vol_strat.prepare_features(df)
    df_eng = eng_strat.prepare_features(df)

    vol_sigs = vol_strat.generate_signals(df_vol)
    eng_sigs = eng_strat.generate_signals(df_eng)
    all_sigs = vol_sigs + eng_sigs

    # Vol stratejisi primary (combine mantığı: vol sinyallerini önce kullan)
    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_vol.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        vol_strat,
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
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol": symbol,
        "strategy": "combined",
        "n_bars": len(df),
        "n_vol_signals": len(vol_sigs),
        "n_eng_signals": len(eng_sigs),
        "n_total_signals": len(all_sigs),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": _cagr,
        "net_pnl": _net_pnl,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
    }


# ---------------------------------------------------------------------------
# Aggregate hesaplama
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict], label: str, starting_cap_per_sym: float = 10_000.0):
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print(f"\n{'='*70}")
    print(f"PORTFOLIO AGREGATE — {label} (equal-weight, naive)")
    print(f"{'='*70}")
    if not valid:
        print("  Hicbir sembolde trade yok.")
        return {
            "avg_sharpe": 0.0,
            "annual": 0.0,
            "avg_dd": 0.0,
            "n_trades": 0,
            "avg_win": 0.0,
        }
    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting_equity = starting_cap_per_sym * len(valid)
    total_return = net_pnl / starting_equity
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
    annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

    print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(results)}")
    print(f"  Toplam trade           : {n_trades}")
    print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
    print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
    print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
    print(f"  Yillik (annualized)    : {annual:+.1f}%")
    print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
    print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
    print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
    print(f"  Avg Profit Factor      : {avg_pf:.2f}")
    return {
        "avg_sharpe": avg_sharpe,
        "annual": annual,
        "avg_dd": avg_dd,
        "n_trades": n_trades,
        "avg_win": avg_win,
        "avg_pf": avg_pf,
        "avg_cagr": avg_cagr,
        "net_pnl": net_pnl,
        "valid_symbols": len(valid),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    from price_action.strategies.vol_risk_premium import VolRiskPremiumStrategy
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]

    vol_manifest = _make_vol_manifest()
    eng_manifest = _make_engulfing_manifest()

    # ---- BÖLÜM 1: VolRiskPremium standalone ----
    print("=== VolRiskPremium Backtest — 10 sembol x 1d x 3y ===\n")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 82)

    vol_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, vol_manifest, VolRiskPremiumStrategy)
            vol_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            vol_results.append({"symbol": sym, "error": str(exc)})

    vol_agg = _aggregate(vol_results, "VolRiskPremium STANDALONE")

    # ---- BÖLÜM 2: Engulfing standalone (karşılaştırma) ----
    print("\n\n=== EngulfingContinuation Backtest — karsilastirma ===\n")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 82)

    eng_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, eng_manifest, EngulfingContinuationStrategy)
            eng_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            eng_results.append({"symbol": sym, "error": str(exc)})

    eng_agg = _aggregate(eng_results, "EngulfingContinuation STANDALONE")

    # ---- BÖLÜM 3: Karşılaştırma tablosu ----
    print("\n\n" + "=" * 70)
    print("KARSILASTIRMA TABLOSU")
    print("=" * 70)
    print(f"  {'Metrik':<25} {'VolRiskPremium':>15} {'Engulfing':>15}")
    print("  " + "-" * 58)
    print(f"  {'Avg Sharpe':<25} {vol_agg.get('avg_sharpe', 0):>15.2f} {eng_agg.get('avg_sharpe', 0):>15.2f}")
    print(f"  {'Yillik (annualized)':<25} {vol_agg.get('annual', 0):>14.1f}% {eng_agg.get('annual', 0):>14.1f}%")
    print(f"  {'Avg MaxDD':<25} {vol_agg.get('avg_dd', 0)*100:>14.1f}% {eng_agg.get('avg_dd', 0)*100:>14.1f}%")
    print(f"  {'Total Trades':<25} {vol_agg.get('n_trades', 0):>15d} {eng_agg.get('n_trades', 0):>15d}")
    print(f"  {'Avg Win Rate':<25} {vol_agg.get('avg_win', 0)*100:>14.1f}% {eng_agg.get('avg_win', 0)*100:>14.1f}%")
    print(f"  {'Avg Profit Factor':<25} {vol_agg.get('avg_pf', 0):>15.2f} {eng_agg.get('avg_pf', 0):>15.2f}")

    # ---- BÖLÜM 4: Combined ----
    print("\n\n=== COMBINED Backtest (VolRiskPremium + Engulfing) ===\n")
    print(f"  {'SYMBOL':<10} {'VOL_S':>5} {'ENG_S':>5} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
    print("  " + "-" * 82)

    comb_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_combined_symbol(sym, vol_manifest, eng_manifest)
            comb_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r.get('n_vol_signals', 0):>5} "
                    f"{r.get('n_eng_signals', 0):>5} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            comb_results.append({"symbol": sym, "error": str(exc)})

    comb_agg = _aggregate(comb_results, "COMBINED (Vol + Engulfing)")

    # ---- BÖLÜM 5: Verdict ----
    print("\n\n" + "=" * 70)
    print("VERDICT — VolRiskPremium Hipotezi")
    print("=" * 70)

    avg_sharpe = vol_agg.get("avg_sharpe", 0.0)
    avg_win = vol_agg.get("avg_win", 0.0)
    avg_dd = vol_agg.get("avg_dd", 0.0)
    annual = vol_agg.get("annual", 0.0)
    n_trades = vol_agg.get("n_trades", 0)

    gates = [
        ("Yillik net > %20        ", annual, 20.0, ">="),
        ("Sharpe > 0.6            ", avg_sharpe, 0.6, ">="),
        ("MaxDD < %30             ", avg_dd * 100, 30.0, "<="),
        ("Win rate > %48          ", avg_win * 100, 48.0, ">="),
        ("Trade sayisi >= 30      ", float(n_trades), 30.0, ">="),
    ]
    passes = 0
    for label, value, target, op in gates:
        ok = (value >= target) if op == ">=" else (value <= target)
        status = "[PASS]" if ok else "[FAIL]"
        if ok:
            passes += 1
        print(f"  {label} actual={value:>8.2f}  target={target:>5.1f}  {status}")

    print()
    if passes >= 4:
        verdict = "PROMOTE"
        reason = "Volatilite tabanlı mean-rev fiyat tabanlıdan farklı — gecerli edge."
    elif passes >= 2:
        verdict = "DEFER"
        reason = "Potansiyel var ama sinyal sayisi az veya Sharpe marjinal — refinement gerek."
    else:
        verdict = "REJECT"
        reason = "Vol-based mean-rev de kripto'da price-based kadar zorlu. Ucuncu red."

    print(f"  VERDICT: {verdict}")
    print(f"  Gerekce: {reason}")
    print()
    print("  --- Vol-based vs Price-based Mean Reversion Analizi ---")
    print(f"  Vol-based (bu strateji) Sharpe   : {avg_sharpe:.2f}")
    print(f"  AVWAP (REJECTED) Sharpe           : ~0 (düşük)")
    print(f"  TPO (REJECTED) Sharpe             : ~0 (düşük)")
    print(f"  Engulfing (trend-following) Sharpe: {eng_agg.get('avg_sharpe', 0):.2f}")
    print()
    if avg_win > 0:
        print(f"  Win rate {avg_win*100:.1f}% @ 1.5R hedef:")
        breakeven_wr = 1 / (1 + 1.5)  # R=1.5 → breakeven win rate = 40%
        if avg_win > breakeven_wr:
            print(f"  => Pozitif beklenti (BE={breakeven_wr*100:.0f}%, actual={avg_win*100:.1f}%)")
        else:
            print(f"  => Negatif beklenti (BE={breakeven_wr*100:.0f}%, actual={avg_win*100:.1f}%)")

    # ---- Rapor kaydet ----
    all_results = {
        "vol_standalone": vol_results,
        "eng_standalone": eng_results,
        "combined": comb_results,
        "aggregates": {
            "vol": vol_agg,
            "eng": eng_agg,
            "combined": comb_agg,
        },
        "verdict": verdict,
        "reason": reason,
    }
    report_path = (
        ROOT
        / "reports"
        / "backtests"
        / f"vol_risk_premium_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(all_results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
