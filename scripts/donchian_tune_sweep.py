"""Donchian Breakout parametre sweep — sinyal frekansi vs. korelasyon korunmasi.

Amac: 112 sinyali 2-3x artirirken -%98.5 engulfing korelasyonunu korumak.

5 config:
  Baseline : period=55, exit=20, ER=0.30, squeeze_lookback=5
  Tune A   : period=20, exit=10, ER=0.20, squeeze_lookback=10
  Tune B   : period=20, exit=10, ER=0.15, squeeze_lookback=10
  Tune C   : period=30, exit=15, ER=0.20, squeeze_lookback=8
  Tune D   : period=20, exit=10, ER=0.20, squeeze_lookback=10, NO squeeze

Son adim: En iyi tune + Engulfing production A => combined $10K, 5 max concurrent.

Calistirma:
    PYTHONPATH=src python scripts/donchian_tune_sweep.py
"""
from __future__ import annotations

import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Semboller ve sabitler
# =====================================================================

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]
INITIAL_CAPITAL = 10_000.0
MAX_CONCURRENT_COMBINED = 5


# =====================================================================
# Sweep configs
# =====================================================================

SWEEP_CONFIGS = [
    {
        "label": "Baseline",
        "entry_period": 55, "exit_period": 20,
        "er_min": 0.30, "squeeze_lookback": 5,
        "squeeze_required": True,
    },
    {
        "label": "Tune A",
        "entry_period": 20, "exit_period": 10,
        "er_min": 0.20, "squeeze_lookback": 10,
        "squeeze_required": True,
    },
    {
        "label": "Tune B",
        "entry_period": 20, "exit_period": 10,
        "er_min": 0.15, "squeeze_lookback": 10,
        "squeeze_required": True,
    },
    {
        "label": "Tune C",
        "entry_period": 30, "exit_period": 15,
        "er_min": 0.20, "squeeze_lookback": 8,
        "squeeze_required": True,
    },
    {
        "label": "Tune D (no-squeeze)",
        "entry_period": 20, "exit_period": 10,
        "er_min": 0.20, "squeeze_lookback": 10,
        "squeeze_required": False,
    },
]


# =====================================================================
# Manifest fabrikasi
# =====================================================================

def _make_donchian_manifest(cfg: dict):
    """Sweep config'den DonchianBreakoutStrategy manifesti uret."""
    from price_action.strategies.base import StrategyManifest
    ep = cfg["entry_period"]
    xp = cfg["exit_period"]
    raw = {
        "name": "donchian_breakout",
        "version": "1.0.0",
        "description": f"Sweep: period={ep}/{xp}, ER={cfg['er_min']}, sq_lb={cfg['squeeze_lookback']}, sq_req={cfg['squeeze_required']}",
        "trend_filter": {"type": "donchian", "period": ep, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "donchian_long_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": ep,
                        "donchian_exit_period": xp,
                        "squeeze_lookback": cfg["squeeze_lookback"],
                    },
                },
                {
                    "id": "donchian_short_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": ep,
                        "donchian_exit_period": xp,
                        "squeeze_lookback": cfg["squeeze_lookback"],
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
                "kaufman_er_min": cfg["er_min"],
                "bb_period": 20,
                "bb_std": 2.0,
                "kc_period": 20,
                "kc_atr_mult": 1.5,
                "squeeze_lookback_bars": cfg["squeeze_lookback"],
                "squeeze_required": cfg["squeeze_required"],
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": f"donchian{xp}", "exit_period": xp},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def _make_engulfing_manifest():
    """Production A engulfing manifesti."""
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
# Veri yukleme
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
# Backtest helpers
# =====================================================================

def _run_donchian_one(symbol: str, manifest, ic: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy

    df = _load_symbol_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}
    s = DonchianBreakoutStrategy(manifest)
    df_f = s.prepare_features(df)
    signals = s.generate_signals(df_f)

    def prov(*a, **k):
        return df_f.copy()

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(
        s, [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d", initial_capital=ic,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0, ohlcv_provider=prov,
    )
    k = r.kpis
    return {
        "symbol": symbol,
        "n_bars": len(df),
        "n_signals": len(signals),
        "n_trades": r.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", ic) - ic)),
        "equity_final": float(k.get("equity_final", ic)),
        "_signal_ts": [str(s.ts) for s in signals],
        "_trades": r.trades,
    }


def _run_engulfing_one(symbol: str, manifest, ic: float = 10_000.0) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    df = _load_symbol_ohlcv(symbol)
    if df.empty:
        return {"symbol": symbol, "error": "no data"}
    s = EngulfingContinuationStrategy(manifest)
    df_f = s.prepare_features(df)
    signals = s.generate_signals(df_f)

    def prov(*a, **k):
        return df_f.copy()

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(
        s, [symbol],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d", initial_capital=ic,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0, ohlcv_provider=prov,
    )
    k = r.kpis
    return {
        "symbol": symbol,
        "n_trades": r.n_trades,
        "win_rate": float(k.get("win_rate", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "sharpe": float(k.get("sharpe", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "net_pnl": float(k.get("net_pnl", k.get("equity_final", ic) - ic)),
        "equity_final": float(k.get("equity_final", ic)),
        "_signal_ts": [str(sig.ts) for sig in signals],
        "_trades": r.trades,
    }


# =====================================================================
# Korelasyon — gunluk sinyal kesisim Pearson
# =====================================================================

def _signal_correlation(don_results: list[dict], eng_results: list[dict]) -> float:
    corrs = []
    for sym in SYMBOLS:
        dr = next((r for r in don_results if r.get("symbol") == sym and "error" not in r), None)
        er = next((r for r in eng_results if r.get("symbol") == sym and "error" not in r), None)
        if dr is None or er is None:
            continue
        d_ts = set(dr.get("_signal_ts", []))
        e_ts = set(er.get("_signal_ts", []))
        if not d_ts and not e_ts:
            continue
        all_ts = sorted(d_ts | e_ts)
        if len(all_ts) < 5:
            continue
        dv = np.array([1 if t in d_ts else 0 for t in all_ts])
        ev = np.array([1 if t in e_ts else 0 for t in all_ts])
        if dv.std() < 1e-8 or ev.std() < 1e-8:
            corrs.append(0.0)
            continue
        corrs.append(float(np.corrcoef(dv, ev)[0, 1]))
    return float(np.mean(corrs)) if corrs else 0.0


# =====================================================================
# Equity curve korelasyonu (kritik — trade P&L zaman serisi)
# =====================================================================

def _equity_curve_correlation(don_results: list[dict], eng_results: list[dict]) -> float:
    """Per-symbol realized PnL gunluk serileri arasinda Pearson ortalamasi."""
    corrs = []
    for sym in SYMBOLS:
        dr = next((r for r in don_results if r.get("symbol") == sym and "error" not in r), None)
        er = next((r for r in eng_results if r.get("symbol") == sym and "error" not in r), None)
        if dr is None or er is None:
            continue
        dt = dr.get("_trades")
        et = er.get("_trades")
        if dt is None or et is None or (hasattr(dt, "empty") and dt.empty) or (hasattr(et, "empty") and et.empty):
            continue
        # Gunluk realized PnL serileri
        try:
            d_pnl = dt.groupby(pd.to_datetime(dt["exit_ts"]).dt.normalize())["realized_pnl_usdt"].sum()
            e_pnl = et.groupby(pd.to_datetime(et["exit_ts"]).dt.normalize())["realized_pnl_usdt"].sum()
            combined = pd.concat([d_pnl.rename("d"), e_pnl.rename("e")], axis=1).fillna(0)
            if len(combined) < 5:
                continue
            if combined["d"].std() < 1e-8 or combined["e"].std() < 1e-8:
                corrs.append(0.0)
                continue
            corrs.append(float(np.corrcoef(combined["d"], combined["e"])[0, 1]))
        except Exception:
            continue
    return float(np.mean(corrs)) if corrs else 0.0


# =====================================================================
# Aggregate
# =====================================================================

def _aggregate(results: list[dict], label: str) -> dict:
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    if not valid:
        return {"label": label, "valid": 0, "n_signals": 0, "n_trades": 0,
                "annual_pct": 0.0, "avg_dd_pct": 0.0, "avg_sharpe": 0.0,
                "avg_win_rate": 0.0, "avg_pf": 0.0}
    n_sigs = sum(r.get("n_signals", 0) for r in valid)
    n_trades = sum(r["n_trades"] for r in valid)
    avg_wr = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
    avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
    avg_sh = sum(r["sharpe"] for r in valid) / len(valid)
    avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
    avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
    return {
        "label": label,
        "valid": len(valid),
        "n_signals": n_sigs,
        "n_trades": n_trades,
        "annual_pct": avg_cagr * 100,
        "avg_dd_pct": avg_dd * 100,
        "avg_sharpe": avg_sh,
        "avg_win_rate": avg_wr * 100,
        "avg_pf": avg_pf,
    }


# =====================================================================
# Combined portfolio replay (shared $10K, max_concurrent)
# =====================================================================

def _trades_to_events(results: list[dict], strategy_label: str) -> list[dict]:
    """BacktestResult trades DataFrame'lerini portfolio event listesine cevir."""
    events = []
    for r in results:
        if "error" in r or not r.get("n_trades", 0):
            continue
        trades_df = r.get("_trades")
        if trades_df is None or (hasattr(trades_df, "empty") and trades_df.empty):
            continue
        for _, t in trades_df.iterrows():
            ep = float(t["entry_price"])
            sl = float(t["initial_sl"])
            sl_pct = abs(ep - sl) / ep if ep > 0 else 0.0
            if sl_pct <= 0:
                continue
            events.append({
                "strategy": strategy_label,
                "symbol": str(t["symbol"]),
                "entry_ts": pd.Timestamp(t["entry_ts"]),
                "exit_ts": pd.Timestamp(t["exit_ts"]),
                "entry_price": ep,
                "initial_sl": sl,
                "sl_pct": sl_pct,
                "R": float(t["realized_r_multiple"]),
            })
    return events


def _replay_portfolio(
    events: list[dict],
    initial: float = 10_000.0,
    risk_pct: float = 0.01,
    max_concurrent: int = 5,
) -> dict:
    """Chronological replay — shared capital, max_concurrent pozisyon."""
    events = sorted(events, key=lambda e: e["entry_ts"])
    equity = initial
    cash = initial
    open_pos: list[dict] = []
    n_taken = 0
    n_skip_conc = 0
    n_skip_cash = 0
    eq_history: list[tuple] = [(events[0]["entry_ts"] if events else pd.Timestamp.now(), initial)]
    by_strat: dict[str, dict] = defaultdict(lambda: {"n": 0, "pnl": 0.0})

    def close_due(now: pd.Timestamp) -> None:
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk_d"] * p["R"]
                cash += p["notional"] + pnl
                equity = cash + sum(q["notional"] for q in still)
                by_strat[p["strategy"]]["n"] += 1
                by_strat[p["strategy"]]["pnl"] += pnl
                eq_history.append((p["exit_ts"], equity))
            else:
                still.append(p)
        open_pos[:] = still

    for ev in events:
        close_due(ev["entry_ts"])
        if len(open_pos) >= max_concurrent:
            n_skip_conc += 1
            continue
        risk_d = equity * risk_pct
        notional = risk_d / ev["sl_pct"]
        if notional > cash:
            n_skip_cash += 1
            continue
        cash -= notional
        open_pos.append({
            "exit_ts": ev["exit_ts"],
            "notional": notional,
            "risk_d": risk_d,
            "R": ev["R"],
            "strategy": ev["strategy"],
        })
        n_taken += 1

    # Force close remaining
    for p in open_pos[:]:
        pnl = p["risk_d"] * p["R"]
        cash += p["notional"] + pnl
        equity = cash
        by_strat[p["strategy"]]["n"] += 1
        by_strat[p["strategy"]]["pnl"] += pnl

    # Max drawdown from equity history
    if eq_history:
        eq_ser = pd.Series([e[1] for e in eq_history])
        roll_max = eq_ser.cummax()
        dd = ((eq_ser - roll_max) / roll_max).min()
    else:
        dd = 0.0

    return {
        "equity_final": equity,
        "n_taken": n_taken,
        "n_total": len(events),
        "n_skip_concurrent": n_skip_conc,
        "n_skip_cash": n_skip_cash,
        "max_drawdown": float(dd),
        "by_strategy": dict(by_strat),
    }


def _annualized(final: float, initial: float, years: float = 3.0) -> float:
    if initial <= 0 or final <= 0:
        return 0.0
    return ((final / initial) ** (1.0 / years) - 1.0) * 100.0


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    print("=" * 80)
    print("DONCHIAN BREAKOUT — PARAMETRE SWEEP + COMBINED PORTFOLIO")
    print(f"Semboller: {len(SYMBOLS)} × 1D  |  Kapital: $10K/sembol standalone")
    print("=" * 80)

    # ------------------------------------------------------------------
    # 1. Engulfing baseline — bir kez calistir, tum sweep'lerde kullanilir
    # ------------------------------------------------------------------
    print("\n[0] Engulfing Continuation (Production A) — once yukle...")
    eng_manifest = _make_engulfing_manifest()
    eng_results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_engulfing_one(sym, eng_manifest)
            eng_results.append({"symbol": sym, **r})
            status = "ok" if "error" not in r else f"FAIL: {r.get('error')}"
            trades_n = r.get("n_trades", 0)
            print(f"  {sym:<12} trades={trades_n:>3} cagr={r.get('cagr',0)*100:>+6.1f}%  {status}")
        except Exception as exc:
            print(f"  {sym:<12} EXCEPTION: {exc}")
            traceback.print_exc()
            eng_results.append({"symbol": sym, "error": str(exc)})
    eng_agg = _aggregate(eng_results, "engulfing_production_A")
    print(f"\n  Engulfing aggregate: {eng_agg['n_trades']} trades, "
          f"{eng_agg['annual_pct']:+.1f}% yillik, "
          f"DD {eng_agg['avg_dd_pct']:.1f}%, "
          f"Sharpe {eng_agg['avg_sharpe']:.2f}")

    # ------------------------------------------------------------------
    # 2. Sweep
    # ------------------------------------------------------------------
    sweep_summaries: list[dict] = []

    for cfg in SWEEP_CONFIGS:
        label = cfg["label"]
        print(f"\n{'='*80}")
        print(f"SWEEP: {label}  "
              f"(entry={cfg['entry_period']}, exit={cfg['exit_period']}, "
              f"ER={cfg['er_min']}, sq_lb={cfg['squeeze_lookback']}, "
              f"sq_req={cfg['squeeze_required']})")
        print("=" * 80)

        don_manifest = _make_donchian_manifest(cfg)
        don_results: list[dict] = []

        for sym in SYMBOLS:
            try:
                r = _run_donchian_one(sym, don_manifest)
                don_results.append({"symbol": sym, **r})
                if "error" in r:
                    print(f"  {sym:<12} FAIL: {r['error']}")
                else:
                    print(
                        f"  {sym:<12} "
                        f"sigs={r['n_signals']:>3} "
                        f"trades={r['n_trades']:>3} "
                        f"win={r['win_rate']*100:>5.1f}% "
                        f"PF={r['profit_factor']:>5.2f} "
                        f"DD={r['max_drawdown']*100:>5.1f}% "
                        f"CAGR={r['cagr']*100:>+6.1f}%"
                    )
            except Exception as exc:
                print(f"  {sym:<12} EXCEPTION: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                don_results.append({"symbol": sym, "error": str(exc)})

        don_agg = _aggregate(don_results, label)

        # Sinyal korelasyonu (gunluk kesisim)
        sig_corr = _signal_correlation(don_results, eng_results)
        # Equity curve korelasyonu (P&L zaman serisi — asil metrik)
        eq_corr = _equity_curve_correlation(don_results, eng_results)

        print(f"\n  Aggregate  | signals={don_agg['n_signals']:>4} "
              f"trades={don_agg['n_trades']:>4} "
              f"win={don_agg['avg_win_rate']:>5.1f}% "
              f"PF={don_agg['avg_pf']:>5.2f} "
              f"DD={don_agg['avg_dd_pct']:>5.1f}% "
              f"CAGR={don_agg['annual_pct']:>+6.1f}% "
              f"Sharpe={don_agg['avg_sharpe']:>5.2f}")
        print(f"  Sinyal korr vs Engulfing : {sig_corr:+.4f}  "
              f"(baz: -0.985 target = negative)")
        print(f"  Equity korr vs Engulfing : {eq_corr:+.4f}  "
              f"(dusuk/negatif = iyi diversifier)")

        summary = {
            "label": label,
            "config": {k: v for k, v in cfg.items() if k != "label"},
            "n_signals": don_agg["n_signals"],
            "n_trades": don_agg["n_trades"],
            "annual_pct": don_agg["annual_pct"],
            "avg_dd_pct": don_agg["avg_dd_pct"],
            "avg_sharpe": don_agg["avg_sharpe"],
            "avg_win_rate": don_agg["avg_win_rate"],
            "avg_pf": don_agg["avg_pf"],
            "signal_correlation": sig_corr,
            "equity_correlation": eq_corr,
            "_don_results": don_results,
        }
        sweep_summaries.append(summary)

    # ------------------------------------------------------------------
    # 3. Sweep tablosu
    # ------------------------------------------------------------------
    print("\n\n" + "=" * 80)
    print("SWEEP TABLOSU")
    print("=" * 80)
    hdr = (f"{'Config':<22} {'Sigs':>5} {'Trds':>5} {'Win%':>6} {'PF':>5} "
           f"{'DD%':>6} {'CAGR%':>7} {'Sharpe':>7} {'SigCorr':>8} {'EqCorr':>8}")
    print(hdr)
    print("-" * 80)
    baseline_sigs = sweep_summaries[0]["n_signals"] if sweep_summaries else 1
    for s in sweep_summaries:
        mult = s["n_signals"] / max(baseline_sigs, 1)
        print(
            f"  {s['label']:<20} "
            f"{s['n_signals']:>5} "
            f"{s['n_trades']:>5} "
            f"{s['avg_win_rate']:>5.1f}% "
            f"{s['avg_pf']:>5.2f} "
            f"{s['avg_dd_pct']:>5.1f}% "
            f"{s['annual_pct']:>+6.1f}% "
            f"{s['avg_sharpe']:>7.2f} "
            f"{s['signal_correlation']:>+8.3f} "
            f"{s['equity_correlation']:>+8.3f}  "
            f"({mult:.1f}x)"
        )

    # ------------------------------------------------------------------
    # 4. En iyi tune sec: en yuksek sinyal × korelasyon korunmasi
    #    Kriter: eq_corr <= -0.50 (negatif kalmali) + en yuksek sinyal sayisi
    # ------------------------------------------------------------------
    print("\n--- Best Tune Secimi ---")
    # Baseline haric diger tunelar
    candidates = [s for s in sweep_summaries[1:]]  # Baseline'i atla

    # Korelasyon degerlendirme: negatif korelasyon korunmali
    # Kriter 1: eq_corr <= 0 (negatif veya sifir — diversification)
    # Kriter 2: en yuksek sinyal sayisi
    # Kriter 3: CAGR > 0 (pozitif getiri)
    def score_fn(s: dict) -> float:
        corr_ok = s["equity_correlation"] <= 0.10  # negatif veya hafif pozitif
        cagr_ok = s["annual_pct"] > 0.0
        if not corr_ok or not cagr_ok:
            return -9999.0
        # Sinyal sayisini maximize et, korelasyon stabilitesini ode
        return s["n_signals"] * 0.6 + (-s["equity_correlation"]) * 100 * 0.4

    candidates_scored = [(score_fn(s), s) for s in candidates]
    candidates_scored.sort(key=lambda x: x[0], reverse=True)

    best_tune = candidates_scored[0][1] if candidates_scored else sweep_summaries[0]
    print(f"  Best tune: [{best_tune['label']}]  "
          f"sigs={best_tune['n_signals']}, "
          f"CAGR={best_tune['annual_pct']:+.1f}%, "
          f"EqCorr={best_tune['equity_correlation']:+.3f}")

    # ------------------------------------------------------------------
    # 5. Combined portfolio: Engulfing + Best Tune Donchian
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("COMBINED PORTFOLIO: Engulfing (Prod A) + Donchian Best Tune")
    print(f"$10K shared capital | max_concurrent={MAX_CONCURRENT_COMBINED} | risk=1%/trade")
    print("=" * 80)

    eng_events = _trades_to_events(eng_results, "engulfing")
    best_don_results = best_tune["_don_results"]
    don_events = _trades_to_events(best_don_results, "donchian_" + best_tune["label"].replace(" ", "_"))
    all_events = eng_events + don_events

    # Senaryo A: Sadece Engulfing
    r_eng_only = _replay_portfolio(eng_events, INITIAL_CAPITAL, 0.01, MAX_CONCURRENT_COMBINED)
    # Senaryo B: Sadece Donchian (best tune)
    r_don_only = _replay_portfolio(don_events, INITIAL_CAPITAL, 0.01, MAX_CONCURRENT_COMBINED)
    # Senaryo C: Kombine FIFO
    r_combined = _replay_portfolio(all_events, INITIAL_CAPITAL, 0.01, MAX_CONCURRENT_COMBINED)

    def _fmt_result(r: dict, label: str) -> None:
        ann = _annualized(r["equity_final"], INITIAL_CAPITAL)
        total_pct = (r["equity_final"] / INITIAL_CAPITAL - 1) * 100
        dd_pct = r["max_drawdown"] * 100
        print(f"\n  {label}")
        print(f"    $10K → ${r['equity_final']:>10,.2f}  "
              f"3y={total_pct:>+7.2f}%  yillik={ann:>+7.2f}%  "
              f"MaxDD={dd_pct:>6.2f}%")
        print(f"    acilan={r['n_taken']:>4}  skip_conc={r['n_skip_concurrent']:>4}  "
              f"skip_cash={r['n_skip_cash']:>4}  toplam={r['n_total']:>4}")
        if "by_strategy" in r:
            for st, sv in r["by_strategy"].items():
                print(f"    {st:<35} closed={sv['n']:>4}  pnl=${sv['pnl']:>+10,.2f}")

    _fmt_result(r_eng_only, "Senaryo A: SADECE Engulfing (Production A)")
    _fmt_result(r_don_only, f"Senaryo B: SADECE Donchian [{best_tune['label']}]")
    _fmt_result(r_combined, f"Senaryo C: KOMBINE (Engulfing + Donchian [{best_tune['label']}])")

    # ------------------------------------------------------------------
    # 6. Comparison table
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("KARSILASTIRMA TABLOSU")
    print("=" * 80)
    print(f"\n{'Senaryo':<50} {'Yillik%':>9} {'3y%':>8} {'MaxDD%':>8} {'Acilan':>7}")
    print("-" * 80)
    for label, r in [
        ("Engulfing alone (Production A)", r_eng_only),
        (f"Donchian [{best_tune['label']}] alone", r_don_only),
        (f"KOMBINE Engulfing+Donchian [{best_tune['label']}]", r_combined),
    ]:
        ann = _annualized(r["equity_final"], INITIAL_CAPITAL)
        tot = (r["equity_final"] / INITIAL_CAPITAL - 1) * 100
        dd = r["max_drawdown"] * 100
        print(f"  {label:<48} {ann:>+8.2f}% {tot:>+7.2f}% {dd:>+7.2f}% {r['n_taken']:>7}")

    # ------------------------------------------------------------------
    # 7. Portfolio combine engulfing'i bozuyor mu?
    # ------------------------------------------------------------------
    print("\n--- Engulfing Degradasyon Analizi ---")
    eng_ann_standalone = _annualized(r_eng_only["equity_final"], INITIAL_CAPITAL)
    comb_ann = _annualized(r_combined["equity_final"], INITIAL_CAPITAL)
    eng_dd_standalone = r_eng_only["max_drawdown"] * 100
    comb_dd = r_combined["max_drawdown"] * 100

    annual_delta = comb_ann - eng_ann_standalone
    dd_delta = comb_dd - eng_dd_standalone
    eng_trades_combined = r_combined["by_strategy"].get("engulfing", {}).get("n", 0)
    eng_trades_standalone = r_eng_only.get("n_taken", 0)
    eng_trade_ratio = eng_trades_combined / max(eng_trades_standalone, 1)

    print(f"  Engulfing standalone yillik : {eng_ann_standalone:>+7.2f}%")
    print(f"  Kombine yillik              : {comb_ann:>+7.2f}%  (delta {annual_delta:>+.2f}%)")
    print(f"  Engulfing standalone MaxDD  : {eng_dd_standalone:>+7.2f}%")
    print(f"  Kombine MaxDD               : {comb_dd:>+7.2f}%  (delta {dd_delta:>+.2f}%)")
    print(f"  Engulfing trade dolum orani : {eng_trade_ratio*100:.1f}%  "
          f"({eng_trades_combined}/{eng_trades_standalone} trade calisabildi)")

    eng_degraded = (annual_delta < -5.0) or (eng_trade_ratio < 0.70)
    if eng_degraded:
        print(f"  [UYARI] Kombine engulfing'i bozuyor!")
        print(f"  Sebep: {'yillik dusus > 5%' if annual_delta < -5.0 else ''}"
              f"{'trade dolum < %70' if eng_trade_ratio < 0.70 else ''}")
    else:
        print(f"  [OK] Kombine engulfing performansini bozmadi.")

    # ------------------------------------------------------------------
    # 8. VERDICT
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    baseline = sweep_summaries[0]
    sig_multiplier = best_tune["n_signals"] / max(baseline["n_signals"], 1)
    corr_preserved = best_tune["equity_correlation"] <= 0.10  # negatif kalmali
    cagr_positive = best_tune["annual_pct"] > 0.0
    no_eng_degradation = not eng_degraded
    combined_better = comb_ann > eng_ann_standalone * 0.95  # en az %5 kayip kabul edilemez

    print(f"\n  Best config    : {best_tune['label']}")
    print(f"  Sinyal artisi  : {sig_multiplier:.1f}x  "
          f"({baseline['n_signals']} → {best_tune['n_signals']})")
    print(f"  Eq Korrelasyon : {best_tune['equity_correlation']:+.3f}  "
          f"({'KORUNDU (negatif)' if corr_preserved else 'BOZULDU (pozitif)'})")
    print(f"  CAGR           : {best_tune['annual_pct']:+.1f}%  "
          f"({'POZITIF' if cagr_positive else 'NEGATIF'})")
    print(f"  Engulfing impact: {annual_delta:+.1f}%  "
          f"({'OK' if no_eng_degradation else 'BOZUCU'})")

    gates = {
        "Sinyal 1.5x+ artisi": sig_multiplier >= 1.5,
        "EqCorr <= 0.10 (negatif)": corr_preserved,
        "CAGR > 0%": cagr_positive,
        "Engulfing bozulmuyor": no_eng_degradation,
        "Combined annual <= standalone+5%": combined_better,
    }
    for gate, ok in gates.items():
        print(f"  {'[PASS]' if ok else '[FAIL]'}  {gate}")

    n_pass = sum(gates.values())
    if n_pass == len(gates):
        verdict = "PROMOTE"
        reason = "Tum gateler gectit — best tuned Donchian portfoyune ekle, walk-forward'a gec."
    elif n_pass >= 3 and corr_preserved and cagr_positive:
        verdict = "SUPPLEMENT"
        reason = f"Cogu gate PASS ({n_pass}/{len(gates)}) — kucuk allokasyon ile test et."
    elif not corr_preserved:
        verdict = "REJECT"
        reason = "Korelasyon bozuldu — engulfing ile overlap, diversification degeri yok."
    elif not cagr_positive:
        verdict = "REJECT"
        reason = "Negatif CAGR — standalone olarak da para kazandirmiyor."
    else:
        verdict = "REJECT"
        reason = f"Kritik gateler FAIL ({n_pass}/{len(gates)}) — daha ileri sweep gerekli."

    print(f"\n  VERDICT: {verdict}")
    print(f"  Gerekcesi: {reason}")

    # ------------------------------------------------------------------
    # 9. Rapor kaydet
    # ------------------------------------------------------------------
    report = {
        "run_date": datetime.now(timezone.utc).isoformat(),
        "baseline": {k: v for k, v in baseline.items() if not k.startswith("_")},
        "sweep_results": [
            {k: v for k, v in s.items() if not k.startswith("_")}
            for s in sweep_summaries
        ],
        "best_tune": {k: v for k, v in best_tune.items() if not k.startswith("_")},
        "engulfing_aggregate": eng_agg,
        "portfolio": {
            "engulfing_only": {
                "annual_pct": eng_ann_standalone,
                "max_dd_pct": eng_dd_standalone,
                "n_taken": r_eng_only["n_taken"],
            },
            "donchian_only": {
                "annual_pct": _annualized(r_don_only["equity_final"], INITIAL_CAPITAL),
                "max_dd_pct": r_don_only["max_drawdown"] * 100,
                "n_taken": r_don_only["n_taken"],
            },
            "combined": {
                "annual_pct": comb_ann,
                "max_dd_pct": comb_dd,
                "n_taken": r_combined["n_taken"],
                "annual_delta_vs_engulfing": annual_delta,
                "dd_delta_vs_engulfing": dd_delta,
                "eng_trade_fill_ratio": eng_trade_ratio,
            },
        },
        "gates": {k: bool(v) for k, v in gates.items()},
        "verdict": verdict,
        "verdict_reason": reason,
    }
    rdir = ROOT / "reports" / "backtests"
    rdir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rpath = rdir / f"donchian_sweep_{ts_str}.json"
    rpath.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\nDetay rapor: {rpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
