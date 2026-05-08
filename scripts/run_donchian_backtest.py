"""Donchian Breakout + Bollinger Squeeze backtest — H-005 hipotez doğrulaması.

Hipotez: H-005 (2026-05-08-donchian-bollinger-breakout.md)
Strateji: DonchianBreakoutStrategy
Veri    : DuckDB (data/market.duckdb) — 10 sembol × 1D × 3y
Kapital : 10.000 USDT × sembol (standalone)
Komisyon: taker 0.075%, maker -0.010%
Slippage: 5 bps

Raporlar:
  1. Per-symbol detay
  2. Standalone aggregate (10 sembol, equal-weight)
  3. Engulfing_continuation ile karşılaştırma
  4. Sinyal korelasyon analizi (decorrelation testi)
  5. H-005 gate değerlendirmesi

Çalıştırma:
    PYTHONPATH=src python scripts/run_donchian_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Manifest fabrikaları
# =====================================================================

def _make_donchian_manifest():
    """H-005 için DonchianBreakoutStrategy manifesti."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "donchian_breakout",
        "version": "1.0.0",
        "trend_filter": {"type": "donchian", "period": 55, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "donchian_long_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": 55,
                        "donchian_exit_period": 20,
                        "squeeze_lookback": 5,
                    },
                },
                {
                    "id": "donchian_short_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": 55,
                        "donchian_exit_period": 20,
                        "squeeze_lookback": 5,
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
                "kaufman_er_min": 0.30,
                "bb_period": 20,
                "bb_std": 2.0,
                "kc_period": 20,
                "kc_atr_mult": 1.5,
                "squeeze_lookback_bars": 5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "donchian20", "exit_period": 20},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_engulfing_manifest():
    """Karşılaştırma için engulfing_continuation manifesti (run_real_backtest.py'den)."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
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


# =====================================================================
# Veri yükleme
# =====================================================================

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


# =====================================================================
# Tek sembol backtest
# =====================================================================

def _run_one_symbol_donchian(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    """DonchianBreakoutStrategy ile tek sembol backtest."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = DonchianBreakoutStrategy(manifest)
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
    # Sinyal zaman damgalarını da kaydet (korelasyon analizi için)
    signal_ts = [s.ts for s in signals]
    signal_dirs = [s.direction for s in signals]
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
        "_signal_ts": [str(t) for t in signal_ts],
        "_signal_dirs": signal_dirs,
    }


def _run_one_symbol_engulfing(symbol: str, manifest, initial_capital: float = 10_000.0) -> dict:
    """EngulfingContinuationStrategy ile tek sembol backtest."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

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
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    k = result.kpis
    signal_ts = [s.ts for s in signals]
    return {
        "symbol": symbol,
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", initial_capital) - initial_capital)),
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
        "_signal_ts": [str(t) for t in signal_ts],
    }


# =====================================================================
# Korelasyon analizi
# =====================================================================

def _compute_signal_correlation(
    don_results: list[dict],
    eng_results: list[dict],
    symbols: list[str],
) -> float:
    """İki strateji sinyallerinin günlük çakışma oranını hesapla.

    Her sembol için günlük sinyal varlığı (0/1) serisi oluştur.
    Pearson korelasyonunun ortalamasını döndür.
    """
    correlations = []
    for sym in symbols:
        don_r = next((r for r in don_results if r.get("symbol") == sym and "error" not in r), None)
        eng_r = next((r for r in eng_results if r.get("symbol") == sym and "error" not in r), None)
        if don_r is None or eng_r is None:
            continue

        don_ts = set(don_r.get("_signal_ts", []))
        eng_ts = set(eng_r.get("_signal_ts", []))
        if not don_ts and not eng_ts:
            continue

        # Tüm sinyal tarihlerini birleştir
        all_ts = sorted(don_ts | eng_ts)
        if len(all_ts) < 5:
            continue

        don_vec = np.array([1 if t in don_ts else 0 for t in all_ts])
        eng_vec = np.array([1 if t in eng_ts else 0 for t in all_ts])

        if don_vec.std() < 1e-8 or eng_vec.std() < 1e-8:
            correlations.append(0.0)
            continue

        corr = float(np.corrcoef(don_vec, eng_vec)[0, 1])
        correlations.append(corr)

    return float(np.mean(correlations)) if correlations else 0.0


# =====================================================================
# Aggregate hesaplama
# =====================================================================

def _aggregate(results: list[dict], label: str, initial_per_symbol: float = 10_000.0) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if not valid:
        return {"label": label, "valid": 0, "error": "no valid results"}

    n_trades = sum(r["n_trades"] for r in valid)
    avg_win = (
        sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    )
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
    # CAGR-based annual return (equal-weight portfolio average)
    annual = avg_cagr * 100

    # Best-effort net_pnl from equity_final if available
    net_pnl = sum(r.get("net_pnl", 0) for r in valid)
    starting_equity = initial_per_symbol * len(valid)
    total_return = net_pnl / starting_equity if net_pnl != 0 else (
        ((1 + avg_cagr) ** 3 - 1)  # 3y implied return from CAGR
    )

    return {
        "label": label,
        "valid": len(valid),
        "n_trades": n_trades,
        "avg_win_rate": avg_win,
        "net_pnl": net_pnl,
        "starting_equity": starting_equity,
        "total_return_pct": total_return * 100,
        "annual_return_pct": annual,
        "avg_max_drawdown_pct": avg_dd * 100,
        "avg_sharpe": avg_sharpe,
        "avg_cagr_pct": avg_cagr * 100,
        "avg_profit_factor": avg_pf,
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    don_manifest = _make_donchian_manifest()
    eng_manifest = _make_engulfing_manifest()

    print("=" * 78)
    print("H-005 DONCHIAN BREAKOUT + BOLLINGER SQUEEZE — Backtest Raporu")
    print(f"Sembol: {len(symbols)} × 1D × 3y  |  Kapital: 10K USDT/sembol")
    print("=" * 78)

    # ---- Donchian backtest ----
    print("\n--- [1] DonchianBreakoutStrategy per-sembol ---\n")
    don_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol_donchian(sym, don_manifest)
            don_results.append(r)
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} bars={r['n_bars']:>4} sigs={r['n_signals']:>3} "
                    f"trades={r['n_trades']:>3} win={r['win_rate']*100:>5.1f}% "
                    f"PF={r['profit_factor']:>5.2f} DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f} ({r['elapsed_sec']:.1f}s)"
                )
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            don_results.append({"symbol": sym, "error": str(exc)})

    # ---- Engulfing backtest ----
    print("\n--- [2] EngulfingContinuation per-sembol (karşılaştırma) ---\n")
    eng_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol_engulfing(sym, eng_manifest)
            eng_results.append({"symbol": sym, **r})
            if "error" in r:
                print(f"  {sym:<12} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<12} trades={r['n_trades']:>3} win={r['win_rate']*100:>5.1f}% "
                    f"PF={r['profit_factor']:>5.2f} DD={r['max_drawdown']*100:>5.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} CAGR={r['cagr']*100:>6.1f}% "
                    f"netP&L={r['net_pnl']:>+8.0f} ({r['elapsed_sec']:.1f}s)"
                )
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            eng_results.append({"symbol": sym, "error": str(exc)})

    # ---- Aggregate ----
    don_agg = _aggregate(don_results, "donchian_breakout")
    eng_agg = _aggregate(eng_results, "engulfing_continuation")

    print("\n" + "=" * 78)
    print("AGGREGATE KARŞILAŞTIRMA (equal-weight, naive portfolio)")
    print("=" * 78)
    print(f"\n{'Metrik':<30} {'Donchian':>14} {'Engulfing':>14}")
    print("-" * 60)
    for key, label in [
        ("valid", "Sembol (gecen)"),
        ("n_trades", "Toplam trade"),
        ("avg_win_rate", "Avg win rate (%)"),
        ("annual_return_pct", "Yillik return (%)"),
        ("avg_max_drawdown_pct", "Avg MaxDD (%)"),
        ("avg_sharpe", "Avg Sharpe"),
        ("avg_profit_factor", "Avg Profit Factor"),
    ]:
        d_val = don_agg.get(key, "N/A")
        e_val = eng_agg.get(key, "N/A")
        if isinstance(d_val, float) and key in ("avg_win_rate",):
            d_val *= 100  # fraction -> pct
        if isinstance(e_val, float) and key in ("avg_win_rate",):
            e_val *= 100
        if isinstance(d_val, float):
            print(f"  {label:<28} {d_val:>13.2f} {e_val:>13.2f}")
        else:
            print(f"  {label:<28} {str(d_val):>13} {str(e_val):>13}")

    # ---- Korelasyon ----
    print("\n--- [3] Sinyal Korelasyon Analizi (Decorrelation Testi) ---\n")
    corr = _compute_signal_correlation(don_results, eng_results, symbols)
    print(f"  Ortalama sinyal korelasyonu (Donchian vs Engulfing): {corr:+.3f}")
    if corr < 0.35:
        print(f"  Dekorelasyon: [PASS] (< 0.35) — Portfolio complementary")
    elif corr < 0.50:
        print(f"  Dekorelasyon: [MARGINAL] (0.35-0.50) — Kısmi complementary")
    else:
        print(f"  Dekorelasyon: [FAIL] (>= 0.50) — Yüksek overlap, REJECT")

    # ---- Combined portfolio (Donchian + Engulfing, equal-weight avg CAGR) ----
    print("\n--- [4] Combined Portfolio (Donchian + Engulfing, $10K × sembol) ---")
    don_annual = don_agg.get("annual_return_pct", 0.0)
    eng_annual = eng_agg.get("annual_return_pct", 0.0)
    # Equal-weight combination of the two strategies' average CAGR
    combined_annual = (don_annual + eng_annual) / 2.0
    print(f"  Donchian alone     : {don_annual:+.1f}% annual")
    print(f"  Engulfing alone    : {eng_annual:+.1f}% annual")
    print(f"  Combined (avg)     : {combined_annual:+.1f}% annual (equal-weight)")
    print(f"  Donchian Sharpe    : {don_agg.get('avg_sharpe', 0):.2f}")
    print(f"  Engulfing Sharpe   : {eng_agg.get('avg_sharpe', 0):.2f}")

    # ---- H-005 Gate değerlendirmesi ----
    print("\n" + "=" * 78)
    print("H-005 GATE DEĞERLENDİRMESİ")
    print("=" * 78)

    annual = don_agg.get("annual_return_pct", 0.0)
    avg_sharpe = don_agg.get("avg_sharpe", 0.0)
    avg_dd = don_agg.get("avg_max_drawdown_pct", 100.0)
    avg_pf = don_agg.get("avg_profit_factor", 0.0)

    gates = [
        ("Yillik net > %40",         annual,     40.0,  ">="),
        ("Sharpe > 0.8",             avg_sharpe,  0.8,  ">="),
        ("MaxDD < %45",              avg_dd,     45.0,  "<="),
        ("Profit Factor > 1.3",      avg_pf,      1.3,  ">="),
        ("Sinyal korel. < 0.35",     corr,        0.35, "<="),
    ]

    all_pass = True
    for label, value, target, op in gates:
        ok = (value >= target) if op == ">=" else (value <= target)
        status = "[PASS]" if ok else "[FAIL]"
        all_pass = all_pass and ok
        print(f"  {label:<30} actual={value:>8.3f}  target={target:>5.2f}  {status}")

    print()
    # Kısmi değerlendirme (SUPPLEMENT koşulu)
    return_ok = annual >= 40.0
    corr_ok = corr <= 0.35
    sharpe_ok = avg_sharpe >= 0.8
    dd_ok = avg_dd <= 45.0

    if all_pass:
        verdict = "PROMOTE"
        reason = "Tüm gates PASS — portföye ekle, walk-forward Faz 3'e geç."
    elif return_ok and corr_ok and not (sharpe_ok and dd_ok):
        verdict = "SUPPLEMENT"
        reason = "Return + decorrelation OK ama Sharpe/DD marginal — parametre fine-tune."
    elif not return_ok and corr_ok:
        verdict = "REJECT"
        reason = "Return gate FAIL. Parametre sweep veya hipotez revizyonu gerekli."
    elif not corr_ok:
        verdict = "REJECT"
        reason = "Yüksek korelasyon — engulfing ile fazla overlap, portfolio faydası yok."
    else:
        verdict = "REJECT"
        reason = "Birden fazla kritik gate FAIL."

    print(f"  VERDICT: {verdict}")
    print(f"  Gerekce: {reason}")

    # ---- Rapor kaydet ----
    report = {
        "hypothesis_id": "H-005",
        "run_date": datetime.now(timezone.utc).isoformat(),
        "donchian_per_symbol": [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in don_results
        ],
        "engulfing_per_symbol": [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in eng_results
        ],
        "donchian_aggregate": don_agg,
        "engulfing_aggregate": eng_agg,
        "signal_correlation": corr,
        "combined_annual_pct": combined_annual,
        "engulfing_alone_annual_pct": eng_agg.get("annual_return_pct", 0.0),
        "gates": [
            {"label": label, "actual": value, "target": target, "op": op,
             "pass": (value >= target) if op == ">=" else (value <= target)}
            for label, value, target, op in gates
        ],
        "verdict": verdict,
        "verdict_reason": reason,
    }
    report_dir = ROOT / "reports" / "backtests"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"donchian_backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
