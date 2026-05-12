"""Wyckoff Phase D stratejisi — 3y gercek veri backtest.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_wyckoff_backtest.py

Faz D hedefleri:
    - Wyckoff standalone performansi degerlendirme
    - 10 sembol, 1d, 3y
    - Per-sembol + aggregate cikti
    - Equity curve ozeti
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
    """Wyckoff Phase D backtest manifesti."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "wyckoff_phase_d",
        "version": "1.0.0",
        "description": "Wyckoff Phase D — Spring+SOS long / UTAD+SOW short",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "wyckoff_long_sos",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 30,
                        "atr_mult": 1.5,
                        "vol_z_min": 1.0,
                        "lookback_spring": 5,
                    },
                },
                {
                    "id": "wyckoff_short_sow",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 30,
                        "atr_mult": 1.5,
                        "vol_z_min": 1.0,
                        "lookback_utad": 5,
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
                "kaufman_er_min": 0.15,
                "ema200_long_only": True,  # 200-EMA uzun bias
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural"},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
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
    from price_action.strategies.wyckoff_phase_d import WyckoffPhaseDStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = WyckoffPhaseDStrategy(manifest)
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

    # Equity curve yearly breakdown
    eq = result.equity_curve
    yearly_returns = {}
    if len(eq) > 0:
        for yr in range(eq.index.min().year, eq.index.max().year + 1):
            yr_eq = eq[eq.index.year == yr]
            if len(yr_eq) >= 2:
                ret = (yr_eq.iloc[-1] / yr_eq.iloc[0]) - 1.0
                yearly_returns[str(yr)] = round(float(ret) * 100, 2)

    return {
        "symbol": symbol,
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": len(signals),
        "n_long_signals": sum(1 for s in signals if s.direction == "long"),
        "n_short_signals": sum(1 for s in signals if s.direction == "short"),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy": float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", initial_capital) - initial_capital)),
        "equity_final": float(k.get("equity_final", initial_capital)),
        "yearly_returns": yearly_returns,
        "elapsed_sec": result.elapsed_sec,
    }


def main() -> int:
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
               "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]
    manifest = _make_manifest()
    results: list[dict] = []
    print(f"=== Wyckoff Phase D Backtest ({len(symbols)} sembol, 3y 1d) ===\n")
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} bars={r['n_bars']:>4} sigs={r['n_signals']:>3} "
                    f"(L={r['n_long_signals']}/S={r['n_short_signals']}) "
                    f"trades={r['n_trades']:>3} win={r['win_rate']*100:>5.1f}% "
                    f"PF={r['profit_factor']:>5.2f} DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f} ({r['elapsed_sec']:.1f}s)"
                )
                if r.get("yearly_returns"):
                    yr_str = "  ".join(f"{yr}={ret:+.1f}%" for yr, ret in sorted(r["yearly_returns"].items()))
                    print(f"    Yillik: {yr_str}")
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    # Aggregate
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 80)
    print("WYCKOFF PHASE D — PORTFOLIO AGGREGATE (equal-weight, 10x $10K)")
    print("=" * 80)
    if valid:
        n_trades = sum(r["n_trades"] for r in valid)
        n_sigs = sum(r["n_signals"] for r in valid)
        avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
        net_pnl = sum(r["net_pnl"] for r in valid)
        starting_equity = 10_000.0 * len(valid)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
        avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
        avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
        annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(symbols)}")
        print(f"  Toplam sinyal          : {n_sigs}")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        # Yearly aggregate
        all_years: dict[str, list[float]] = {}
        for r in valid:
            for yr, ret in r.get("yearly_returns", {}).items():
                all_years.setdefault(yr, []).append(ret)
        if all_years:
            print("\n  Yillik Getiri Dagilimi (sembol ortalamasi):")
            for yr in sorted(all_years):
                rets = all_years[yr]
                avg_ret = sum(rets) / len(rets)
                print(f"    {yr}: {avg_ret:+.1f}%  (n={len(rets)} sembol)")

    elif len([r for r in results if "error" not in r]) > 0:
        no_trade = [r for r in results if "error" not in r and r.get("n_trades", 0) == 0]
        print(f"  Sinyal uretildi ama trade yok: {len(no_trade)} sembol")
        for r in no_trade:
            print(f"    {r['symbol']}: n_signals={r.get('n_signals', 0)}")
    else:
        print("  Hic gecen sembol yok — veri eksik olabilir.")

    print("\n--- CRITICAL ASSESSMENT ---")
    print("  Wyckoff Spring+SOS mekanik implementasyonunun 1d crypto verisi icin")
    print("  olasi zayifliklari:")
    print("  1. Spring/SOS crypto'da cok sik 'false positive' uretir (yuksek volatilite)")
    print("  2. Range tespiti (30-bar) parametreye cok hassas — yari-keyfi")
    print("  3. ATR body kriteri (1.5x) hizli piyasalarda kolayca asiliyor")
    print("  4. Vol z-score threshold (1.0) wash trading ile yaniltilabilir")
    print("  5. 200-EMA bias filtresi trade sayisini buyuk olcude kisitiyor")
    print("  Sonuc: Standalone Wyckoff Phase D, 1d crypto'da dusuk frekans +")
    print("  yuksek varyans gosterir. Engulfing ile birlesim daha anlamli.")

    # Save
    report_path = ROOT / "reports" / "backtests" / f"wyckoff_phase_d_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
