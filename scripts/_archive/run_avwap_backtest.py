"""Anchored VWAP + POC Reversal stratejisi icin gercek 3y backtest.

10 USDT sembolu * 1d * ~1095 bar.
Standalone backtest + engulfing_continuation ile kombine portfoy testi.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_avwap_backtest.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]
INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01
MAX_CONCURRENT = 5


# =====================================================================
# Manifest
# =====================================================================

def _make_avwap_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "anchored_vwap_reversal",
        "version": "1.0.0",
        "description": "Anchored VWAP + POC mean-reversion",
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "avwap_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_long_max": 55.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
                    },
                },
                {
                    "id": "avwap_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_short_min": 45.0,
                        "avwap_swing_lookback": 60,
                        "poc_lookback": 60,
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
            "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": RISK_PER_TRADE},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Data loader
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
# Single symbol backtest
# =====================================================================

def _run_one_symbol_avwap(symbol: str, manifest, initial_capital: float = INITIAL_CAPITAL) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.anchored_vwap_reversal import AnchoredVWAPReversalStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = AnchoredVWAPReversalStrategy(manifest)
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
    _cagr = float(k.get("cagr", 0.0))
    _raw_net = float(k.get("net_pnl", 0.0))
    _net_pnl = _raw_net if _raw_net != 0.0 else initial_capital * ((1 + _cagr) ** 3 - 1)

    # Yearly breakdown from trades
    yearly = {}
    if hasattr(result, "trades") and result.trades is not None and len(result.trades) > 0:
        trades_df = result.trades.copy()
        if "exit_ts" in trades_df.columns:
            trades_df["year"] = pd.to_datetime(trades_df["exit_ts"]).dt.year
            for yr, grp in trades_df.groupby("year"):
                yearly[int(yr)] = {
                    "n_trades": len(grp),
                    "win_rate": float((grp["realized_r_multiple"] > 0).mean()) if len(grp) > 0 else 0.0,
                }

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
        "cagr": _cagr,
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "net_pnl": _net_pnl,
        "equity_final": float(k.get("equity_final", initial_capital)),
        "elapsed_sec": result.elapsed_sec,
        "yearly": yearly,
    }


# =====================================================================
# Combined portfolio replay
# =====================================================================

def _gather_avwap_trades(manifest) -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.anchored_vwap_reversal import AnchoredVWAPReversalStrategy
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df.empty:
            continue
        s = AnchoredVWAPReversalStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **kw): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=INITIAL_CAPITAL,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=prov,
        )
        if hasattr(r, "trades") and r.trades is not None and len(r.trades) > 0:
            for _, t in r.trades.iterrows():
                ep = float(t.get("entry_price", 0.0))
                sl = float(t.get("initial_sl", 0.0))
                R = float(t.get("realized_r_multiple", 0.0))
                out.append({
                    "strategy": "anchored_vwap_reversal",
                    "symbol": sym,
                    "entry_ts": t["entry_ts"],
                    "exit_ts": t["exit_ts"],
                    "entry_price": ep,
                    "initial_sl": sl,
                    "R": R,
                })
    return out


def _gather_engulfing_trades() -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df.empty:
            continue
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **kw): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=INITIAL_CAPITAL,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=prov,
        )
        if hasattr(r, "trades") and r.trades is not None and len(r.trades) > 0:
            for _, t in r.trades.iterrows():
                ep = float(t.get("entry_price", 0.0))
                sl = float(t.get("initial_sl", 0.0))
                R = float(t.get("realized_r_multiple", 0.0))
                out.append({
                    "strategy": "engulfing_continuation",
                    "symbol": sym,
                    "entry_ts": t["entry_ts"],
                    "exit_ts": t["exit_ts"],
                    "entry_price": ep,
                    "initial_sl": sl,
                    "R": R,
                })
    return out


def replay_portfolio(trades: list[dict]) -> dict:
    """Kronoloik siralama ile cagri bazinda portfoy replay."""
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    open_positions: list[dict[str, Any]] = []
    n_taken = 0
    n_skip_concurrent = 0
    n_skip_cash = 0
    fee_rt = 0.0015
    slip_rt = 0.001
    total_fees = 0.0
    total_slip = 0.0
    by_strategy: dict[str, dict] = {}
    # R serisi — korelasyon hesabi icin
    r_avwap: list[float] = []
    r_engulf: list[float] = []

    def close_due(now):
        nonlocal cash, equity, total_fees, total_slip
        still = []
        for p in open_positions:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                fees_cost = p["notional"] * fee_rt
                slip_cost = p["notional"] * slip_rt
                cash += p["notional"] + pnl
                total_fees += fees_cost
                total_slip += slip_cost
                strat = p["strategy"]
                by_strategy.setdefault(strat, {"n": 0, "pnl": 0.0})
                by_strategy[strat]["n"] += 1
                by_strategy[strat]["pnl"] += pnl
                if strat == "anchored_vwap_reversal":
                    r_avwap.append(p["R"])
                elif strat == "engulfing_continuation":
                    r_engulf.append(p["R"])
            else:
                still.append(p)
        open_positions[:] = still
        equity = cash + sum(q["notional"] for q in open_positions)

    for t in trades:
        close_due(t["entry_ts"])
        if len(open_positions) >= MAX_CONCURRENT:
            n_skip_concurrent += 1
            continue
        ep = t["entry_price"]
        sl = t["initial_sl"]
        if ep <= 0 or sl <= 0:
            continue
        sl_pct = abs(ep - sl) / ep
        if sl_pct <= 0:
            continue
        risk_d = equity * RISK_PER_TRADE
        notional = risk_d / sl_pct
        if notional > cash:
            n_skip_cash += 1
            continue
        cash -= notional
        open_positions.append({
            "exit_ts": t["exit_ts"],
            "notional": notional,
            "risk": risk_d,
            "R": t["R"],
            "strategy": t["strategy"],
        })
        n_taken += 1

    # Force close remaining
    for p in open_positions[:]:
        pnl = p["risk"] * p["R"]
        cash += p["notional"] + pnl
        equity = cash
        strat = p["strategy"]
        by_strategy.setdefault(strat, {"n": 0, "pnl": 0.0})
        by_strategy[strat]["n"] += 1
        by_strategy[strat]["pnl"] += pnl
        if strat == "anchored_vwap_reversal":
            r_avwap.append(p["R"])
        elif strat == "engulfing_continuation":
            r_engulf.append(p["R"])

    # Strateji bagimsiz R korelasyonu (approximate)
    corr = float("nan")
    min_len = min(len(r_avwap), len(r_engulf))
    if min_len >= 5:
        a = np.array(r_avwap[:min_len])
        b = np.array(r_engulf[:min_len])
        if np.std(a) > 0 and np.std(b) > 0:
            corr = float(np.corrcoef(a, b)[0, 1])

    return {
        "equity_final": equity,
        "n_taken": n_taken,
        "n_total": len(trades),
        "n_skip_concurrent": n_skip_concurrent,
        "n_skip_cash": n_skip_cash,
        "fees": total_fees,
        "slippage": total_slip,
        "by_strategy": by_strategy,
        "r_correlation": corr,
        "r_avwap_series": r_avwap,
        "r_engulf_series": r_engulf,
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    avwap_manifest = _make_avwap_manifest()

    # ---- STANDALONE BACKTEST ----
    print("=== AnchoredVWAP Reversal Backtest — 10 sembol x 1d x 3y ===\n")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 82)

    results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one_symbol_avwap(sym, avwap_manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
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
    print("\n" + "=" * 75)
    print("AVWAP STANDALONE — PORTFOLIO AGREGATE (equal-weight)")
    print("=" * 75)
    if valid:
        n_trades = sum(r["n_trades"] for r in valid)
        avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades)
        net_pnl = sum(r["net_pnl"] for r in valid)
        starting_equity = INITIAL_CAPITAL * len(valid)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
        avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
        avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
        annual = (((1 + total_return) ** (1 / 3)) - 1) * 100

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(SYMBOLS)}")
        print(f"  Toplam trade           : {n_trades}")
        print(f"  Aggregate win rate     : {avg_win*100:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual:+.1f}%")
        print(f"  Avg MaxDD              : {avg_dd*100:.1f}%")
        print(f"  Avg Sharpe             : {avg_sharpe:.2f}")
        print(f"  Avg CAGR               : {avg_cagr*100:.1f}%")
        print(f"  Avg Profit Factor      : {avg_pf:.2f}")

        # Yearly breakdown
        print("\n--- YILLIK DAGILIM ---")
        year_totals: dict[int, dict] = {}
        for r in valid:
            for yr, yd in r.get("yearly", {}).items():
                if yr not in year_totals:
                    year_totals[yr] = {"n_trades": 0, "symbols": 0}
                year_totals[yr]["n_trades"] += yd["n_trades"]
                year_totals[yr]["symbols"] += 1
        for yr in sorted(year_totals):
            yt = year_totals[yr]
            print(f"  {yr}: trades={yt['n_trades']:>3}, symbols={yt['symbols']:>2}")

        # Gate check
        print("\n--- STANDALONE GATE KARSILASTIRMA ---")
        gates = [
            ("Sharpe > 0.8          ", avg_sharpe, 0.8, ">="),
            ("MaxDD < 35%           ", avg_dd * 100, 35.0, "<="),
            ("Win rate > 50%        ", avg_win * 100, 50.0, ">="),
            ("Toplam trades > 30    ", float(n_trades), 30.0, ">="),
        ]
        all_pass = True
        for label, value, target, op in gates:
            ok = (value >= target) if op == ">=" else (value <= target)
            status = "[PASS]" if ok else "[FAIL]"
            all_pass = all_pass and ok
            print(f"  {label} actual={value:>7.2f}  target={target:>5.1f}  {status}")

        avwap_standalone = {
            "annual_pct": annual,
            "avg_dd": avg_dd * 100,
            "avg_sharpe": avg_sharpe,
            "n_trades": n_trades,
            "avg_win": avg_win * 100,
        }
    else:
        print("  Hicbir sembolde trade yok.")
        avwap_standalone = {}

    # ---- COMBINED PORTFOLIO ----
    print("\n" + "=" * 75)
    print("COMBINED PORTFOLIO TEST (engulfing + avwap, $10K paylasik kapital)")
    print("=" * 75)

    print("\nLoading engulfing trades...")
    eng_trades = []
    try:
        eng_trades = _gather_engulfing_trades()
        print(f"  {len(eng_trades)} trade yüklendi")
    except Exception as exc:
        print(f"  HATA: {exc}")

    print("Loading avwap trades from replay...")
    avwap_trades = []
    try:
        avwap_trades = _gather_avwap_trades(avwap_manifest)
        print(f"  {len(avwap_trades)} trade yüklendi")
    except Exception as exc:
        print(f"  HATA: {exc}")

    # Senaryo 1: sadece engulfing
    if eng_trades:
        r_eng_solo = replay_portfolio(eng_trades)
        eng_3y_pct = (r_eng_solo["equity_final"] / INITIAL_CAPITAL - 1) * 100
        eng_annual = ((r_eng_solo["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo 1: SADECE engulfing_continuation ---")
        print(f"  $10K -> ${r_eng_solo['equity_final']:,.0f}  "
              f"({eng_3y_pct:+.1f}% 3y, {eng_annual:+.1f}% yillik)")
        print(f"  Acilan: {r_eng_solo['n_taken']}/{r_eng_solo['n_total']}")
    else:
        eng_annual = float("nan")
        print("\n--- Senaryo 1: Engulfing trade yok ---")

    # Senaryo 2: sadece avwap
    if avwap_trades:
        r_avwap_solo = replay_portfolio(avwap_trades)
        avwap_3y_pct = (r_avwap_solo["equity_final"] / INITIAL_CAPITAL - 1) * 100
        avwap_annual = ((r_avwap_solo["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo 2: SADECE anchored_vwap_reversal ---")
        print(f"  $10K -> ${r_avwap_solo['equity_final']:,.0f}  "
              f"({avwap_3y_pct:+.1f}% 3y, {avwap_annual:+.1f}% yillik)")
        print(f"  Acilan: {r_avwap_solo['n_taken']}/{r_avwap_solo['n_total']}")
    else:
        avwap_annual = float("nan")
        print("\n--- Senaryo 2: AVWAP trade yok ---")

    # Senaryo 3: kombine
    combined_trades = eng_trades + avwap_trades
    if combined_trades:
        r_comb = replay_portfolio(combined_trades)
        comb_3y_pct = (r_comb["equity_final"] / INITIAL_CAPITAL - 1) * 100
        comb_annual = ((r_comb["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo 3: KOMBINE (engulfing + avwap, FIFO) ---")
        print(f"  $10K -> ${r_comb['equity_final']:,.0f}  "
              f"({comb_3y_pct:+.1f}% 3y, {comb_annual:+.1f}% yillik)")
        print(f"  Acilan: {r_comb['n_taken']}/{r_comb['n_total']}, "
              f"skip-concurrent={r_comb['n_skip_concurrent']}, skip-cash={r_comb['n_skip_cash']}")
        print(f"  Strateji bazinda:")
        for st, s in r_comb["by_strategy"].items():
            print(f"    {st:<30} closed={s['n']:>3} pnl=${s['pnl']:>+8,.2f}")
        if not np.isnan(r_comb["r_correlation"]):
            print(f"  R-multiple korelasyonu (avwap vs engulfing): {r_comb['r_correlation']:.3f}")
            corr_note = "DUSUK (dekorelasyon kaniti)" if abs(r_comb["r_correlation"]) < 0.5 else "YUKSEK (dikkat)"
            print(f"  Yorum: {corr_note}")

        # Delta vs engulfing alone
        if not np.isnan(eng_annual):
            delta_annual = comb_annual - eng_annual
            print(f"\n--- DELTA (kombine vs sadece engulfing) ---")
            print(f"  Yillik delta  : {delta_annual:+.2f}%")
    else:
        comb_annual = float("nan")
        r_comb = {}
        print("\n--- Senaryo 3: Trade yok ---")

    # ---- KARSILASTIRMA TABLOSU ----
    print("\n" + "=" * 75)
    print("KARSILASTIRMA OZETI")
    print("=" * 75)
    if avwap_standalone:
        print(f"  AVWAP standalone:")
        print(f"    Sharpe   : {avwap_standalone['avg_sharpe']:.2f}")
        print(f"    MaxDD    : {avwap_standalone['avg_dd']:.1f}%")
        print(f"    Yillik   : {avwap_standalone['annual_pct']:.1f}%")
        print(f"    Win rate : {avwap_standalone['avg_win']:.1f}%")
        print(f"    Trades   : {avwap_standalone['n_trades']}")

    # VERDICT
    print("\n" + "=" * 75)
    print("VERDICT")
    print("=" * 75)
    if avwap_standalone:
        sh = avwap_standalone["avg_sharpe"]
        dd = avwap_standalone["avg_dd"]
        wr = avwap_standalone["avg_win"]
        nt = avwap_standalone["n_trades"]
        corr_val = r_comb.get("r_correlation", float("nan")) if r_comb else float("nan")

        gates_pass = (
            sh >= 0.8 and
            dd <= 35.0 and
            wr >= 50.0 and
            nt >= 30
        )
        corr_ok = (not np.isnan(corr_val)) and abs(corr_val) < 0.5

        if gates_pass and corr_ok and not np.isnan(comb_annual) and not np.isnan(eng_annual) and comb_annual > eng_annual:
            verdict = "PROMOTE — gates gecildi, dekorelasyon kaniti mevcut, portfoy degerini artiriyor"
        elif gates_pass:
            verdict = "SUPPLEMENT — gates gecildi ama dekorelasyon veya portfoy avantaji sinirli"
        else:
            verdict = "REJECT — gates basarisiz"

        print(f"  {verdict}")
        print(f"\n  Kritik degerlendirme:")
        print(f"  - AVWAP edge gercek mi? Kripto mean-reversion trend-dominant "
              f"rejimde katastrofik calisabilir (Kaufman uyarisi).")
        print(f"  - POC + AVWAP confluence sinyal sayisini azaltiyor (daha az trade), "
              f"bu beraberinde istatistiksel guvenilirlik sorusunu getirir.")
        print(f"  - Backtest survivorship bias tasiyor (top-10, delisted yok).")
        corr_str = f"{corr_val:.3f}" if not np.isnan(corr_val) else "N/A"
        corr_label = "dekorelasyon kaniti mevcut" if corr_ok else "dekorelasyon yetersiz"
        print(f"  - Corr={corr_str} — {corr_label}.")

    # ---- SAVE REPORT ----
    report_path = (
        ROOT / "reports" / "backtests" /
        f"avwap_reversal_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "standalone": results,
        "combined_equity": {
            "engulfing_solo": getattr(locals().get("r_eng_solo", {}), "get", lambda k, d: d)("equity_final", None),
            "avwap_solo": getattr(locals().get("r_avwap_solo", {}), "get", lambda k, d: d)("equity_final", None),
        }
    }
    report_path.write_text(
        json.dumps(report_data, default=str, indent=2), encoding="utf-8"
    )
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
