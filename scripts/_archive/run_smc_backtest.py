"""SMC Order Block + Liquidity Grab backtest — 10 USDT symbols × 1d × 3y.

Mirrors run_real_backtest.py but uses SMCOrderBlockStrategy with a tuned
manifest: primary_R=3.0, atr_mult_for_displacement=1.5.

Run:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_smc_backtest.py
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


def _make_smc_manifest():
    """SMC-tuned manifest.

    Key parameters:
    - primary_R = 3.0   (SMC tradition: higher R:R)
    - atr_mult_for_displacement = 1.5  (strategy spec)
    - atr_mult_for_sl = 1.0  (structural stop at OB edge + small buffer)
    - 200-EMA as bias filter (computed in prepare_features)
    """
    from price_action.strategies.base import StrategyManifest

    raw = {
        "name": "smc_orderblock",
        "version": "1.0.0",
        "description": "SMC Order Block + Liquidity Grab combo — 1D crypto",
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [],  # SMC uses its own detection, not classic patterns
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 50,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 50,
                },
                "require_proximity_to_sr_atr": 0.0,  # OB is the S/R — no additional SR filter
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
                "atr_mult_for_displacement": 1.5,  # strategy spec
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,   # OB + liq_grab = 2.0
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "structural",
                "atr_period": 14,
                "atr_multiplier": 1.0,   # OB edge + 1×ATR buffer
            },
            "take_profit": {
                "method": "r_multiple",
                "primary_R": 3.0,         # SMC tradition: 3R target
                "partial_R": 1.0,         # 1R partial close (tracked in metadata)
            },
            "position_sizing": {
                "method": "fixed_fractional",
                "risk_per_trade": 0.01,
            },
        },
        "backtest": {
            "warmup_bars": 250,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


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


def _run_one_symbol(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.smc_orderblock import SMCOrderBlockStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = SMCOrderBlockStrategy(manifest)
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
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", initial_capital) - initial_capital)),
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
    }


def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    manifest = _make_smc_manifest()
    results: list[dict] = []

    print("=" * 75)
    print("SMC ORDER BLOCK + LIQUIDITY GRAB BACKTEST")
    print(f"  Strategy  : smc_orderblock v1.0.0")
    print(f"  Universe  : {len(symbols)} USDT symbols, 1d, ~3y")
    print(f"  primary_R : 3.0  |  atr_mult_displacement : 1.5")
    print(f"  Stop      : OB edge + 1×ATR buffer")
    print(f"  Bias      : 200-EMA (long above, short below)")
    print("=" * 75)
    print()

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} bars={r['n_bars']:>4} sigs={r['n_signals']:>3} "
                    f"trades={r['n_trades']:>3} win={r['win_rate']*100:>5.1f}% "
                    f"PF={r['profit_factor']:>5.2f} DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f} ({r['elapsed_sec']:.1f}s)"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    # Aggregate
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print()
    print("=" * 75)
    print("PORTFOLIO AGGREGATE (equal-weight, naive)")
    print("=" * 75)

    if valid:
        n_trades = sum(r["n_trades"] for r in valid)
        avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
        net_pnl = sum(r["net_pnl"] for r in valid)
        starting_equity = 10_000.0 * len(valid)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
        avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
        avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
        annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

        print(f"  Symbols passing         : {len(valid)}/{len(symbols)}")
        print(f"  Total trades            : {n_trades}")
        print(f"  Aggregate win rate      : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L       : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return    : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Annualized              : {annual:+.1f}%")
        print(f"  Avg MaxDD               : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe              : {avg_sharpe:.2f}")
        print(f"  Avg CAGR                : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor       : {avg_pf:.2f}")

        print()
        print("--- COMPARISON vs BENCHMARKS ---")
        print(f"  classic_pa (Phase B)    : Sharpe=0.28, yearly=+2.1%")
        print(f"  SMC community claim     : win_rate=60-70% (unverified)")
        print(f"  This run (smc_ob)       : Sharpe={avg_sharpe:.2f}, yearly={annual:+.1f}%, "
              f"win_rate={avg_win*100:.1f}%")

        print()
        print("--- CRITICAL ASSESSMENT ---")
        print("  Signal rate reflects mechanical OB+LG detection; community SMC")
        print("  practitioners apply additional subjective filters (HTF context,")
        print("  kill zones, OB quality assessment) not captured here.")
        print("  Mechanical win rate likely below 60-70% community claim due to:")
        print("  1. No retroactive OB selection (all OBs treated equally).")
        print("  2. No kill-zone time filter (daily bar strategy ignores intraday timing).")
        print("  3. Lookahead-free detection may miss some 'obvious' OBs a live")
        print("     trader would identify by visual inspection.")
        if avg_win < 0.50:
            print(f"  Win rate {avg_win*100:.1f}% < 50%: high R:R (3R) required to be")
            print("  profitable. Verify expectancy is positive.")
        elif avg_win < 0.60:
            print(f"  Win rate {avg_win*100:.1f}% below community claim (60-70%).")
            print("  Edge present but weaker than advertised — consistent with")
            print("  academic microstructure literature (Harris, stop-hunt fade).")
        else:
            print(f"  Win rate {avg_win*100:.1f}% within community claim range.")
            print("  Cross-validate with walk-forward before promoting.")

    else:
        print("  No valid results — check data availability.")

    # Save report
    report_path = (
        ROOT
        / "reports"
        / "backtests"
        / f"smc_orderblock_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetail report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
