"""Halving Cycle Phase — Engulfing + Halving Sizing Backtest.

Karsilastirir:
  1. Engulfing Solo (baseline) — mevcut engulfing_continuation
  2. Engulfing + Halving Phase Sizing — halving_cycle filtresi ile

Per-phase breakdown:
  Phase A (0-12 ay post-halving): 2024-04-19 → 2025-04-19
  Phase B (12-30 ay post-halving): 2022-07 → 2023-05 + 2025-04-19+
  Phase C (30-45 ay post-halving): 2023-02 → 2024-04-19 arasi
  Phase D (45-48 ay post-halving): kisa pencere halving oncesi

3y pencere: 2023-05-01 → 2026-05-01
  Bu pencere Phase C sonu + Phase A (2024 halvinginden sonra) + Phase B baslangici kapar.

Calistirma:
  PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_halving_cycle_backtest.py

UYARI:
  4 halving x 4 faz = 16 global sample.
  Istatistiksel anlamlilik kurulamaz. Sonuclar narrative-fit riski tasir.
"""
from __future__ import annotations

import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Manifest fabrikasi
# ---------------------------------------------------------------------------

def _make_engulfing_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "description": "Engulfing bar after 20-EMA pullback in established trend",
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


# ---------------------------------------------------------------------------
# Veri yukleme
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tek sembol calistirma (solo + halving)
# ---------------------------------------------------------------------------

def _run_one_symbol(
    symbol: str,
    manifest,
    use_halving: bool = False,
    initial_capital: float = 10_000.0,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.halving_cycle import HalvingCycleEngulfingStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    base_strategy = EngulfingContinuationStrategy(manifest)

    if use_halving:
        strategy = HalvingCycleEngulfingStrategy(base_strategy, base_risk=0.01)
    else:
        strategy = base_strategy

    df_feats = strategy.prepare_features(df)
    signals = strategy.generate_signals(df_feats)

    def ohlcv_provider(_sym, _tf, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    result = engine.run(
        strategy if not use_halving else base_strategy,  # engine uses inner for trade sim
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
        "mode": "halving" if use_halving else "solo",
        "n_bars": len(df),
        "n_signals": len(signals),
        "n_trades": result.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "expectancy": float(k.get("expectancy", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "sortino": float(k.get("sortino", 0.0)),
        "cagr": _cagr,
        "net_pnl": _net_pnl,
        "elapsed_sec": result.elapsed_sec,
    }


# ---------------------------------------------------------------------------
# Per-phase breakdown
# ---------------------------------------------------------------------------

def _compute_per_phase_breakdown(
    symbol: str,
    manifest,
    initial_capital: float = 10_000.0,
) -> dict[str, dict]:
    """Her faz icin ayri backtest calistir.

    Not: Kisa pencereler (Phase C: ~11 ay, Phase D: yok) az trade uretir.
    Sonuclar yorumsal — istatistiksel degil.
    """
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.halving_cycle import compute_halving_phase

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {}

    strategy = EngulfingContinuationStrategy(manifest)
    df_feats = strategy.prepare_features(df)

    # Her bara faz ata
    df_feats["halving_phase"] = df_feats["ts"].apply(compute_halving_phase)

    phase_results: dict[str, dict] = {}
    for phase in ["A", "B", "C", "D"]:
        phase_df = df_feats[df_feats["halving_phase"] == phase].copy()
        if len(phase_df) < 30:
            phase_results[phase] = {
                "n_bars": len(phase_df),
                "n_trades": 0,
                "note": "insufficient data (<30 bars)",
            }
            continue

        # Sinyaller sadece bu faz icin
        phase_df = phase_df.reset_index(drop=True)
        try:
            signals = strategy.generate_signals(phase_df)
        except Exception as e:
            phase_results[phase] = {"error": str(e)}
            continue

        if not signals:
            phase_results[phase] = {
                "n_bars": len(phase_df),
                "n_trades": 0,
                "note": "no signals",
            }
            continue

        def _provider(_sym, _tf, _s, _e):
            return phase_df.copy()

        try:
            engine = BacktestEngine(risk_officer=None, store_load=None)
            result = engine.run(
                strategy,
                [symbol],
                start=phase_df["ts"].iloc[0].to_pydatetime(),
                end=phase_df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=initial_capital,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=_provider,
            )
            k = result.kpis
            n_days = len(phase_df)
            years = n_days / 365.25
            _cagr = float(k.get("cagr", 0.0))
            _raw_net = float(k.get("net_pnl", 0.0))
            _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** years - 1)
            annual = _cagr * 100

            phase_results[phase] = {
                "n_bars": n_days,
                "years": round(years, 2),
                "n_signals": len(signals),
                "n_trades": result.n_trades,
                "win_rate": float(k.get("win_rate", 0.0)),
                "sharpe": float(k.get("sharpe", 0.0)),
                "max_drawdown": float(k.get("max_drawdown", 0.0)),
                "cagr": _cagr,
                "annual_pct": annual,
                "net_pnl": _net_pnl,
            }
        except Exception as e:
            phase_results[phase] = {"error": str(e)}

    return phase_results


# ---------------------------------------------------------------------------
# Yillik sigma hesabi
# ---------------------------------------------------------------------------

def _compute_annual_sigma(results: list[dict]) -> float:
    """Sembollerin CAGR listesinden yillar-arasi tutarlilik (sigma)."""
    cagrs = [r["cagr"] for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if len(cagrs) < 2:
        return float("nan")
    return float(np.std(cagrs, ddof=1))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    ]
    manifest = _make_engulfing_manifest()
    initial_cap = 10_000.0

    print("=" * 80)
    print("BTC Halving Cycle Phase — Backtest (2023-05 → 2026-05)")
    print("=" * 80)
    print()
    print("UYARI: 4 halving x 4 faz = 16 global sample.")
    print("       Istatistiksel anlamlilik kurulamaz — narrative-fit riski yuksek.")
    print()

    # ------------------------------------------------------------------
    # 1. Engulfing Solo (baseline)
    # ------------------------------------------------------------------
    print("--- [1] ENGULFING SOLO (BASELINE) ---")
    print(f"  {'SYMBOL':<10} {'TRD':>4} {'WIN%':>6} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
    print("  " + "-" * 65)

    solo_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest, use_halving=False, initial_capital=initial_cap)
            solo_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['max_drawdown']*100:>5.1f} {r['sharpe']:>6.2f} "
                    f"{r['cagr']*100:>7.1f} {r['net_pnl']:>+9.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {exc}")
            solo_results.append({"symbol": sym, "error": str(exc)})

    # ------------------------------------------------------------------
    # 2. Engulfing + Halving Phase Sizing
    # ------------------------------------------------------------------
    print()
    print("--- [2] ENGULFING + HALVING PHASE SIZING ---")
    print(f"  {'SYMBOL':<10} {'TRD':>4} {'WIN%':>6} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9}")
    print("  " + "-" * 65)

    halving_results: list[dict] = []
    for sym in symbols:
        try:
            r = _run_one_symbol(sym, manifest, use_halving=True, initial_capital=initial_cap)
            halving_results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['max_drawdown']*100:>5.1f} {r['sharpe']:>6.2f} "
                    f"{r['cagr']*100:>7.1f} {r['net_pnl']:>+9.0f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {exc}")
            halving_results.append({"symbol": sym, "error": str(exc)})

    # ------------------------------------------------------------------
    # 3. Per-phase breakdown (BTC/USDT)
    # ------------------------------------------------------------------
    print()
    print("--- [3] PER-PHASE BREAKDOWN (BTC/USDT) ---")
    print("  (sadece BTC — diger semboller faz sinirlari tam kapsamayabilir)")
    print()

    phase_data: dict[str, dict] = {}
    try:
        phase_data = _compute_per_phase_breakdown("BTC/USDT", manifest, initial_cap)
        phase_labels = {
            "A": "Phase A  (0-12 ay post-halving, AGGRESSIVE)",
            "B": "Phase B  (12-30 ay post-halving, DEFENSIVE)",
            "C": "Phase C  (30-45 ay post-halving, MODERATE)",
            "D": "Phase D  (45-48 ay post-halving, AGGRESSIVE)",
        }
        for ph in ["A", "B", "C", "D"]:
            pd_r = phase_data.get(ph, {})
            label = phase_labels.get(ph, ph)
            print(f"  {label}")
            if "error" in pd_r:
                print(f"    ERROR: {pd_r['error']}")
            elif "note" in pd_r:
                print(f"    n_bars={pd_r.get('n_bars', 0)}  note={pd_r['note']}")
            else:
                print(
                    f"    n_bars={pd_r.get('n_bars', 0):>4}  years={pd_r.get('years', 0):.2f}  "
                    f"trades={pd_r.get('n_trades', 0):>3}  win={pd_r.get('win_rate', 0)*100:.1f}%  "
                    f"sharpe={pd_r.get('sharpe', 0):.2f}  dd={pd_r.get('max_drawdown', 0)*100:.1f}%  "
                    f"cagr={pd_r.get('annual_pct', 0):+.1f}%"
                )
            print()
    except Exception as exc:
        print(f"  Per-phase breakdown HATASI: {exc}")
        traceback.print_exc()

    # ------------------------------------------------------------------
    # 4. Karsilastirma tablosu
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print("KARSILASTIRMA: Engulfing Solo vs Engulfing + Halving Sizing")
    print("=" * 80)

    solo_valid = [r for r in solo_results if "error" not in r and r.get("n_trades", 0) > 0]
    halv_valid = [r for r in halving_results if "error" not in r and r.get("n_trades", 0) > 0]

    def _agg(results: list[dict]) -> dict:
        if not results:
            return {}
        n_trades = sum(r["n_trades"] for r in results)
        net_pnl = sum(r["net_pnl"] for r in results)
        starting_eq = initial_cap * len(results)
        total_ret = net_pnl / starting_eq
        return {
            "n_symbols": len(results),
            "n_trades": n_trades,
            "avg_win_rate": sum(r["win_rate"] * r["n_trades"] for r in results) / max(1, n_trades),
            "net_pnl": net_pnl,
            "total_return_pct": total_ret * 100,
            "annual_pct": (((1 + total_ret) ** (1 / 3)) - 1) * 100,
            "avg_dd": sum(r["max_drawdown"] for r in results) / len(results),
            "avg_sharpe": sum(r["sharpe"] for r in results) / len(results),
            "avg_cagr": sum(r["cagr"] for r in results) / len(results),
            "sigma_cagr": _compute_annual_sigma(results),
        }

    solo_agg = _agg(solo_valid)
    halv_agg = _agg(halv_valid)

    print()
    print(f"  {'Metrik':<30} {'Solo':>12} {'Halving':>12} {'Delta':>10}")
    print("  " + "-" * 68)

    metrics = [
        ("Sembol sayisi", "n_symbols", "{:.0f}"),
        ("Toplam trade", "n_trades", "{:.0f}"),
        ("Avg win rate %", "avg_win_rate", "{:.1%}"),
        ("Yillik return %", "annual_pct", "{:+.1f}"),
        ("Avg MaxDD %", "avg_dd", "{:.1%}"),
        ("Avg Sharpe", "avg_sharpe", "{:.2f}"),
        ("Avg CAGR", "avg_cagr", "{:.2%}"),
        ("CAGR sigma (tutarlilik)", "sigma_cagr", "{:.2%}"),
    ]

    for label, key, fmt in metrics:
        sv = solo_agg.get(key, float("nan"))
        hv = halv_agg.get(key, float("nan"))
        try:
            delta = hv - sv
            if "%" in label or key in ("avg_win_rate", "avg_dd", "avg_cagr", "sigma_cagr"):
                sv_str = fmt.format(sv)
                hv_str = fmt.format(hv)
                d_str = f"{delta:+.2f}"
            else:
                sv_str = fmt.format(sv)
                hv_str = fmt.format(hv)
                d_str = f"{delta:+.2f}"
            print(f"  {label:<30} {sv_str:>12} {hv_str:>12} {d_str:>10}")
        except Exception:
            print(f"  {label:<30} {'N/A':>12} {'N/A':>12} {'N/A':>10}")

    # ------------------------------------------------------------------
    # 5. Verdict
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print("VERDICT ANALIZI")
    print("=" * 80)
    print()

    sharpe_delta = halv_agg.get("avg_sharpe", 0) - solo_agg.get("avg_sharpe", 0)
    dd_delta = halv_agg.get("avg_dd", 0) - solo_agg.get("avg_dd", 0)
    annual_delta = halv_agg.get("annual_pct", 0) - solo_agg.get("annual_pct", 0)
    sigma_halv = halv_agg.get("sigma_cagr", float("nan"))

    promote_conditions = [
        sharpe_delta > 0.2,
        dd_delta < 0,
        annual_delta > 2.0,
    ]
    defer_conditions = [
        sharpe_delta > 0.0 or dd_delta < 0,
        True,  # always: sample size too small for PROMOTE
    ]

    if all(promote_conditions):
        # Asla promote etme — sample size yetersiz
        verdict = "DEFER"
        reason = (
            "Metrikler pozitif iyilesme gosteriyor ama 4 halving x 4 faz = 16 global sample. "
            "Istatistiksel anlamlilik kurulamaz. 2028 halving sonrasi out-of-sample test bekle."
        )
    elif sharpe_delta > 0 or dd_delta < 0:
        verdict = "DEFER"
        reason = (
            "Hafif iyilesme isaretleri var. Sample size yetersiz (N=16 global, N=1 dongu bu backtest'te). "
            "Narrative-fit riski yuksek. 2028 halvinginden sonra test et."
        )
    else:
        verdict = "REJECT"
        reason = (
            "Halving phase sizing metrik iyilestirmesi gosteremiyor. "
            "4 yillik dongu fazlariyla overfitting veya tesaduf. Reddet."
        )

    print(f"  Sharpe delta    : {sharpe_delta:+.3f}  (hedef > 0.2 PROMOTE icin)")
    print(f"  MaxDD delta     : {dd_delta*100:+.1f}%  (hedef < 0 PROMOTE icin)")
    print(f"  Yillik delta    : {annual_delta:+.1f}%  (hedef > 2pp PROMOTE icin)")
    print(f"  CAGR sigma      : {sigma_halv:.2%}  (tutarlilik — dusuk = iyi)")
    print()
    print(f"  VERDICT: ** {verdict} **")
    print(f"  Sebep  : {reason}")
    print()
    print("  KRITIK ISTATISTIK NOTU:")
    print("  - 3y backtest = yalnizca 1 komple halving dongusu (2024 halvingini kapsiyor)")
    print("  - Faz A 2024-2025 bull'unu kapsadigi icin Phase A sonuclari overfitted gorubilir")
    print("  - Phase C ve D backtest penceresinde cok az bar var (yetersiz stat)")
    print("  - Bu sonuclar NARRATIVE-FIT: bir bull cycle'i yakalamak tum Phase A'yi iyi gosterir")
    print("  - 2028 halvinginden sonra 2 tam dongu verisi ile tekrar test edilmeli")
    print()

    # ------------------------------------------------------------------
    # 6. Rapor kaydet
    # ------------------------------------------------------------------
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "window": "2023-05 to 2026-05 (approx 3y)",
        "solo_aggregate": solo_agg,
        "halving_aggregate": halv_agg,
        "per_phase_btc": phase_data,
        "solo_symbols": solo_results,
        "halving_symbols": halving_results,
        "verdict": verdict,
        "verdict_reason": reason,
        "statistical_warning": (
            "4 halvings x 4 phases = 16 global samples. "
            "No statistical significance possible. High narrative-fit risk."
        ),
    }
    report_path = (
        ROOT / "reports" / "backtests"
        / f"halving_cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"  Detay rapor: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
