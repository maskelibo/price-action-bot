"""Brooks H2/L2 Two-Legged Pullback — gercek 3y backtest.

10 USDT sembolu * 1d * ~1095 bar.
Brooks'un en guvenilir continuation setup'i.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_h2l2_backtest.py
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


def _make_manifest():
    """H2/L2 icin tuned manifest."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "brooks_h2_l2",
        "version": "1.0.0",
        "description": "Brooks H2/L2 two-legged ABC pullback continuation",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "h2_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "leg_min_bars": 3,
                        "bounce_max_bars": 3,
                        "max_lookback": 25,
                        "sl_atr_buffer": 0.5,
                    },
                },
                {
                    "id": "l2_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "leg_min_bars": 3,
                        "bounce_max_bars": 3,
                        "max_lookback": 25,
                        "sl_atr_buffer": 0.5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 100,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.004,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
                "bear_regime_size_factor": 0.75,
                "trend_n_bars": 10,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "leg_c_extreme", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
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
    from price_action.strategies.brooks_h2_l2 import BrooksH2L2Strategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = BrooksH2L2Strategy(manifest)
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
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": len(signals),
        "n_h2": int(df_feats["h2_signal"].sum()),
        "n_l2": int(df_feats["l2_signal"].sum()),
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


def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    manifest = _make_manifest()
    results: list[dict] = []
    print("=== Brooks H2/L2 Two-Legged Pullback Backtest — 10 sembol x 1d x 3y ===\n")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'H2':>4} {'L2':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 92)

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_h2']:>4} {r['n_l2']:>4} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    # Aggregate
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 80)
    print("PORTFOLIO AGREGATE (equal-weight, naive)")
    print("=" * 80)
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
        total_h2 = sum(r.get("n_h2", 0) for r in valid)
        total_l2 = sum(r.get("n_l2", 0) for r in valid)

        print(f"  Sembol sayisi (gecen)   : {len(valid)}/{len(symbols)}")
        print(f"  Toplam H2 signal       : {total_h2}")
        print(f"  Toplam L2 signal       : {total_l2}")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        print("\n--- FAZ 2 ROI GATE ---")
        gates = [
            ("Yillik net > %70   ", annual, 70.0, ">="),
            ("Sharpe > 1.5       ", avg_sharpe, 1.5, ">="),
            ("MaxDD < %20        ", avg_dd * 100, 20.0, "<="),
        ]
        all_pass = True
        for label, value, target, op in gates:
            ok = (value >= target) if op == ">=" else (value <= target)
            status = "[PASS]" if ok else "[FAIL]"
            all_pass = all_pass and ok
            print(f"  {label} actual={value:>7.2f}  target={target:>5.1f}  {status}")
        print()

        # VERDICT
        print("=" * 80)
        if all_pass:
            verdict = "DEPLOY CANDIDATE"
            print(f"  VERDICT: [{verdict}] — Tum ROI gate'leri gecti.")
        elif avg_win > 0.55 and avg_pf > 1.2:
            verdict = "REFINE"
            print(f"  VERDICT: [{verdict}] — Win rate ve PF umut verici, DD/Sharpe optimize edilmeli.")
        else:
            verdict = "REJECT / RE-HYPOTHESIS"
            print(f"  VERDICT: [{verdict}] — Brooks H2/L2 bu parametreler icin yetersiz.")
        print("=" * 80)

    else:
        print("  Hicbir sembolde trade yok.")
        print(f"\n  VERDICT: [NO TRADES] — Signal uretilemiyor; parametreleri genislet.")

    # Save report
    report_path = (
        ROOT
        / "reports"
        / "backtests"
        / f"brooks_h2l2_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
