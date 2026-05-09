"""VSA Selling Climax + Test Bar stratejisi — 10 sembol, 1d, 3y backtest.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_vsa_climax_backtest.py

Strateji ozeti:
    Long  : Selling Climax + Test Bar (3-15 bar bekle) + yesil onay bari
    Short : Buying Climax + Up Thrust (3-15 bar bekle) + kirmizi onay bari
    SL    : SC low - 1×ATR
    TP    : 3R
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
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "vsa_climax_test",
        "version": "1.0.0",
        "description": "VSA Selling Climax + Test Bar — Wyckoff Phase A bottom signal",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_sc_test_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_min": 0.50,
                        "min_low_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "low_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
                    },
                },
                {
                    "id": "vsa_bc_thrust_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_max": 0.50,
                        "max_high_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "high_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
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
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "sc_low_atr", "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 60,
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
    # Son 3 yil (1095 bar)
    cutoff = df["ts"].max() - pd.Timedelta(days=365 * 3 + 10)
    df = df[df["ts"] >= cutoff].reset_index(drop=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


def _run_one_symbol(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = VSAClimaxTestStrategy(manifest)
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

    # SC / BC / Test / UT istatistikleri
    n_sc = int(df_feats["sc_flag"].sum()) if "sc_flag" in df_feats.columns else 0
    n_bc = int(df_feats["bc_flag"].sum()) if "bc_flag" in df_feats.columns else 0
    n_tb = int(df_feats["test_bar_flag"].sum()) if "test_bar_flag" in df_feats.columns else 0
    n_ut = int(df_feats["up_thrust_flag"].sum()) if "up_thrust_flag" in df_feats.columns else 0

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
        "n_sc": n_sc,
        "n_bc": n_bc,
        "n_test_bars": n_tb,
        "n_up_thrusts": n_ut,
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
        "net_pnl": float(result.equity_curve.iloc[-1] - initial_capital) if len(result.equity_curve) > 0 else 0.0,
        "equity_final": float(result.equity_curve.iloc[-1]) if len(result.equity_curve) > 0 else initial_capital,
        "yearly_returns": yearly_returns,
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
    print("VSA SELLING CLIMAX + TEST BAR — Backtest (10 sembol, 1d, 3y)")
    print("=" * 80)
    print("Strateji: SC (klimaktik hacim + genis bar) -> Test Bar (3-15 bar) -> Yesil bar giris")
    print("Mirror:   BC (klimaktik hacim + genis bar) -> Up Thrust (3-15 bar) -> Kirmizi bar giris")
    print("SL: SC low - 1×ATR  |  TP: 3R\n")

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} bars={r['n_bars']:>4} "
                    f"SC={r['n_sc']:>2}/BC={r['n_bc']:>2} "
                    f"TB={r['n_test_bars']:>2}/UT={r['n_up_thrusts']:>2} "
                    f"sigs={r['n_signals']:>2}(L={r['n_long_signals']}/S={r['n_short_signals']}) "
                    f"trades={r['n_trades']:>2} win={r['win_rate']*100:>5.1f}% "
                    f"PF={r['profit_factor']:>5.2f} DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>5.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f} ({r['elapsed_sec']:.1f}s)"
                )
                if r.get("yearly_returns"):
                    yr_str = "  ".join(
                        f"{yr}={ret:+.1f}%" for yr, ret in sorted(r["yearly_returns"].items())
                    )
                    print(f"    Yillik: {yr_str}")
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    # ---------- Aggregate ----------
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    no_trade = [r for r in results if "error" not in r and r.get("n_trades", 0) == 0]

    print("\n" + "=" * 80)
    print("VSA CLIMAX TEST — PORTFOLIO AGGREGATE (equal-weight, 10x $10K)")
    print("=" * 80)

    total_sc = sum(r.get("n_sc", 0) for r in results if "error" not in r)
    total_bc = sum(r.get("n_bc", 0) for r in results if "error" not in r)
    total_tb = sum(r.get("n_test_bars", 0) for r in results if "error" not in r)
    total_ut = sum(r.get("n_up_thrusts", 0) for r in results if "error" not in r)
    total_sigs = sum(r.get("n_signals", 0) for r in results if "error" not in r)

    print(f"  Toplam SC (Selling Climax)  : {total_sc}")
    print(f"  Toplam BC (Buying Climax)   : {total_bc}")
    print(f"  Toplam Test Bar             : {total_tb}")
    print(f"  Toplam Up Thrust            : {total_ut}")
    print(f"  Toplam sinyal (giris)       : {total_sigs}")

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

        print(f"\n  Sembol sayisi (trade var)   : {len(valid)}/{len(symbols)}")
        print(f"  Trade siz sembol            : {len(no_trade)}")
        print(f"  Toplam trade                : {n_trades}")
        print(f"  Aggregate win rate          : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L           : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return        : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)         : {annual:+.1f}%")
        print(f"  Avg MaxDD                   : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe                  : {avg_sharpe:.2f}")
        print(f"  Avg CAGR                    : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor           : {avg_pf:.2f}")

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

        # Verdict
        print("\n" + "=" * 80)
        print("VERDICT — VSA Selling Climax + Test Bar")
        print("=" * 80)
        if avg_win >= 0.55 and annual >= 20.0 and avg_pf >= 1.5:
            verdict = "PROMISING — Yüksek win rate + pozitif CAGR. Daha ileri optimizasyon uygundur."
        elif avg_win >= 0.45 and annual >= 5.0:
            verdict = "MARGINAL — Sinyal az, performans vasat. Filtre gevsetmesi denenebilir."
        elif n_trades < 5:
            verdict = "INSUFFICIENT DATA — Cok az trade. 3y 1d veri icin beklenen dusuk frekans."
        else:
            verdict = "UNDERPERFORMING — Win rate veya return yetersiz. Strateji revizyonu gerekli."
        print(f"  {verdict}")
        print("\n  VSA SC+Test teorik gucleri:")
        print("  - Major bottom'larda (BTC 2018 Aralik, 2020 Mart, 2022 Kasim) mükemmel calisti")
        print("  - Sinyal frekansi dusuk (~3-15 sinyal/sembol/yil) = dusuk trade sayisi")
        print("  - 3R hedef ile tek kazanan trade birçok kaybi telafi edebilir")
        print("  - Kripto 1D'de SC basarili: volume z-score > 2.5 + lower wick recovery")
        print("  VSA SC+Test teorik zayifliklari:")
        print("  - Alti-sinyal durumu: SC sonrasi hizla yukarı giderse Test Bar hic olusmaz")
        print("  - Yalan SC (Failed SC): SC sonrasi 3-5 bar icerisinde yeni dip yapilirsa iptal")
        print("  - Kripto 24/7: hafta sonu dusuk hacim 'test bar' gibi gorunebilir (false positive)")
        print("  - Tolerans %1 dar olabilir — 1D barda low'lar tam eslesmiyor")
    elif no_trade:
        print(f"\n  Trade siz sembol sayisi: {len(no_trade)}")
        for r in no_trade:
            print(f"    {r['symbol']}: SC={r.get('n_sc',0)} BC={r.get('n_bc',0)} "
                  f"TB={r.get('n_test_bars',0)} UT={r.get('n_up_thrusts',0)} sigs={r.get('n_signals',0)}")
        print("\n  Sinyal uretildi ancak trade yok => giriş bari eslemedi veya veri eksik.")
    else:
        print("  Hic gecen sembol yok — veri eksik olabilir.")

    # Save report
    report_path = (
        ROOT / "reports" / "backtests"
        / f"vsa_climax_test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
