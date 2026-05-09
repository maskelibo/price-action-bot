"""HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural HL — Gercek veri backtest.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_spring_vsa_backtest.py

Strateji ozeti:
    Long  : Multi-test HL (60 bar, +-2% tolerans) + Spring bar (VSA stopping vol:
            volume>2x SMA, close ust %40, dar govde) + bullish onay bari
    Short : Multi-test EQH + UTAD bar (VSA stopping vol, alt %40 kapanis) + bearish onay bari
    SL    : Spring low - 0.5*ATR  /  UTAD high + 0.5*ATR
    TP    : 3R

Wyckoff Phase D REJECT farki:
    - Phase D: Spring+SOS zinciri => 2 bekleme event'i => daha gec giris
    - Bu strateji: Phase C Spring'i VSA imzasiyla + HL context tek barda yakaliyor
    - VSA dar govde filtresi => effort>>result absorpsiyon imzasi (Phase D'de yoktu)
    - Multi-test HL => Spring'in "gercek" oldugunu garanti eder (Phase D'de yoktu)
    - Onay bari: 1 bar (Phase D'de SOS = 2+ bar bekleme)
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
    """Spring VSA backtest manifesti."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "wyckoff_spring_vsa",
        "version": "1.0.0",
        "description": "HYP-NEW-1: VSA Spring + Multi-test HL — Phase C giriş",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "spring_vsa_long",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "fractal_n": 5,
                        "hl_lookback": 60,
                        "hl_tolerance_pct": 0.02,
                        "min_swing_lows": 2,
                        "vol_sma_window": 20,
                        "vol_mult": 2.0,
                        "close_pos_min": 0.60,
                        "body_ratio_max": 0.40,
                        "atr_depth_max": 1.0,
                        "sl_atr_buffer": 0.5,
                    },
                },
                {
                    "id": "utad_vsa_short",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "fractal_n": 5,
                        "eqh_lookback": 60,
                        "eqh_tolerance_pct": 0.02,
                        "vol_mult": 2.0,
                        "close_pos_max": 0.40,
                        "body_ratio_max": 0.40,
                        "atr_depth_max": 1.0,
                        "sl_atr_buffer": 0.5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 5},
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
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 80,
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
    # Son 3 yil (1095 bar civarinda)
    cutoff = df["ts"].max() - pd.Timedelta(days=365 * 3 + 10)
    df = df[df["ts"] >= cutoff].reset_index(drop=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = venue
    return df


def _run_one_symbol(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.wyckoff_spring_vsa import WyckoffSpringVSAStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = WyckoffSpringVSAStrategy(manifest)
    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    # Ara istatistikler
    n_hl_ctx = int(df_feats["hl_context"].sum()) if "hl_context" in df_feats.columns else 0
    n_spring = int(df_feats["spring_vsa_flag"].sum()) if "spring_vsa_flag" in df_feats.columns else 0
    n_spring_confirm = int(df_feats["spring_vsa_confirm"].sum()) if "spring_vsa_confirm" in df_feats.columns else 0
    n_utad_confirm = int(df_feats["utad_vsa_confirm"].sum()) if "utad_vsa_confirm" in df_feats.columns else 0

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

    net_pnl = float(result.equity_curve.iloc[-1] - initial_capital) if len(result.equity_curve) > 0 else 0.0
    equity_final = float(result.equity_curve.iloc[-1]) if len(result.equity_curve) > 0 else initial_capital

    return {
        "symbol": symbol,
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_hl_context_bars": n_hl_ctx,
        "n_spring_bars": n_spring,
        "n_spring_confirm": n_spring_confirm,
        "n_utad_confirm": n_utad_confirm,
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
        "net_pnl": net_pnl,
        "equity_final": equity_final,
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
    print("HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural HL")
    print("Backtest: 10 sembol, 1d, 3y gercek veri")
    print("=" * 80)
    print("Strateji: Multi-test HL (60bar, +-2%) + Spring (vol>2x, close>60%, dar govde)")
    print("          + bullish onay bari => LONG @ next open")
    print("Mirror:   Multi-test EQH + UTAD (vol>2x, close<40%, dar govde)")
    print("          + bearish onay bari => SHORT @ next open")
    print("SL: Spring low - 0.5xATR  |  TP: 3R\n")
    print(f"{'Sembol':<12} {'Bars':>4} {'HL':>4} {'Spr':>3} {'Cnf':>3} "
          f"{'Sig':>4} (L/S) {'Trd':>4} {'WR%':>6} {'PF':>5} {'DD%':>5} "
          f"{'Sharpe':>6} {'CAGR%':>6} {'P&L':>9}")
    print("-" * 80)

    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} {r['n_bars']:>4} {r['n_hl_context_bars']:>4} "
                    f"{r['n_spring_bars']:>3} {r['n_spring_confirm']:>3} "
                    f"{r['n_signals']:>4}({r['n_long_signals']}/{r['n_short_signals']}) "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f}% "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f}% "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>6.1f}% "
                    f"{r['net_pnl']:>+9.0f} ({r['elapsed_sec']:.1f}s)"
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
    print("HYP-NEW-1 SPRING VSA — PORTFOLIO AGGREGATE (equal-weight, 10x $10K)")
    print("=" * 80)

    # Funnel istatistikleri
    total_bars = sum(r.get("n_bars", 0) for r in results if "error" not in r)
    total_hl = sum(r.get("n_hl_context_bars", 0) for r in results if "error" not in r)
    total_spring = sum(r.get("n_spring_bars", 0) for r in results if "error" not in r)
    total_confirm = sum(r.get("n_spring_confirm", 0) for r in results if "error" not in r)
    total_utad = sum(r.get("n_utad_confirm", 0) for r in results if "error" not in r)
    total_sigs = sum(r.get("n_signals", 0) for r in results if "error" not in r)
    total_long = sum(r.get("n_long_signals", 0) for r in results if "error" not in r)
    total_short = sum(r.get("n_short_signals", 0) for r in results if "error" not in r)

    print(f"\n  SIGNAL FUNNEL:")
    print(f"  Toplam bar (10 sembol x 3y)  : {total_bars}")
    print(f"  HL context aktif barlar       : {total_hl}  ({total_hl/max(1,total_bars)*100:.1f}% of bars)")
    print(f"  Spring bar (VSA imzali)       : {total_spring}")
    print(f"  Spring confirm (onay bari)    : {total_confirm}  (long sinyal adayi)")
    print(f"  UTAD confirm (short)          : {total_utad}  (short sinyal adayi)")
    print(f"  Toplam giris sinyali          : {total_sigs}  (L={total_long} / S={total_short})")

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
        annual = (((1 + total_return) ** (1 / 3)) - 1) * 100 if total_return > -1 else -100.0

        print(f"\n  PERFORMANCE METRICS:")
        print(f"  Sembol sayisi (trade var)    : {len(valid)}/{len(symbols)}")
        print(f"  Trade siz sembol             : {len(no_trade)}")
        print(f"  Toplam trade                 : {n_trades}")
        print(f"  Trade / sembol / yil         : {n_trades / max(1, len(valid)) / 3:.1f}")
        print(f"  Aggregate win rate           : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L            : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return         : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)          : {annual:+.1f}%")
        print(f"  Avg MaxDD                    : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe                   : {avg_sharpe:.2f}")
        print(f"  Avg CAGR                     : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor            : {avg_pf:.2f}")

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

        # ---------- WYCKOFF PHASE D karsilastirma ----------
        print("\n  WYCKOFF PHASE D (REJECTED) vs HYP-NEW-1 SPRING VSA:")
        print("  +--------------------------+------------------+------------------+")
        print("  | Kriter                   | Phase D (REJECT) | Spring VSA (bu)  |")
        print("  +--------------------------+------------------+------------------+")
        print("  | Giris zamani             | Phase D (gec)    | Phase C (erken)  |")
        print("  | Trigger                  | Spring + SOS     | Spring VSA tek   |")
        print("  | VSA dar govde filtresi   | Yok              | Var (<=0.4 body) |")
        print("  | Multi-test HL context    | Yok              | Var (60 bar)     |")
        print("  | Volume filtresi          | vol_z (relative) | vol>2xSMA(20)    |")
        print("  | Onay bari                | SOS (2+ bar)     | 1 bar bullish    |")
        print("  | Trade frekans            | ~7 toplam (low!) | Bu backtest =>   |")
        print(f"  | Trade/sembol/yil         | ~0.2             | {n_trades / max(1, len(valid)) / 3:>4.1f}            |")
        print("  +--------------------------+------------------+------------------+")

        # ---------- VERDICT ----------
        print("\n" + "=" * 80)
        print("VERDICT — HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural HL")
        print("=" * 80)

        trades_per_sym_yr = n_trades / max(1, len(valid)) / 3.0

        if avg_win >= 0.62 and annual >= 15.0 and avg_pf >= 1.5 and trades_per_sym_yr >= 2.0:
            verdict = "PROMOTE"
            rationale = (
                f"Win rate {avg_win*100:.1f}% >= hedef 62%, "
                f"Yillik {annual:+.1f}% >= 15%, "
                f"PF {avg_pf:.2f} >= 1.5, "
                f"Yeterli frekans ({trades_per_sym_yr:.1f} trade/sembol/yil). "
                "VSA filtresi Wyckoff'u kurtardi."
            )
        elif avg_win >= 0.55 and annual >= 5.0 and trades_per_sym_yr >= 1.5:
            verdict = "DEFER"
            rationale = (
                f"Win rate {avg_win*100:.1f}% (hedef 62%), "
                f"Yillik {annual:+.1f}%, frekans {trades_per_sym_yr:.1f}/y. "
                "Parametreler gevsetilebilir (hl_tolerance_pct, vol_mult). "
                "VSA filtresi kismi deger goruyor."
            )
        elif n_trades < 10:
            verdict = "RARE (like Phase D)"
            rationale = (
                f"Cok az trade: {n_trades} toplam ({trades_per_sym_yr:.1f}/sembol/yil). "
                "VSA + multi-test HL kombinasyonu Phase D kadar nadir. "
                "Filtreler gevsetilebilir veya REJECT."
            )
        else:
            verdict = "REJECT"
            rationale = (
                f"Win rate {avg_win*100:.1f}% (hedef 62%), "
                f"Yillik {annual:+.1f}%, PF {avg_pf:.2f}. "
                "Performans hedeflerin altinda. REJECT."
            )

        print(f"\n  VERDICT: {verdict}")
        print(f"  Gerekcesi: {rationale}")

        print("\n  VSA FILTRESI WYCKOFF'U KURTARDI MI?")
        if trades_per_sym_yr >= 2.0 and avg_win >= 0.55:
            print("  EVET — Trade frekans Phase D'den yuksek VE win rate kabul edilebilir.")
            print("  Multi-test HL + dar govde + onay bari Phase C Spring'i filtredi.")
        elif trades_per_sym_yr < 1.5:
            print("  HAYIR — Hala cok nadir (Phase D'nin 7 trade sorununa benziyor).")
            print("  VSA + HL context katmani aslinda frekans azaltti. Trade adeti yetersiz.")
        else:
            print(f"  KISMEN — Frekans Phase D'den iyi ({trades_per_sym_yr:.1f} vs 0.2/sembol/yil)")
            print("  ama win rate veya return hedef esigine ulasamadi.")

    elif no_trade:
        print(f"\n  Trade siz sembol: {len(no_trade)}")
        for r in no_trade:
            print(
                f"    {r['symbol']}: HL_ctx={r.get('n_hl_context_bars',0)} "
                f"Spring={r.get('n_spring_bars',0)} Confirm={r.get('n_spring_confirm',0)} "
                f"sigs={r.get('n_signals',0)}"
            )
        print("\n  VERDICT: RARE — Sinyal uretildi ama trade baglanamiyor veya hic sinyal yok.")
        print("  VSA filtresi Wyckoff'u 'kurtarmadi' — hala Phase D gibi nadir.")
    else:
        print("  VERDICT: FAIL — Hic gecen sembol yok.")

    # Save report
    report_path = (
        ROOT / "reports" / "backtests"
        / f"spring_vsa_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
