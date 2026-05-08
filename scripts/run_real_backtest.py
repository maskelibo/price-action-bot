"""Gercek 3y veriyle classic_pa backtest — Faz 2 ROI gate testi.

Loadlanan veriler: DuckDB (data/market.duckdb) — 10 sembol (BTC/ETH/SOL/BNB/
XRP/DOGE/ADA/AVAX/LINK/DOT) * 1d * ~1095 bar.

Her sembol icin classic_pa stratejisi calistirilir, sonuclar agregat edilir.

Faz 2 hedefleri:
- Yillik net > %70
- Sharpe > 1.5
- MaxDD < %20
- Walk-forward dilim oranı > %66 (bu ilk bakista kontrol edilmiyor; o sonraki adim)

Calistirma:
    PYTHONPATH=src python scripts/run_real_backtest.py
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
    """classic_pa.yaml'a yakin manifest — 1D crypto icin tuned."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "classic_pa_real",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_pin_bar", "enabled": True, "weight": 1.5, "params": {
                    "body_to_range_max": 0.33,
                    "lower_wick_to_range_min": 0.6,
                    "upper_wick_to_range_max": 0.15,
                }},
                {"id": "bearish_pin_bar", "enabled": True, "weight": 1.5, "params": {
                    "body_to_range_max": 0.33,
                    "upper_wick_to_range_min": 0.6,
                    "lower_wick_to_range_max": 0.15,
                }},
                {"id": "bullish_engulfing", "enabled": True, "weight": 1.5, "params": {
                    "prev_body_min_range_pct": 0.15,
                }},
                {"id": "bearish_engulfing", "enabled": True, "weight": 1.5, "params": {
                    "prev_body_min_range_pct": 0.15,
                }},
                {"id": "inside_bar_breakout", "enabled": True, "weight": 0.8, "params": {
                    "confirm_with_close": True,
                }},
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
                # Aşama B forward-looking filters (sensitivity sweep best config)
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,                  # chop reject (sweet spot 0.20)
                # always_in_required: kapalı — agresif, n drastik düşürüyor
                # rolling_sharpe_min: kapalı — anlamlı uplift sağlamadı
                "bear_regime_size_factor": 0.5,          # 200-EMA altında long reject
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
                # max_score: kapalı — confluence cap tek başına marginal
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
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


def _run_one_symbol(symbol: str, manifest: dict, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.classic_pa import ClassicPriceActionStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = ClassicPriceActionStrategy(manifest)
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
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
               "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]
    manifest = _make_manifest()
    results: list[dict] = []
    print(f"=== Faz 2 ROI Gate Backtest — classic_pa ({len(symbols)} sembol, 3y 1d) ===\n")
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

    # Aggregate (equal-weight)
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 75)
    print("PORTFOLIO AGREGATE (equal-weight, naive)")
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

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(symbols)}")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {(((1+total_return)**(1/3)) - 1)*100:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        print("\n--- FAZ 2 ROI GATE KARSILASTIRMASI ---")
        annual = (((1+total_return)**(1/3)) - 1)*100
        gates = [
            ("Yillik net > %70   ", annual, 70.0, ">="),
            ("Sharpe > 1.5       ", avg_sharpe, 1.5, ">="),
            ("MaxDD < %20        ", avg_dd*100, 20.0, "<="),
        ]
        all_pass = True
        for label, value, target, op in gates:
            ok = (value >= target) if op == ">=" else (value <= target)
            status = "[PASS]" if ok else "[FAIL]"
            all_pass = all_pass and ok
            print(f"  {label} actual={value:>7.2f}  target={target:>5.1f}  {status}")
        print()
        if all_pass:
            print("  ROI GATE: [PASS] — Faz 3 risk katmanina gec.")
        else:
            print("  ROI GATE: [FAIL] — Researcher hipotez rafinasyonuna don.")

    # Save report
    report_path = ROOT / "reports" / "backtests" / f"classic_pa_real_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
