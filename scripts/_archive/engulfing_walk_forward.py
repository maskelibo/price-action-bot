"""Engulfing strategy walk-forward DSR test.

3 yıllık veriyi 6 pencere × 6 ay halinde böl. Her pencerede:
- Tek $10K hesapla replay
- Final equity, Sharpe, win rate, trade count
Walk-forward σ ve DSR (López) yaklaşık hesabı.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


def main():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv

    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
               "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]

    # Tüm trade'leri topla
    print("Tüm engulfing trade'lerini topluyor...")
    manifest = engulf_manifest()
    all_trades = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            all_trades.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
            })
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam: {len(all_trades)} trade")

    # 6 pencere × 6 ay
    if not all_trades:
        return
    start_dt = all_trades[0]["entry_ts"]
    end_dt = all_trades[-1]["exit_ts"]
    total_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    n_windows = 6
    months_per = max(1, total_months // n_windows)
    print(f"Toplam ay: {total_months}, pencere/ay: {months_per}")

    # Replay each window with $10K isolated
    results = []
    import datetime as dt
    for i in range(n_windows):
        win_start = start_dt + dt.timedelta(days=30 * months_per * i)
        win_end = start_dt + dt.timedelta(days=30 * months_per * (i + 1))
        win_trades = [t for t in all_trades if win_start <= t["entry_ts"] < win_end]
        if not win_trades:
            results.append({"i": i, "trades": 0, "final": 10000.0, "Rs": []})
            continue

        # Tek hesap replay (max 5 concurrent, 1% risk)
        equity = 10_000.0
        cash = 10_000.0
        open_pos = []
        n_taken = 0
        Rs = []
        for t in win_trades:
            # Close due
            still = []
            for p in open_pos:
                if p["exit_ts"] <= t["entry_ts"]:
                    pnl = p["risk"] * p["R"]
                    cash += p["notional"] + pnl
                    equity = cash + sum(q["notional"] for q in still)
                    Rs.append(p["R"])
                else:
                    still.append(p)
            open_pos = still
            if len(open_pos) >= 5:
                continue
            sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
            if sl_pct <= 0:
                continue
            risk_d = equity * 0.01
            notional = risk_d / sl_pct
            if notional > cash:
                continue
            cash -= notional
            open_pos.append({"exit_ts": t["exit_ts"], "notional": notional, "risk": risk_d, "R": t["R"]})
            n_taken += 1
        # Force close
        for p in open_pos:
            cash += p["notional"] + p["risk"] * p["R"]
            equity = cash
            Rs.append(p["R"])
        ret = (equity / 10000 - 1)
        results.append({"i": i+1, "trades": n_taken, "final": equity, "return": ret, "Rs": Rs})

    print(f"\n{'Pencere':<10} {'trades':>7} {'final$':>10} {'return%':>9} {'win%':>6} {'avgR':>7}")
    print("-"*55)
    rets = []
    for r in results:
        if r["trades"] == 0:
            print(f"  {r['i']:<8} {0:>7} {10000:>10,.0f} {0:>+8.1f}% {'-':>6} {'-':>7}")
            continue
        wr = sum(1 for x in r["Rs"] if x > 0) / len(r["Rs"]) if r["Rs"] else 0
        avgR = sum(r["Rs"])/len(r["Rs"]) if r["Rs"] else 0
        print(f"  {r['i']:<8} {r['trades']:>7} {r['final']:>10,.0f} {r['return']*100:>+8.1f}% {wr*100:>5.1f}% {avgR:>+7.2f}")
        rets.append(r["return"])

    if rets:
        avg_ret = sum(rets)/len(rets)
        std_ret = (sum((x-avg_ret)**2 for x in rets) / len(rets)) ** 0.5
        # Annualized assuming each window is ~6 months
        sharpe_wf = (avg_ret / std_ret) * math.sqrt(2) if std_ret > 0 else 0  # 2 windows/year
        positive_pct = sum(1 for x in rets if x > 0) / len(rets)
        print(f"\n--- Walk-Forward Stats ---")
        print(f"  Pencere getiri ortalaması : {avg_ret*100:+.2f}% / pencere")
        print(f"  Pencere getiri σ          : {std_ret*100:.2f}%")
        print(f"  Walk-forward Sharpe       : {sharpe_wf:.2f}")
        print(f"  Pozitif pencere oranı     : {positive_pct*100:.0f}% ({sum(1 for x in rets if x > 0)}/{len(rets)})")
        print(f"  GATE: pozitif oran > %66  : {'[PASS]' if positive_pct > 0.66 else '[FAIL]'}")

        # DSR yaklaşık (López formülü, basit haliyle)
        # SR_obs annualized
        sr_obs = (avg_ret / std_ret) * math.sqrt(2) if std_ret > 0 else 0
        n = len(rets)
        # E[SR_max] for N=1 trial = ~0 (no multiple testing); for higher N it grows
        # Bu run'da N_trials = N_windows = 6 (her pencere bir trial)
        N_trials = n
        if N_trials > 1:
            # Approximation: gamma(Euler-Mascheroni) = 0.5772
            E_sr_max = (1 - 0.5772) / math.sqrt(n) + math.sqrt(2 * math.log(N_trials)) / math.sqrt(n)
        else:
            E_sr_max = 0
        dsr = sr_obs - E_sr_max
        print(f"  DSR (López, ~)            : {dsr:.2f}")
        print(f"  GATE: DSR > 0.6           : {'[PASS]' if dsr > 0.6 else '[FAIL]'}")


if __name__ == "__main__":
    main()
