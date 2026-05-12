"""Three White Soldiers / Three Black Crows — 3-yil backtest.

10 USDT sembolu x 1d x ~1095 bar.
Engulfing_continuation ile dekorelasyon analizi dahil.

Calistirma:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/run_3ws_backtest.py
"""
from __future__ import annotations

import sys
import traceback
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
# Single symbol backtest — Three White Soldiers
# =====================================================================

def _run_one_symbol_3ws(
    symbol: str,
    manifest,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.three_white_soldiers import ThreeWhiteSoldiersStrategy

    df = _load_symbol_ohlcv(symbol, tf="1d")
    if df.empty:
        return {"symbol": symbol, "error": "no data"}

    strategy = ThreeWhiteSoldiersStrategy(manifest)
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

    # Pattern breakdown
    n_tws = sum(1 for s in signals if s.direction == "long")
    n_tbc = sum(1 for s in signals if s.direction == "short")

    # Yearly breakdown
    yearly: dict[int, dict] = {}
    if hasattr(result, "trades") and result.trades is not None and len(result.trades) > 0:
        trades_df = result.trades.copy()
        if "exit_ts" in trades_df.columns:
            trades_df["year"] = pd.to_datetime(trades_df["exit_ts"]).dt.year
            for yr, grp in trades_df.groupby("year"):
                yearly[int(yr)] = {
                    "n_trades": len(grp),
                    "win_rate": float(
                        (grp["realized_r_multiple"] > 0).mean()
                    ) if len(grp) > 0 else 0.0,
                }

    return {
        "symbol": symbol,
        "n_bars": len(df),
        "first_ts": str(df["ts"].iloc[0].date()),
        "last_ts": str(df["ts"].iloc[-1].date()),
        "n_signals": len(signals),
        "n_tws_long": n_tws,
        "n_tbc_short": n_tbc,
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
# Trade gatherers for correlation analysis
# =====================================================================

def _gather_3ws_trades(manifest) -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.three_white_soldiers import ThreeWhiteSoldiersStrategy

    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        if df.empty:
            continue
        s = ThreeWhiteSoldiersStrategy(manifest)
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
                    "strategy": "three_white_soldiers",
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
        EngulfingContinuationStrategy,
        _default_manifest as engulf_manifest,
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


# =====================================================================
# Portfolio replay (shared capital)
# =====================================================================

def replay_portfolio(trades: list[dict]) -> dict:
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
    r_3ws: list[float] = []
    r_eng: list[float] = []

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
                if strat == "three_white_soldiers":
                    r_3ws.append(p["R"])
                elif strat == "engulfing_continuation":
                    r_eng.append(p["R"])
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
    for p in open_positions:
        pnl = p["risk"] * p["R"]
        cash += p["notional"] + pnl
        equity = cash
        strat = p["strategy"]
        by_strategy.setdefault(strat, {"n": 0, "pnl": 0.0})
        by_strategy[strat]["n"] += 1
        by_strategy[strat]["pnl"] += pnl
        if strat == "three_white_soldiers":
            r_3ws.append(p["R"])
        elif strat == "engulfing_continuation":
            r_eng.append(p["R"])

    # R-multiple correlation
    corr = float("nan")
    min_len = min(len(r_3ws), len(r_eng))
    if min_len >= 5:
        a = np.array(r_3ws[:min_len])
        b = np.array(r_eng[:min_len])
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
        "r_3ws_series": r_3ws,
        "r_eng_series": r_eng,
    }


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    from price_action.strategies.three_white_soldiers import _default_manifest

    manifest = _default_manifest()

    print("=" * 80)
    print("THREE WHITE SOLDIERS / THREE BLACK CROWS — 10 sembol x 1d x 3y")
    print("Bulkowski rank 3/103 | %82 continuation rate")
    print("=" * 80)
    print()
    print(f"  {'SYMBOL':<10} {'BARS':>4} {'SIGS':>4} {'TWS':>4} {'TBC':>4} "
          f"{'TRD':>4} {'WIN%':>6} {'PF':>5} {'DD%':>5} "
          f"{'SHR':>6} {'CAGR%':>7} {'netP&L':>9} {'s':>5}")
    print("  " + "-" * 95)

    results: list[dict] = []
    for sym in SYMBOLS:
        try:
            r = _run_one_symbol_3ws(sym, manifest)
            results.append(r)
            if "error" in r:
                print(f"  {sym:<10} FAIL: {r['error']}")
            else:
                print(
                    f"  {sym:<10} {r['n_bars']:>4} {r['n_signals']:>4} "
                    f"{r['n_tws_long']:>4} {r['n_tbc_short']:>4} "
                    f"{r['n_trades']:>4} {r['win_rate']*100:>6.1f} "
                    f"{r['profit_factor']:>5.2f} {r['max_drawdown']*100:>5.1f} "
                    f"{r['sharpe']:>6.2f} {r['cagr']*100:>7.1f} "
                    f"{r['net_pnl']:>+9.0f} {r['elapsed_sec']:>5.1f}"
                )
        except Exception as exc:
            print(f"  {sym:<10} EXCEPTION: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results.append({"symbol": sym, "error": str(exc)})

    # ---- Aggregate ----
    valid = [r for r in results if "error" not in r and r.get("n_trades", 0) > 0]
    print("\n" + "=" * 80)
    print("3WS STANDALONE — PORTFOLIO AGGREGATE (equal-weight)")
    print("=" * 80)

    annual_pct = float("nan")
    avg_win_pct = float("nan")
    avg_dd = float("nan")
    avg_sharpe = float("nan")
    n_trades_total = 0

    if valid:
        n_trades_total = sum(r["n_trades"] for r in valid)
        avg_win = sum(r["win_rate"] * r["n_trades"] for r in valid) / max(1, n_trades_total)
        avg_win_pct = avg_win * 100
        net_pnl = sum(r["net_pnl"] for r in valid)
        starting_equity = INITIAL_CAPITAL * len(valid)
        total_return = net_pnl / starting_equity
        avg_dd = sum(r["max_drawdown"] for r in valid) / len(valid)
        avg_sharpe = sum(r["sharpe"] for r in valid) / len(valid)
        avg_cagr = sum(r["cagr"] for r in valid) / len(valid)
        avg_pf = sum(r["profit_factor"] for r in valid) / len(valid)
        annual_pct = (((1 + total_return) ** (1 / 3)) - 1) * 100

        print(f"  Sembol sayisi (gecen)  : {len(valid)}/{len(SYMBOLS)}")
        print(f"  Toplam trade           : {n_trades_total}")
        print(f"  TWS long sinyaller     : {sum(r.get('n_tws_long', 0) for r in valid)}")
        print(f"  TBC short sinyaller    : {sum(r.get('n_tbc_short', 0) for r in valid)}")
        print(f"  Aggregate win rate     : {avg_win_pct:.1f}%")
        print(f"  Aggregate net P&L      : ${net_pnl:+,.0f}")
        print(f"  Aggregate net return   : {total_return*100:+.1f}% (3y, equal-weight)")
        print(f"  Yillik (annualized)    : {annual_pct:+.1f}%")
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
                    year_totals[yr] = {"n_trades": 0, "win_rates": []}
                year_totals[yr]["n_trades"] += yd["n_trades"]
                if yd["n_trades"] > 0:
                    year_totals[yr]["win_rates"].append(yd["win_rate"])
        for yr in sorted(year_totals):
            yt = year_totals[yr]
            wr_list = yt["win_rates"]
            avg_wr = sum(wr_list) / len(wr_list) if wr_list else 0.0
            print(f"  {yr}: trades={yt['n_trades']:>3}, avg_win={avg_wr*100:.1f}%")
    else:
        print("  Hicbir sembolde trade yok — pattern cok nadir veya data eksik.")

    # ---- Gate check ----
    print("\n--- 3WS STANDALONE GATE KARSILASTIRMA ---")
    gates = [
        ("Sharpe > 0.5          ", avg_sharpe, 0.5, ">="),
        ("MaxDD < 40%           ", avg_dd * 100 if not np.isnan(avg_dd) else 999, 40.0, "<="),
        ("Win rate > 45%        ", avg_win_pct, 45.0, ">="),
        ("Toplam trades > 20    ", float(n_trades_total), 20.0, ">="),
    ]
    all_pass = True
    for label, value, target, op in gates:
        if np.isnan(value):
            print(f"  {label} actual=     NaN  target={target:>5.1f}  [FAIL]")
            all_pass = False
            continue
        ok = (value >= target) if op == ">=" else (value <= target)
        status = "[PASS]" if ok else "[FAIL]"
        all_pass = all_pass and ok
        print(f"  {label} actual={value:>7.2f}  target={target:>5.1f}  {status}")

    # ---- Decorrelation vs Engulfing ----
    print("\n" + "=" * 80)
    print("DEKORELASYON ANALIZi — 3WS vs Engulfing Continuation")
    print("=" * 80)

    tws_trades = []
    eng_trades = []
    try:
        print("  3WS trade'leri toplanıyor...")
        tws_trades = _gather_3ws_trades(manifest)
        print(f"  {len(tws_trades)} 3WS trade yüklendi")
    except Exception as exc:
        print(f"  3WS HATA: {exc}")

    try:
        print("  Engulfing trade'leri toplanıyor...")
        eng_trades = _gather_engulfing_trades()
        print(f"  {len(eng_trades)} Engulfing trade yüklendi")
    except Exception as exc:
        print(f"  Engulfing HATA: {exc}")

    # Senaryo 1: Sadece 3WS
    if tws_trades:
        r_solo = replay_portfolio(tws_trades)
        solo_3y = (r_solo["equity_final"] / INITIAL_CAPITAL - 1) * 100
        solo_ann = ((r_solo["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo A: SADECE three_white_soldiers ---")
        print(f"  $10K -> ${r_solo['equity_final']:,.0f}  "
              f"({solo_3y:+.1f}% 3y, {solo_ann:+.1f}% yillik)")
        print(f"  Acilan: {r_solo['n_taken']}/{r_solo['n_total']}")

    # Senaryo 2: Sadece Engulfing
    if eng_trades:
        r_eng = replay_portfolio(eng_trades)
        eng_3y = (r_eng["equity_final"] / INITIAL_CAPITAL - 1) * 100
        eng_ann = ((r_eng["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo B: SADECE engulfing_continuation ---")
        print(f"  $10K -> ${r_eng['equity_final']:,.0f}  "
              f"({eng_3y:+.1f}% 3y, {eng_ann:+.1f}% yillik)")
        print(f"  Acilan: {r_eng['n_taken']}/{r_eng['n_total']}")

    # Senaryo 3: Kombine
    combined = tws_trades + eng_trades
    if combined:
        r_comb = replay_portfolio(combined)
        comb_3y = (r_comb["equity_final"] / INITIAL_CAPITAL - 1) * 100
        comb_ann = ((r_comb["equity_final"] / INITIAL_CAPITAL) ** (1 / 3) - 1) * 100
        print(f"\n--- Senaryo C: KOMBINE (3WS + engulfing, paylasik kapital) ---")
        print(f"  $10K -> ${r_comb['equity_final']:,.0f}  "
              f"({comb_3y:+.1f}% 3y, {comb_ann:+.1f}% yillik)")
        print(f"  Acilan: {r_comb['n_taken']}/{r_comb['n_total']}, "
              f"skip-concurrent={r_comb['n_skip_concurrent']}, "
              f"skip-cash={r_comb['n_skip_cash']}")
        print("  Strateji bazinda:")
        for st, s in r_comb["by_strategy"].items():
            print(f"    {st:<35} closed={s['n']:>3} pnl=${s['pnl']:>+8,.2f}")

        if not np.isnan(r_comb["r_correlation"]):
            corr_val = r_comb["r_correlation"]
            print(f"\n  R-multiple korelasyonu (3WS vs engulfing): {corr_val:.3f}")
            if abs(corr_val) < 0.30:
                corr_note = "DUSUK — iyi dekorelasyon, portfoy diversifikasyonu sagliyor"
            elif abs(corr_val) < 0.60:
                corr_note = "ORTA — kısmi dekorelasyon"
            else:
                corr_note = "YUKSEK — dikkat, piyasa riski paylasiyor"
            print(f"  Not: {corr_note}")
        else:
            print("  R korelasyonu: yeterli ortak bar yok (her iki stratejide de az trade)")

    # ---- VERDICT ----
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    if not np.isnan(avg_sharpe) and not np.isnan(avg_dd) and not np.isnan(avg_win_pct):
        if avg_sharpe >= 0.8 and avg_dd <= 0.35 and avg_win_pct >= 50.0 and n_trades_total >= 30:
            verdict = "PROMOTE — Tum gate'ler gecti. Portfoy entegrasyonuna hazir."
        elif avg_sharpe >= 0.5 and avg_dd <= 0.45 and n_trades_total >= 15:
            verdict = "DEFER — Sonuclar umut verici ama henuz promote esiginde degil. Walk-forward test onerilir."
        else:
            verdict = "REJECT — Yeterli performance yok. Pattern crypto 1d'de istenen sonucu vermiyor."
    else:
        verdict = "REJECT — Yeterli trade yok. Pattern cok nadir veya data eksik."

    print(f"  {verdict}")
    print()
    print("  Bulkowski referansi : %82 continuation rate (hisse senedi 1d)")
    print("  Bu backtest         : Crypto 1d — sonuclar yukarida")
    print("  Dekorelasyon        : Engulfing ile farkli mekanizma (3-bar vs 2-bar)")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
