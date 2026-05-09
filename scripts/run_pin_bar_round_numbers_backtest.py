"""Pin Bar at Round Numbers stratejisi — 3y backtest.

10 kripto sembolü * 1d * ~1095 bar.
Engulfing Continuation ile dekorelasyon karsilastirmasi dahil.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_pin_bar_round_numbers_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Manifest
# =====================================================================

def _make_pin_bar_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "pin_bar_round_numbers",
        "version": "1.0.0",
        "description": "Pin bar at institutional round number levels (Volman)",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "wick_ratio_min": 0.60,
                        "round_proximity_atr": 0.3,
                    },
                },
                {
                    "id": "bearish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "wick_ratio_min": 0.60,
                        "round_proximity_atr": 0.3,
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
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "pin_tail", "tail_atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_engulfing_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
                {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 120, "cluster_atr_multiplier": 0.5,
                                       "min_touches": 2, "max_age_bars": 120},
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0,
                        "kaufman_er_period": 14, "kaufman_er_min": 0.20,
                        "bear_regime_size_factor": 0.5},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Data loader
# =====================================================================

def _load_symbol_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
        [venue, symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"]        = pd.to_datetime(df["ts"], utc=True)
    df["symbol"]    = symbol
    df["timeframe"] = tf
    df["venue"]     = venue
    return df


# =====================================================================
# Run one symbol
# =====================================================================

def _run_pin_bar(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.pin_bar_round_numbers import PinBarRoundNumbersStrategy

    df = _load_symbol_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy  = PinBarRoundNumbersStrategy(manifest)
    df_feats  = strategy.prepare_features(df)
    signals   = strategy.generate_signals(df_feats)

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
    k        = result.kpis
    _cagr    = float(k.get("cagr", 0.0))
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** 3 - 1)

    # Signal stats
    long_sigs  = [s for s in signals if s.direction == "long"]
    short_sigs = [s for s in signals if s.direction == "short"]

    return {
        "symbol":       symbol,
        "n_bars":       len(df),
        "first_ts":     str(df["ts"].iloc[0].date()),
        "last_ts":      str(df["ts"].iloc[-1].date()),
        "n_signals":    len(signals),
        "n_long":       len(long_sigs),
        "n_short":      len(short_sigs),
        "n_trades":     result.n_trades,
        "win_rate":     float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy":   float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe":       float(k.get("sharpe", 0.0)),
        "sortino":      float(k.get("sortino", 0.0)),
        "cagr":         _cagr,
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "net_pnl":      _net_pnl,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec":  result.elapsed_sec,
        # Round number metadata
        "signal_dates": [str(s.ts.date()) for s in signals[:20]],  # ilk 20
        "round_levels":  list({
            round(s.metadata.get("round_level", 0.0)) for s in signals
        }),
    }


def _run_engulfing(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_symbol_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy  = EngulfingContinuationStrategy(manifest)
    df_feats  = strategy.prepare_features(df)
    signals   = strategy.generate_signals(df_feats)

    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy, [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d", initial_capital=initial_capital,
        fees={"taker": 0.00075, "maker": -0.00010}, slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    k        = result.kpis
    _cagr    = float(k.get("cagr", 0.0))
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** 3 - 1)
    return {
        "symbol":    symbol,
        "n_signals": len(signals),
        "n_trades":  result.n_trades,
        "win_rate":  float(k.get("win_rate", 0.0)),
        "cagr":      _cagr,
        "sharpe":    float(k.get("sharpe", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "net_pnl":   _net_pnl,
    }


# =====================================================================
# Decorrelation
# =====================================================================

def _decorrelation(pb_results: list[dict], eng_results: list[dict]) -> dict:
    """Pin bar ile engulfing sinyal zamanlarinin ortusme orani."""
    pb_sym  = {r["symbol"]: set(r.get("signal_dates", [])) for r in pb_results if "error" not in r}
    # Engulfing signal dates bilgisi yok ama trade sayisindan yaklasim yapabiliriz
    eng_trades = {r["symbol"]: r.get("n_trades", 0) for r in eng_results if "error" not in r}
    pb_trades  = {r["symbol"]: r.get("n_trades", 0) for r in pb_results if "error" not in r}

    # Pearson R: trade count zaman serisi (proxy, gercek tarih verisiz)
    import numpy as np
    shared = sorted(set(pb_trades) & set(eng_trades))
    if len(shared) < 2:
        return {"note": "insufficient symbols for decorrelation"}
    pb_v  = [pb_trades[s]  for s in shared]
    eng_v = [eng_trades[s] for s in shared]
    pb_a  = pb_v  if sum(pb_v)  > 0 else [0.0] * len(shared)
    eng_a = eng_v if sum(eng_v) > 0 else [0.0] * len(shared)

    # If variance is zero correlation is undefined
    if len(set(pb_a)) == 1 or len(set(eng_a)) == 1:
        corr = 0.0
    else:
        corr = float(
            pd.Series(pb_a).corr(pd.Series(eng_a))
        )

    return {
        "symbols_compared": shared,
        "pin_bar_trade_counts":  pb_v,
        "engulfing_trade_counts": eng_v,
        "trade_count_pearson_r": round(corr, 3),
        "decorrelation_assessment": (
            "LOW (good complement)"  if abs(corr) < 0.3 else
            "MODERATE"               if abs(corr) < 0.6 else
            "HIGH (similar signals)"
        ),
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    pb_manifest  = _make_pin_bar_manifest()
    eng_manifest = _make_engulfing_manifest()

    print("=" * 80)
    print("  Pin Bar at Round Numbers — 10 sembol x 1d x 3y")
    print("  Volman institutional magnet reversal")
    print("=" * 80)
    print()
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>5} {'L':>3} {'S':>3} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>6} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 88)

    pb_results:  list[dict] = []
    eng_results: list[dict] = []

    for sym in symbols:
        try:
            r = _run_pin_bar(sym, pb_manifest)
            pb_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>5} "
                    f"{r['n_long']:>3} {r['n_short']:>3} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>6.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            pb_results.append({"symbol": sym, "error": str(exc)})

    # Engulfing comparison (same symbols)
    print("\n  --- Karsilastirma: Engulfing Continuation ---")
    print(f"  {'SYMBOL':<10} {'SIGS':>5} {'TRD':>4} {'WIN%':>6} {'SHR':>6} {'CAGR%':>7}")
    print("  " + "-" * 50)
    for sym in symbols:
        try:
            r = _run_engulfing(sym, eng_manifest)
            eng_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_signals']:>5} {r['n_trades']:>4} "
                    f"{r['win_rate']*100:>6.1f} {r['sharpe']:>6.2f} {r['cagr']*100:>7.1f}"
                )
        except Exception as exc:
            eng_results.append({"symbol": sym, "error": str(exc)})
            print(f"  {sym:<10} ENG ERR: {exc}")

    # ── Aggregate ──────────────────────────────────────────────────────
    valid = [r for r in pb_results if "error" not in r and r.get("n_trades", 0) > 0]
    print()
    print("=" * 80)
    print("  PIN BAR AGGREGATE (equal-weight, naive)")
    print("=" * 80)
    if valid:
        n_signals = sum(r["n_signals"] for r in valid)
        n_trades  = sum(r["n_trades"]  for r in valid)
        avg_win   = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
        net_pnl   = sum(r["net_pnl"]  for r in valid)
        start_eq  = 10_000.0 * len(valid)
        total_ret = net_pnl / start_eq
        avg_dd    = sum(r["max_drawdown"]   for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"]        for r in valid) / len(valid)
        avg_cagr   = sum(r["cagr"]          for r in valid) / len(valid)
        avg_pf     = sum(r["profit_factor"] for r in valid) / len(valid)
        annual     = (((1 + total_ret) ** (1 / 3)) - 1) * 100

        # Signal rarity
        bars_total = sum(r["n_bars"] for r in valid)
        sig_per_year = n_signals / max(1, bars_total / 365.0)

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(symbols)}")
        print(f"  Toplam sinyal          : {n_signals}  "
              f"({n_signals/len(valid):.1f} per symbol) | {sig_per_year:.1f} per year/symbol")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_ret*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")
    else:
        print("  Hicbir sembolde trade yok.")
        n_signals = n_trades = 0
        avg_win = avg_dd = avg_sharpe = avg_cagr = avg_pf = annual = 0.0

    # ── Decorrelation ──────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  DEKORELASYON (Pin Bar vs Engulfing Continuation)")
    print("=" * 80)
    dcorr = _decorrelation(pb_results, eng_results)
    for k, v in dcorr.items():
        if k == "symbols_compared":
            continue
        print(f"  {k:<32}: {v}")

    # ── Verdict ───────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  VERDICT")
    print("=" * 80)

    verdict_items = [
        ("Sinyal nadirligi (rare signal threshold < 30/yr)", sig_per_year if valid else 0, 30, "<="),
        ("Win rate > 50%", avg_win * 100, 50.0, ">="),
        ("Yillik return > 10%", annual, 10.0, ">="),
        ("Avg MaxDD < 30%", avg_dd * 100, 30.0, "<="),
        ("Sharpe > 0.5", avg_sharpe, 0.5, ">="),
    ]

    all_pass = True
    for label, value, target, op in verdict_items:
        ok = (value >= target) if op == ">=" else (value <= target)
        status = "[PASS]" if ok else "[FAIL]"
        all_pass = all_pass and ok
        print(f"  {label:<48} val={value:>8.2f}  tgt={target:>6.1f}  {status}")

    print()
    if valid and n_trades > 0:
        if all_pass:
            print("  VERDICT: ADOPT — Pin bar at round numbers, portfolio eklenmeli.")
        elif avg_win > 0.5 and n_trades > 5:
            print("  VERDICT: CONDITIONAL — Parametre ayari ile kabul edilebilir.")
        else:
            print("  VERDICT: REJECT — Istatistiksel edge yetersiz.")
    else:
        print("  VERDICT: INSUFFICIENT DATA — Veri eksik veya sinyal yok.")
        print("  Not: Round number seviyelerinde daha dar ATR toleransi denenebilir.")

    # ── Save report ────────────────────────────────────────────────────
    report = {
        "strategy":         "pin_bar_round_numbers",
        "run_ts":           datetime.now(timezone.utc).isoformat(),
        "symbols":          symbols,
        "pin_bar_results":  pb_results,
        "engulfing_results": eng_results,
        "decorrelation":    dcorr,
        "aggregate": {
            "n_signals": n_signals,
            "n_trades":  n_trades,
            "win_rate":  avg_win,
            "annual_pct": annual,
            "max_dd":    avg_dd,
            "sharpe":    avg_sharpe,
            "cagr":      avg_cagr,
        },
    }
    report_path = (
        ROOT / "reports" / "backtests" /
        f"pin_bar_round_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
