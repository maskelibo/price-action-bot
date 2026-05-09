"""Morning Star / Evening Star stratejisi icin 3 yillik backtest.

Bulkowski baz: Morning Star Doji variant %74 / Evening Star %73 reversal rate.
Semboller    : 10 USDT paritesi (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT)
Timeframe    : 1d
Sermaye      : $10,000 / sembol (equal-weight)

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_star_backtest.py
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
    """Morning/Evening Star icin tuned manifest.

    Filtreler:
      - kaufman_er_min = 0.15  (hafif chop reject, engulfing'den yumusak)
      - bear_regime_size_factor = 0.5  (200-EMA altinda pozisyon buyuklugu yarim)
      - trend_filter.required = False  (pattern kendi yonunu belirliyor)
      - volume_filter aktif (Bulkowski: Bar2 dusuk hacim, Bar3 artis)
    """
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "morning_evening_star",
        "version": "1.0.0",
        "description": "Morning Star + Evening Star — Bulkowski %72-74 reversal",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "morning_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.0,
                        "use_volume_filter": True,
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
                    },
                },
                {
                    "id": "evening_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.0,
                        "use_volume_filter": True,
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
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
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.15,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "bar2_extreme"},
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
    from price_action.strategies.morning_evening_star import MorningEveningStarStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = MorningEveningStarStrategy(manifest)
    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    # Morning Star ve Evening Star sinyal sayilari
    ms_sigs = [s for s in signals if s.pattern_id == "morning_star"]
    es_sigs = [s for s in signals if s.pattern_id == "evening_star"]

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
        "n_morning_star": len(ms_sigs),
        "n_evening_star": len(es_sigs),
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

    print("=" * 80)
    print("MORNING STAR / EVENING STAR — 3 Yillik Backtest (10 sembol x 1d)")
    print("Bulkowski referans: Morning Star %74 | Evening Star %73 reversal rate")
    print("=" * 80)
    print()
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIG':>4} {'MS':>3} {'ES':>3} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 90)

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_morning_star']:>3} {r['n_evening_star']:>3} "
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

    print()
    print("=" * 80)
    print("PORTFOLIO AGREGATE (equal-weight, 10 sembol, $10K/sembol)")
    print("=" * 80)

    if valid:
        n_trades = sum(r["n_trades"] for r in valid)
        total_ms = sum(r.get("n_morning_star", 0) for r in valid)
        total_es = sum(r.get("n_evening_star", 0) for r in valid)
        avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
        net_pnl = sum(r["net_pnl"] for r in valid)
        starting_equity = 10_000.0 * len(valid)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
        avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
        avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
        # 3-yillik annualize (toplam sermaye uzerinden)
        years = 3.0
        annual = (((1 + total_return) ** (1 / years)) - 1) * 100

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(symbols)}")
        print(f"  Toplam sinyal          : {sum(r['n_signals'] for r in valid)}")
        print(f"    Morning Star sinyali : {total_ms}")
        print(f"    Evening Star sinyali : {total_es}")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        # Performans degerlendirmesi
        print()
        print("--- FAZ 2 ROI GATE (Morning/Evening Star) ---")
        gates = [
            ("Yillik net > %50   ", annual,          50.0,  ">="),
            ("Sharpe > 1.0       ", avg_sharpe,       1.0,  ">="),
            ("MaxDD < %25        ", avg_dd * 100,    25.0,  "<="),
            ("Win rate > %45     ", avg_win * 100,   45.0,  ">="),
        ]
        all_pass = True
        for label, value, target, op in gates:
            ok = (value >= target) if op == ">=" else (value <= target)
            status = "[PASS]" if ok else "[FAIL]"
            all_pass = all_pass and ok
            print(f"  {label}  actual={value:>7.2f}  target={target:>5.1f}  {status}")

        print()
        if all_pass:
            print("  VERDICT: [PASS] — Morning/Evening Star sisteme dahil edilebilir.")
        else:
            n_fail = sum(
                1 for _, val, tgt, op in gates
                if not ((val >= tgt) if op == ">=" else (val <= tgt))
            )
            if n_fail <= 1:
                print("  VERDICT: [MARGINAL] — 1 kriter hatalı; parametre rafine edilebilir.")
            else:
                print(f"  VERDICT: [FAIL] — {n_fail} kriter hatalı; hipotez gözden gecirilmeli.")

        print()
        print("--- ENGULFING BASELINE KARSILASTIRMASI ---")
        print(f"  Metrik              morning_evening_star    engulfing_cont (ref)")
        print(f"  Sharpe              {avg_sharpe:>8.2f}                  ~0.80")
        print(f"  Yillik return       {annual:>8.1f}%               ~+25%")
        print(f"  MaxDD               {avg_dd*100:>8.1f}%                ~18%")
        print(f"  Win rate            {avg_win*100:>8.1f}%                ~55%")
        print(f"  Bulkowski rate      72-74%                       78.5%")

    else:
        print("  Hicbir sembolde trade yok.")

    # Rapor kaydet
    report_path = (
        ROOT
        / "reports"
        / "backtests"
        / f"morning_evening_star_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
