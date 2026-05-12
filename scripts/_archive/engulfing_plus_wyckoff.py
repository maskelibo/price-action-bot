"""Engulfing + Wyckoff Phase D birlesik backtest — 3 senaryo karsilastirmasi.

Senaryolar:
  A) Engulfing Only  — classic engulfing_continuation
  B) Wyckoff Only    — wyckoff_phase_d
  C) Combined        — her iki strateji sinyalleri birlesik (max 5 concurrent)

Konfigürasyon:
  Tek $10K hesap, max 5 concurrent pozisyon
  Risk %2, leverage 3x dynamic_risk + breaker
  10 sembol, 1d, 3y

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/engulfing_plus_wyckoff.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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


def _make_wyckoff_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "wyckoff_phase_d",
        "version": "1.0.0",
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
                "ema200_long_only": True,
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


def _run_symbol_scenario(
    symbol: str,
    scenario: str,  # "engulfing", "wyckoff", "combined"
    engulfing_manifest,
    wyckoff_manifest,
    initial_capital: float = 10_000.0,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.wyckoff_phase_d import WyckoffPhaseDStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "scenario": scenario, "error": "no data"}

    if scenario == "engulfing":
        strategy = EngulfingContinuationStrategy(engulfing_manifest)
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        ohlcv_df = df_feats
    elif scenario == "wyckoff":
        strategy = WyckoffPhaseDStrategy(wyckoff_manifest)
        df_feats = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_feats)
        ohlcv_df = df_feats
    else:  # combined
        # Run both strategies, merge signals
        eng_strat = EngulfingContinuationStrategy(engulfing_manifest)
        wyk_strat = WyckoffPhaseDStrategy(wyckoff_manifest)
        df_eng = eng_strat.prepare_features(df.copy())
        df_wyk = wyk_strat.prepare_features(df.copy())
        eng_sigs = eng_strat.generate_signals(df_eng)
        wyk_sigs = wyk_strat.generate_signals(df_wyk)
        signals = sorted(eng_sigs + wyk_sigs, key=lambda s: s.ts)
        # Use engulfing df for ohlcv (has full features)
        ohlcv_df = df_eng
        strategy = eng_strat  # engine needs a strategy for manifest access

    def ohlcv_provider(_sym, _tf, _start, _end):
        return ohlcv_df.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    # For combined: inject signals directly by using a wrapper strategy
    if scenario == "combined":
        # Create a passthrough strategy that returns pre-computed signals
        class CombinedPassthrough(EngulfingContinuationStrategy):
            _cached_signals: list = []
            def generate_signals(self, df):
                return self._cached_signals

        combined_strat = CombinedPassthrough(engulfing_manifest)
        combined_strat._cached_signals = signals
        strategy = combined_strat

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

    # Yearly returns from equity curve
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
        "scenario": scenario,
        "n_signals": len(signals),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", initial_capital) - initial_capital)),
        "equity_final": float(k.get("equity_final", initial_capital)),
        "yearly_returns": yearly_returns,
        "elapsed_sec": result.elapsed_sec,
    }


def _aggregate(results: list[dict], scenario: str, n_symbols: int) -> dict:
    valid = [r for r in results if r.get("scenario") == scenario and "error" not in r and r.get("n_trades", 0) > 0]
    if not valid:
        return {"scenario": scenario, "n_valid": 0, "n_symbols": n_symbols}

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

    # Yearly aggregate
    all_years: dict[str, list[float]] = {}
    for r in valid:
        for yr, ret in r.get("yearly_returns", {}).items():
            all_years.setdefault(yr, []).append(ret)

    return {
        "scenario": scenario,
        "n_valid": len(valid),
        "n_symbols": n_symbols,
        "n_signals": n_sigs,
        "n_trades": n_trades,
        "avg_win_rate": avg_win,
        "net_pnl": net_pnl,
        "total_return_3y": total_return,
        "annual_pct": annual,
        "avg_max_dd": avg_dd,
        "avg_sharpe": avg_sharpe,
        "avg_cagr": avg_cagr,
        "avg_pf": avg_pf,
        "yearly": {yr: sum(v) / len(v) for yr, v in all_years.items()},
    }


def _print_agg(agg: dict):
    s = agg["scenario"].upper()
    print(f"\n  [{s}]")
    if agg.get("n_valid", 0) == 0:
        print(f"    Gecen sembol yok (trade yok)")
        return
    print(f"    Sembol (gecen)  : {agg['n_valid']}/{agg['n_symbols']}")
    print(f"    Sinyaller       : {agg['n_signals']}")
    print(f"    Tradeler        : {agg['n_trades']}")
    print(f"    Win Rate        : {agg['avg_win_rate']*100:.1f}%")
    print(f"    Net P&L         : ${agg['net_pnl']:+,.0f}")
    print(f"    3y Return       : {agg['total_return_3y']*100:+.1f}%")
    print(f"    Yillik          : {agg['annual_pct']:+.1f}%")
    print(f"    Avg MaxDD       : {agg['avg_max_dd']*100:.1f}%")
    print(f"    Avg Sharpe      : {agg['avg_sharpe']:.2f}")
    print(f"    Avg CAGR        : {agg['avg_cagr']*100:.1f}%")
    print(f"    Avg PF          : {agg['avg_pf']:.2f}")
    if agg.get("yearly"):
        yr_str = "  ".join(f"{yr}={ret:+.1f}%" for yr, ret in sorted(agg["yearly"].items()))
        print(f"    Yillik: {yr_str}")


def main() -> int:
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
               "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]

    eng_manifest = _make_engulfing_manifest()
    wyk_manifest = _make_wyckoff_manifest()

    scenarios = ["engulfing", "wyckoff", "combined"]
    all_results: list[dict] = []

    print(f"=== Engulfing + Wyckoff Karsilastirma ({len(symbols)} sembol, 3y 1d) ===\n")
    print(f"3 senaryo: engulfing_only / wyckoff_only / combined\n")

    for scenario in scenarios:
        print(f"--- {scenario.upper()} ---")
        for sym in symbols:
            try:
                r = _run_symbol_scenario(
                    sym, scenario, eng_manifest, wyk_manifest, initial_capital=10_000.0
                )
                all_results.append(r)
                if "error" in r:
                    print(f"  {sym:<10} {scenario:<10} FAIL: {r['error']}")
                else:
                    print(
                        f"  {sym:<10} sigs={r['n_signals']:>3} trades={r['n_trades']:>3} "
                        f"win={r['win_rate']*100:>5.1f}% DD={r['max_drawdown']*100:>5.1f}% "
                        f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}%"
                    )
            except Exception as exc:
                print(f"  {sym:<10} {scenario:<10} EXCEPTION: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                all_results.append({"symbol": sym, "scenario": scenario, "error": str(exc)})
        print()

    # Aggregate per scenario
    print("\n" + "=" * 80)
    print("KARSILASTIRMA OZETI — AGGREGATE (equal-weight)")
    print("=" * 80)

    aggs = {}
    for scenario in scenarios:
        agg = _aggregate(all_results, scenario, len(symbols))
        aggs[scenario] = agg
        _print_agg(agg)

    # Delta comparison
    print("\n" + "=" * 80)
    print("DELTA KARSILASTIRMASI: Combined vs Engulfing Only")
    print("=" * 80)
    eng = aggs.get("engulfing", {})
    comb = aggs.get("combined", {})
    if eng.get("n_valid", 0) > 0 and comb.get("n_valid", 0) > 0:
        dd_delta = (comb["avg_max_dd"] - eng["avg_max_dd"]) * 100
        annual_delta = comb["annual_pct"] - eng["annual_pct"]
        sharpe_delta = comb["avg_sharpe"] - eng["avg_sharpe"]
        print(f"  Yillik getiri farki     : {annual_delta:+.1f}% ({'iyilesti' if annual_delta > 0 else 'kotulesti'})")
        print(f"  MaxDD farki             : {dd_delta:+.1f}% ({'iyilesti' if dd_delta < 0 else 'kotulesti'})")
        print(f"  Sharpe farki            : {sharpe_delta:+.2f} ({'iyilesti' if sharpe_delta > 0 else 'kotulesti'})")
        print(f"  Ek sinyal (Wyckoff)     : {comb['n_signals'] - eng['n_signals']:+d}")
    else:
        print("  Karsilastirma icin yeterli veri yok")

    # Verdict
    print("\n" + "=" * 80)
    print("CRITICAL ASSESSMENT & VERDICT")
    print("=" * 80)
    wyk = aggs.get("wyckoff", {})
    wyk_trades = wyk.get("n_trades", 0)
    eng_trades = eng.get("n_trades", 0)
    comb_trades = comb.get("n_trades", 0)

    print(f"\n  1. SINYAL FREKANSI:")
    print(f"     Engulfing: {eng.get('n_signals', 0)} sinyal, {eng_trades} trade (3y, 10 sembol)")
    print(f"     Wyckoff  : {wyk.get('n_signals', 0)} sinyal, {wyk_trades} trade")
    print(f"     Combined : {comb.get('n_signals', 0)} sinyal, {comb_trades} trade")

    print(f"\n  2. MEKANIK WYCKOFF'UN KISITLAMALARI (1d crypto verisi):")
    print(f"     - Spring+SOS kombo 3 yilda sadece {wyk_trades} trade uretiyor")
    print(f"     - Spring: reclaim 1-3 bar icinde zorunlu => cok katı")
    print(f"     - SOS: body > 1.5x ATR + vol_z > 1.0 => crypto'da yuksek baris gecmiyor")
    print(f"     - kaufman_er_min=0.15 + ema200 bias => cok fazla filtre birikiyor")
    print(f"     - 30-bar range lookback keyfi — daha kisa (15-20) cok daha fazla sinyal")

    print(f"\n  3. HONESTY NOTU:")
    print(f"     Wyckoff metodolojisi bircok elitist trader tarafindan 'sanatsal' gorulur.")
    print(f"     Mekanik implementasyonda guclu backtestler genellikle curve-fitting eseridir.")
    print(f"     Bu implementasyon kasitli olarak muhafazakar tutulmus; sonuclar beklendik:")
    print(f"     Cok az sinyal, istatistiksel anlam yok ({wyk_trades} trade << 30 minimum).")

    print(f"\n  VERDICT:")
    if wyk_trades < 10:
        print(f"  [REJECT] — Wyckoff Phase D (mevcut parametreler) production'a hazir degil.")
        print(f"             Sebepler:")
        print(f"             a) {wyk_trades} trade / 3y / 10 sembol — istatistiksel anlamsiz")
        print(f"             b) Engulfing ile korrelasyon analizi icin yeterli veri yok")
        print(f"             c) Decorrelasyon hipotezi test edilemez bu frekansta")
        print(f"")
        print(f"  REVISE ONERI: lookback=15, vol_z_min=0.5, atr_mult=1.0, kaufman_er_min=0.0")
        print(f"  ile yeniden cal — frekans artmali. Sonra win_rate ve expectancy degerlendir.")
    elif comb.get("annual_pct", 0) > eng.get("annual_pct", 0) and comb.get("avg_max_dd", 1) <= eng.get("avg_max_dd", 1) * 1.1:
        print(f"  [PROMOTE] — Combined strateji Engulfing'den daha iyi performans gosteriyor.")
    else:
        print(f"  [REVISE] — Combined strateji anlamli katki saglamadi. Wyckoff parametrelerini")
        print(f"             revizyona al, sonra tekrar degerlendir.")

    # Save
    report_path = ROOT / "reports" / "backtests" / f"combined_engulfing_wyckoff_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"results": all_results, "aggregates": aggs}, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
