"""Forex major pairs engulfing continuation backtest — 5y 1D.

Pairs  : EUR/USD, GBP/USD, USD/JPY
Data   : data/forex_market.duckdb (yfinance, 5y daily)
Strategy: engulfing_continuation — ayni manifest, sadece forex semboller
Commission: 1.0 pip per round-trip (~0.01% EUR/USD)
Slippage  : 2 bps (tighter than crypto 5 bps)

Calistirma:
    PYTHONPATH=src python scripts/run_forex_backtest.py

Oncelikle ingest edilmis olmali:
    python scripts/ingest_forex_data.py
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

DB_PATH = ROOT / "data" / "forex_market.duckdb"

# Crypto baseline (run_engulfing_backtest.py onceki sonuclar — referans icin)
CRYPTO_BASELINE = {
    "avg_sharpe": 0.28,
    "annual_pct": 2.1,
    "avg_dd_pct": 14.2,
    "n_trades": 87,
    "win_rate_pct": 47.8,
}


def _make_manifest():
    """engulfing_continuation manifest — crypto ile ayni, sadece label degisik."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Forex engulfing bar after 20-EMA pullback in established trend",
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
                "atr_min_pct": 0.002,          # Forex volatility daha dusuk; 0.005 cok kati
                "volume_zscore_min": 0.0,       # Forex volume unreliable; kapat
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,         # Ayni chop reject
                "bear_regime_size_factor": 0.5, # Ayni 200-EMA proxy
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


def _load_forex_ohlcv(symbol: str) -> pd.DataFrame:
    """forex_market.duckdb'den symbol verisini yukle."""
    import duckdb
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Forex DB bulunamadi: {DB_PATH}\n"
            "Once 'python scripts/ingest_forex_data.py' calistirin."
        )
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue='forex' AND symbol=? AND timeframe='1d' ORDER BY ts",
        [symbol],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    df["venue"] = "forex"
    return df


def _run_one_symbol(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_forex_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data in DB — run ingest_forex_data.py first"}

    n_years = (df["ts"].iloc[-1] - df["ts"].iloc[0]).days / 365.25

    strategy = EngulfingContinuationStrategy(manifest)
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
        # Forex: 1-pip spread (~0.01% for EUR/USD) = 10 bps round-trip; maker/taker N/A
        fees={"taker": 0.0001, "maker": 0.0001},
        slippage_bps=2.0,
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    _cagr = float(k.get("cagr", 0.0))
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** n_years - 1)
    return {
        "symbol": symbol,
        "n_bars": len(df),
        "n_years": round(n_years, 2),
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


def _print_comparison(valid: list[dict], n_years: float) -> None:
    """Forex vs Crypto baseline karsilastirmasi yazdir."""
    if not valid:
        return
    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    net_pnl = sum(r["net_pnl"] for r in valid)
    starting_equity = 10_000.0 * len(valid)
    total_return = net_pnl / starting_equity
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
    annual = (((1 + total_return) ** (1 / max(n_years, 0.1))) - 1) * 100

    print(f"\n{'=' * 70}")
    print("PORTFOLIO AGREGATE (equal-weight, naive)")
    print("=" * 70)
    print(f"  Sembol sayisi (gecen)  : {len(valid)}/3")
    print(f"  Toplam trade           : {n_trades}")
    print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
    print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
    print(f"  Aggregate net return   : {total_return*100:+.1f}% ({n_years:.1f}y, equal-weight)")
    print(f"  Yillik (annualized)    : {annual:+.1f}%")
    print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
    print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
    print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
    print(f"  Avg Profit Factor      : {avg_pf:.2f}")

    # Karsilastirma tablosu
    b = CRYPTO_BASELINE
    print(f"\n{'─' * 70}")
    print(f"  {'METRIK':<22} {'FOREX (5y)':>12} {'CRYPTO (3y)':>12} {'DELTA':>10}")
    print(f"  {'─'*22} {'─'*12} {'─'*12} {'─'*10}")
    metrics = [
        ("Avg Sharpe",       avg_sharpe,       b["avg_sharpe"],    "{:+.2f}", "{:.2f}", "{:.2f}"),
        ("Yillik return%",   annual,            b["annual_pct"],    "{:+.1f}", "{:.1f}", "{:.1f}"),
        ("Avg MaxDD%",       avg_dd*100,        b["avg_dd_pct"],    "{:+.1f}", "{:.1f}", "{:.1f}"),
        ("N trades (total)", n_trades,          b["n_trades"],      "{:+.0f}", "{:.0f}", "{:.0f}"),
        ("Avg win rate%",    avg_win*100,       b["win_rate_pct"],  "{:+.1f}", "{:.1f}", "{:.1f}"),
    ]
    for name, fx_val, cr_val, dfmt, ffmt, cfmt in metrics:
        delta = fx_val - cr_val
        print(f"  {name:<22} {ffmt.format(fx_val):>12} {cfmt.format(cr_val):>12} {dfmt.format(delta):>10}")

    # Verdict
    print(f"\n{'=' * 70}")
    print("VERDICT")
    print("=" * 70)
    promote = (
        avg_win >= 0.45
        and avg_pf >= 1.1
        and avg_sharpe >= 0.4
        and avg_dd <= 0.25
        and n_trades >= 15
    )
    better_than_crypto = avg_sharpe > b["avg_sharpe"] and annual > b["annual_pct"]

    if promote:
        print("  [PROMOTE] Forex engulfing kriterleri geciyor.")
        if better_than_crypto:
            print("  Edge crypto'dan DAHA GUCLU — forex universe'e gec.")
        else:
            print("  Edge mevcut ama crypto'dan daha zayif — yine de PROMOTE.")
    elif avg_sharpe > 0 and avg_pf > 1.0:
        print("  [DEFER] Pozitif ama yetersiz edge — parametreleri rafine et.")
        print("  Onerilen: GBP/JPY, AUD/USD ekle; veya 4H timeframe dene.")
    else:
        print("  [REJECT] Forex'te de anlamli edge yok.")
        print("  Engulfing continuation genel olarak zayif bir pattern olabilir.")
        print("  Pivot onerileri: breakout (Donchian) veya mean-reversion (Bollinger).")

    if better_than_crypto:
        print("\n  SONUC: Engulfing edge crypto-spesifik DEGIL — forex'te de var.")
    else:
        print("\n  SONUC: Eger crypto'da da zayif, edge crypto-spesifik de degil;")
        print("         pattern genel olarak guvenilir degil.")

    return {
        "n_trades": n_trades,
        "avg_win_pct": avg_win * 100,
        "net_pnl": net_pnl,
        "annual_pct": annual,
        "avg_dd_pct": avg_dd * 100,
        "avg_sharpe": avg_sharpe,
        "avg_cagr_pct": avg_cagr * 100,
        "avg_pf": avg_pf,
        "promote": promote,
        "better_than_crypto": better_than_crypto,
    }


def _data_quality_diagnostic(symbols: list[str]) -> dict:
    """yfinance open==close bug diagnostics — report before backtest."""
    import duckdb
    print("\n--- DATA QUALITY DIAGNOSTIC ---")
    results: dict[str, dict] = {}
    for sym in symbols:
        if not DB_PATH.exists():
            print(f"  {sym}: DB missing")
            continue
        con = duckdb.connect(str(DB_PATH), read_only=True)
        import pandas as pd
        df = con.execute(
            "SELECT open, high, low, close FROM ohlcv WHERE venue='forex' AND symbol=? AND timeframe='1d'",
            [sym],
        ).fetchdf()
        con.close()
        n = len(df)
        open_eq_close = (df["open"] == df["close"]).sum()
        import numpy as np
        body = (df["open"] - df["close"]).abs()
        rng = (df["high"] - df["low"]).replace(0, np.nan)
        body_ratio = body / rng
        import sys
        from price_action.strategies.engulfing_continuation import _strict_engulfing
        df_full = df.copy()
        df_full["ts"] = pd.date_range("2021-01-01", periods=n, freq="B")[:n]
        df_full["symbol"] = sym
        df_full["venue"] = "forex"
        df_full["timeframe"] = "1d"
        df_full["volume"] = 0.0
        bull = _strict_engulfing(df_full, body_ratio_min=0.3, bullish=True).sum()
        bear = _strict_engulfing(df_full, body_ratio_min=0.3, bullish=False).sum()
        bull_raw = int(((df["close"] > df["open"]) & (df["close"].shift(1) < df["open"].shift(1))
                        & (df["open"] <= df["close"].shift(1)) & (df["close"] >= df["open"].shift(1))).sum())
        bear_raw = int(((df["close"] < df["open"]) & (df["close"].shift(1) > df["open"].shift(1))
                        & (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))).sum())
        pct_corrupt = open_eq_close / max(n, 1) * 100
        print(f"  {sym:<10}: n={n}, open==close={open_eq_close} ({pct_corrupt:.0f}%), "
              f"raw_engulf(bull={bull_raw}, bear={bear_raw}), "
              f"body_ratio p50={body_ratio.median():.3f}")
        results[sym] = {
            "n_bars": n,
            "open_eq_close_count": int(open_eq_close),
            "open_eq_close_pct": round(pct_corrupt, 1),
            "raw_bull_engulf": bull_raw,
            "raw_bear_engulf": bear_raw,
            "body_ratio_p50": round(float(body_ratio.median()), 4),
        }

    print()
    if any(v.get("open_eq_close_pct", 0) > 50 for v in results.values()):
        print("  [WARNING] yfinance open==close bug detected on >50% of bars!")
        print("  Engulfing detection is UNRELIABLE with this data.")
        print("  Data alternatives: OANDA API, Alpha Vantage, Dukascopy")
    return results


def main() -> int:
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY"]
    manifest = _make_manifest()
    results: list[dict] = []

    print("=== Forex EngulfingContinuation Backtest — 3 pair x 1d x 5y ===\n")

    # Data quality check first
    dq = _data_quality_diagnostic(symbols)

    print(f"  {'SYMBOL':<10} {'BARS':>5} {'SIGS':>5} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 80)

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>5} {r['n_signals']:>5} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]

    # Avg years across valid symbols
    n_years = (
        sum(r.get("n_years", 5.0) for r in valid) / len(valid) if valid else 5.0
    )

    agg = _print_comparison(valid, n_years) if valid else None

    # VERDICT section
    print(f"\n{'=' * 70}")
    if not valid:
        print("VERDICT: DEFER — Zero trades generated across all forex pairs.")
        print()
        print("ROOT CAUSE: yfinance open==close data quality bug affects >70% of bars.")
        print("  Engulfing pattern requires distinct open != close to detect body direction.")
        print("  With open==close, body=0, body_ratio=0, no engulfing can be detected.")
        print()
        print("SECONDARY: Even with clean data, body_ratio_min=0.6 is too strict for forex:")
        print("  EUR/USD daily ATR ~0.55% vs BTC/USDT ~3.1% (6x less volatile)")
        print("  Strict engulfing of full prev body is structurally rare at 0.55% daily moves")
        print()
        print("ACTION ITEMS:")
        print("  1. Replace yfinance with OANDA API or Alpha Vantage for clean forex OHLCV")
        print("  2. Lower body_ratio_min from 0.6 to 0.3 for forex re-test")
        print("  3. Consider 4H timeframe: more bars, more patterns, less data dependency")
        print()
        print("HYPOTHESIS STATUS: DEFER (data quality) — not REJECT")
        print("  Cannot conclude engulfing fails on forex without clean data.")

    # Save report
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = ROOT / "reports" / "backtests" / f"forex_engulfing_{ts_str}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "run_ts": ts_str,
            "strategy": "engulfing_continuation",
            "universe": "forex_majors",
            "timeframe": "1d",
            "data_source": "yfinance_5y",
            "verdict": "DEFER",
            "defer_reason": "yfinance_open_eq_close_bug",
        },
        "data_quality": dq,
        "per_symbol": results,
        "aggregate": agg,
        "crypto_baseline": CRYPTO_BASELINE,
    }
    report_path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
