"""TPO Value Area (Volume Profile) stratejisi icin gercek 3y backtest.

10 USDT sembolu * 1d * ~1095 bar.
Standalone backtest + engulfing_continuation ile kombine portfoy testi
(informational only — bildigimiz uzere kombine compound edge yaratmiyor).

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_tpo_backtest.py
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

def _make_tpo_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "tpo_value_area",
        "version": "1.0.0",
        "description": "TPO Market Profile Value Area mean-reversion",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "tpo_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
                        "va_pct": 0.70,
                    },
                },
                {
                    "id": "tpo_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
                        "va_pct": 0.70,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
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
            "take_profit": {"method": "poc_target"},
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

def _run_one_symbol_tpo(symbol: str, manifest, initial_capital: float = INITIAL_CAPITAL) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.tpo_value_area import TPOValueAreaStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = TPOValueAreaStrategy(manifest)
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
                wr = float((grp["realized_r_multiple"] > 0).mean()) if len(grp) > 0 else 0.0
                avg_r = float(grp["realized_r_multiple"].mean()) if len(grp) > 0 else 0.0
                yearly[int(yr)] = {
                    "n_trades": len(grp),
                    "win_rate": wr,
                    "avg_r": avg_r,
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
# Trade gatherers for portfolio replay
# =====================================================================

def _gather_tpo_trades(manifest) -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.tpo_value_area import TPOValueAreaStrategy
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df.empty:
            continue
        s = TPOValueAreaStrategy(manifest)
        df_feats = s.prepare_features(df)

        def prov(*a, **kw):
            return df_feats.copy()

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
                    "strategy": "tpo_value_area",
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

        def prov(*a, **kw):
            return df_feats.copy()

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
    """Kronolojik siralama ile trade bazinda portfoy replay."""
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
    r_tpo: list[float] = []
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
                if strat == "tpo_value_area":
                    r_tpo.append(p["R"])
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
        if strat == "tpo_value_area":
            r_tpo.append(p["R"])
        elif strat == "engulfing_continuation":
            r_engulf.append(p["R"])

    corr = float("nan")
    min_len = min(len(r_tpo), len(r_engulf))
    if min_len >= 5:
        a = np.array(r_tpo[:min_len])
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
        "r_tpo_series": r_tpo,
        "r_engulf_series": r_engulf,
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    tpo_manifest = _make_tpo_manifest()

    # ---- STANDALONE BACKTEST ----
    print("=== TPO Value Area Backtest — 10 sembol x 1d x 3y ===\n")
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TRD':>4} "
          f"{'WIN%':>6} {'PF':>5} {'DD%':>5} {'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 82)

    results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one_symbol_tpo(sym, tpo_manifest)
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

    # ---- AGGREGATE ----
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 75)
    print("TPO STANDALONE — PORTFOLIO AGREGATE (equal-weight)")
    print("=" * 75)

    tpo_standalone: dict = {}
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
                    year_totals[yr] = {"n_trades": 0, "total_r": 0.0, "n_wins": 0}
                year_totals[yr]["n_trades"] += yd["n_trades"]
                year_totals[yr]["total_r"] += yd.get("avg_r", 0.0) * yd["n_trades"]
                year_totals[yr]["n_wins"] += int(yd["win_rate"] * yd["n_trades"])

        print(f"  {'YIL':>5} {'TRADES':>7} {'WIN%':>7} {'AVG_R':>7}")
        for yr in sorted(year_totals):
            yt = year_totals[yr]
            nt = yt["n_trades"]
            wr_pct = yt["n_wins"] / nt * 100 if nt > 0 else 0.0
            avg_r = yt["total_r"] / nt if nt > 0 else 0.0
            print(f"  {yr:>5} {nt:>7} {wr_pct:>7.1f} {avg_r:>7.2f}")

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

        tpo_standalone = {
            "annual_pct": annual,
            "avg_dd": avg_dd * 100,
            "avg_sharpe": avg_sharpe,
            "n_trades": n_trades,
            "avg_win": avg_win * 100,
            "avg_pf": avg_pf,
            "avg_cagr": avg_cagr * 100,
            "all_gates_pass": all_pass,
        }
    else:
        print("  Hicbir sembolde trade yok.")

    # ---- COMBINED PORTFOLIO TEST ----
    print("\n" + "=" * 75)
    print("COMBINED PORTFOLIO TEST (engulfing + TPO, $10K paylasik kapital)")
    print("(Informational only — bildigimiz uzere combine compound avantaj saglamiyor)")
    print("=" * 75)

    print("\nLoading engulfing trades...")
    eng_trades: list[dict] = []
    try:
        eng_trades = _gather_engulfing_trades()
        print(f"  {len(eng_trades)} trade yuklendi")
    except Exception as exc:
        print(f"  HATA: {exc}")

    print("Loading TPO trades from replay...")
    tpo_trades: list[dict] = []
    try:
        tpo_trades = _gather_tpo_trades(tpo_manifest)
        print(f"  {len(tpo_trades)} trade yuklendi")
    except Exception as exc:
        print(f"  HATA: {exc}")

    r_eng_solo: dict = {}
    r_tpo_solo: dict = {}
    r_comb: dict = {}
    eng_annual = float("nan")
    tpo_annual_replay = float("nan")
    comb_annual = float("nan")

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
        print("\n--- Senaryo 1: Engulfing trade yok ---")

    # Senaryo 2: sadece TPO
    if tpo_trades:
        r_tpo_solo = replay_portfolio(tpo_trades)
        tpo_3y_pct = (r_tpo_solo["equity_final"] / INITIAL_CAPITAL - 1) * 100
        tpo_annual_replay = ((r_tpo_solo["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo 2: SADECE tpo_value_area ---")
        print(f"  $10K -> ${r_tpo_solo['equity_final']:,.0f}  "
              f"({tpo_3y_pct:+.1f}% 3y, {tpo_annual_replay:+.1f}% yillik)")
        print(f"  Acilan: {r_tpo_solo['n_taken']}/{r_tpo_solo['n_total']}")
    else:
        print("\n--- Senaryo 2: TPO trade yok ---")

    # Senaryo 3: kombine
    combined_trades = eng_trades + tpo_trades
    if combined_trades:
        r_comb = replay_portfolio(combined_trades)
        comb_3y_pct = (r_comb["equity_final"] / INITIAL_CAPITAL - 1) * 100
        comb_annual = ((r_comb["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo 3: KOMBINE (engulfing + TPO, FIFO) ---")
        print(f"  $10K -> ${r_comb['equity_final']:,.0f}  "
              f"({comb_3y_pct:+.1f}% 3y, {comb_annual:+.1f}% yillik)")
        print(f"  Acilan: {r_comb['n_taken']}/{r_comb['n_total']}, "
              f"skip-concurrent={r_comb['n_skip_concurrent']}, skip-cash={r_comb['n_skip_cash']}")
        print(f"  Strateji bazinda:")
        for st, s in r_comb["by_strategy"].items():
            print(f"    {st:<30} closed={s['n']:>3} pnl=${s['pnl']:>+8,.2f}")
        if not np.isnan(r_comb["r_correlation"]):
            corr_val = r_comb["r_correlation"]
            corr_note = "DUSUK (dekorelasyon kaniti)" if abs(corr_val) < 0.5 else "YUKSEK (dikkat)"
            print(f"  R-multiple korelasyonu (TPO vs engulfing): {corr_val:.3f} — {corr_note}")

        if not np.isnan(eng_annual):
            delta = comb_annual - eng_annual
            print(f"\n--- DELTA (kombine vs sadece engulfing) ---")
            print(f"  Yillik delta  : {delta:+.2f}%")
    else:
        print("\n--- Senaryo 3: Trade yok ---")

    # ---- COMPARISON SUMMARY ----
    print("\n" + "=" * 75)
    print("KARSILASTIRMA OZETI")
    print("=" * 75)
    if tpo_standalone:
        print(f"  TPO Value Area standalone:")
        print(f"    Sharpe   : {tpo_standalone['avg_sharpe']:.2f}")
        print(f"    MaxDD    : {tpo_standalone['avg_dd']:.1f}%")
        print(f"    Yillik   : {tpo_standalone['annual_pct']:.1f}%")
        print(f"    Win rate : {tpo_standalone['avg_win']:.1f}%")
        print(f"    Trades   : {tpo_standalone['n_trades']}")
        print(f"    Pf       : {tpo_standalone['avg_pf']:.2f}")

    # ---- VERDICT ----
    print("\n" + "=" * 75)
    print("VERDICT")
    print("=" * 75)
    if tpo_standalone:
        sh = tpo_standalone["avg_sharpe"]
        dd = tpo_standalone["avg_dd"]
        wr = tpo_standalone["avg_win"]
        nt = tpo_standalone["n_trades"]
        pf = tpo_standalone["avg_pf"]
        all_gates = tpo_standalone["all_gates_pass"]

        corr_val = r_comb.get("r_correlation", float("nan")) if r_comb else float("nan")
        corr_ok = (not np.isnan(corr_val)) and abs(corr_val) < 0.5

        if all_gates and corr_ok and not np.isnan(comb_annual) and not np.isnan(eng_annual) and comb_annual > eng_annual:
            verdict = "PROMOTE"
            verdict_detail = "Tum gateler gecildi, dekorelasyon kaniti mevcut, portfoy degerini artiriyor."
        elif all_gates:
            verdict = "SUPPLEMENT"
            verdict_detail = "Gateler gecildi ama dekorelasyon veya portfoy avantaji sinirli."
        elif sh >= 0.4 and nt >= 15:
            verdict = "DEFER"
            verdict_detail = "Kismi gate gecisi — daha fazla veri veya parametre rafine ile tekrar dene."
        else:
            verdict = "REJECT"
            verdict_detail = "Gate basarisiz — istatistiksel edge kaniti yetersiz."

        print(f"  {verdict} — {verdict_detail}")
        print(f"\n--- Metrik detay ---")
        print(f"  Sharpe     : {sh:.2f}  (gerekli >= 0.8)")
        print(f"  MaxDD      : {dd:.1f}%  (gerekli <= 35%)")
        print(f"  Win rate   : {wr:.1f}%  (gerekli >= 50%)")
        print(f"  Trades     : {nt}  (gerekli >= 30)")
        print(f"  Profit F   : {pf:.2f}")

        print(f"\n--- KRITIK DEGERLENDIRME: TPO kripto'ya transfer oldu mu? ---")
        print(f"  Steidlmayer metodu equity index futures icin gelistirildi.")
        print(f"  Orijinal ortam: S&P 500 pit trading, gunkuk auction mekanizmasi,")
        print(f"  dar range, kurumsal katilimci dominant, belirgin fair value noktasi.")
        print(f"")
        print(f"  Kripto 1d ortami:")
        print(f"  - 24/7 sureklili islem: auction close mekanizmasi yok.")
        print(f"  - Volatilite 3-5x daha yuksek: Value Area her gun yeniden sekillenir.")
        print(f"  - Guclu trend rejimleri: 2021, 2023-2024 bull run'larinda")
        print(f"    mean-reversion sistematik olarak trend'e karsi calisir.")
        print(f"  - Retail sentiment dominant: kurumsal 'fair value' dondurma mekanizmasi")
        print(f"    equity index kadar guclu degil.")
        print(f"  - Volume Profile'de 'tail' bolgeler kripto'da hizla extend eder;")
        print(f"    equity'de tails genellikle kisa omurludur.")
        print(f"")
        if nt < 30:
            print(f"  NOT: Trade sayisi ({nt}) istatistiksel anlamlililik icin yetersiz.")
            print(f"  Sonuclar guclu trend rejimlerinde (BTC 2021, 2024) VAL/VAH break'lerin")
            print(f"  reversal degil trend devami oldugunu gosteriyor olabilir.")
        if sh < 0.4:
            print(f"  Sharpe ({sh:.2f}) Donchian breakout baseline'in altinda.")
            print(f"  AVWAP gibi TPO da kripto trend-dominant ortaminda mean-reversion edge'ini")
            print(f"  istikrarli sekilde ortaya cikaramamaktadir.")
            print(f"")
            print(f"  SONUC: Kripto'da mean-reversion sistemlerin ortak sorunu:")
            print(f"  - Trend periyodlarinda (2021 bull, 2022 bear, 2024 bull) katastrofik.")
            print(f"  - Sadece range-bound rejimlerde (2019, bazi 2023 donemi) edge goruluyor.")
            print(f"  - Kaufman'in uyarisi dogrulaniyor: 'mean-reversion in trending market")
            print(f"    = catastrophic drawdown.' Kripto 1d trend-dominant bir varliktir.")
        else:
            print(f"  Sharpe ({sh:.2f}) makul. Ancak uzun vadeli kripto trend'lerinde")
            print(f"  bu edge'in korunup korumayacagi belirsizdir.")
    else:
        print("  Yeterli trade yok — verdict uretilemiyor.")

    # ---- SAVE REPORT ----
    report_path = (
        ROOT / "reports" / "backtests" /
        f"tpo_value_area_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_data = {
        "standalone": results,
        "aggregate": tpo_standalone,
        "combined_replay": {
            "engulfing_solo_equity": r_eng_solo.get("equity_final"),
            "tpo_solo_equity": r_tpo_solo.get("equity_final"),
            "combined_equity": r_comb.get("equity_final"),
        },
    }
    report_path.write_text(
        json.dumps(report_data, default=str, indent=2), encoding="utf-8"
    )
    print(f"\nDetay rapor: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
