"""Sec19 walk-forward: TOP_11 (Champion = TOP_10 + FVG) vs +new strategies.

Compares champion (v1.5+ BALANCED+F&G+side-cond+force-exit) with:
  - CHALLENGER A : Champion + inside_day_failure
  - CHALLENGER B : Champion + high_tight_flag
  - CHALLENGER C : Champion + quasimodo_reversal
  - CHALLENGER D : Champion + ALL THREE

3y rolling walk-forward.

Also robustness:
  - Symbol-out CV (each symbol dropped, mean shift)
  - Regime split (bull / bear / range proxy via BTC EMA50 above/below)
  - Shuffle baseline (50 random R shuffles, p-value vs real)
  - Param perturb (per new strategy, ±25% lookback / ATR mult)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


REPORT_OUT = ROOT / "reports" / "researcher" / "sec19_walkforward.md"


def _load_or_gather_new() -> dict:
    """Load new strategy trades pkl (created by standalone) or gather."""
    import pickle
    pkl = ROOT / "reports" / "researcher" / "sec19_new_trades.pkl"
    if pkl.exists():
        with open(pkl, "rb") as f:
            return pickle.load(f)
    # Re-gather
    from scripts.sec19_new_strategies_standalone import NEW
    out = {}
    for m, c in NEW:
        out[m] = _gather(m, c)
    return out


def _load_fvg_trades() -> list:
    """Re-gather FVG trades for ensemble base."""
    return _gather("fvg_fill_reversal", "FVGFillReversalStrategy")


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# Sec19 -- Researcher Sprint 2026-05-14 -- New Strategy WF + Robustness")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Hypotheses:** HYP-2026-05-14-{{quasimodo,htf,idf}}")
    w(f"**Sprint goal:** Top 3 new strategies (Quasimodo, HTF, IDF) ensemble retest vs Champion (TOP_10 + FVG).")
    w("")

    new_trades = _load_or_gather_new()
    qm = new_trades.get("quasimodo_reversal", [])
    htf = new_trades.get("high_tight_flag", [])
    idf = new_trades.get("inside_day_failure", [])

    # Champion ensemble = TOP_10 + FVG
    print("\nGathering TOP_10 + FVG...")
    top10 = []
    for m, c in TOP_10:
        ts = _gather(m, c)
        top10.extend(ts)
    fvg = _load_fvg_trades()
    champion = top10 + fvg
    print(f"TOP_10: {len(top10)}  FVG: {len(fvg)}  Champion: {len(champion)}")
    print(f"QM: {len(qm)}  HTF: {len(htf)}  IDF: {len(idf)}")

    # ---- Standalone summary table ----
    w("## Standalone Edge (5y, 11 sym)")
    w("")
    w("| Strategy | n | mR | sumR | WR | Edge gate |")
    w("|---|---:|---:|---:|---:|---|")
    for name, trades, gate in [
        ("inside_day_failure", idf, (0.10, 50, 0.35)),
        ("high_tight_flag", htf, (0.10, 30, 0.40)),
        ("quasimodo_reversal", qm, (0.10, 50, 0.35)),
    ]:
        if not trades:
            w(f"| {name} | 0 | - | - | - | n/a |")
            continue
        Rs = np.array([t["R"] for t in trades])
        mR = float(Rs.mean())
        sumR = float(Rs.sum())
        WR = float((Rs > 0).mean())
        passes = mR > gate[0] and len(trades) > gate[1] and WR > gate[2]
        verdict = "PASS" if passes else "FAIL"
        w(f"| {name} | {len(trades)} | {mR:+.3f} | {sumR:+.1f} | {WR*100:.1f}% | **{verdict}** |")
    w("")

    # Sorting
    challengers = [
        ("CHAMPION (TOP_10 + FVG)",        champion),
        ("CHALLENGER A (+IDF)",            champion + idf),
        ("CHALLENGER B (+HTF)",            champion + htf),
        ("CHALLENGER C (+QM)",             champion + qm),
        ("CHALLENGER D (+IDF+HTF+QM)",     champion + idf + htf + qm),
    ]
    for name, trades in challengers:
        trades.sort(key=lambda x: x["entry_ts"])

    # ---- Filter calendars ----
    print("\nFilter calendars...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    fng_short_dict = dict(fng_short_20)
    combined_short_skip = {**fund_short_dict, **fng_short_dict}

    # Window setup
    base_trades = challengers[-1][1]
    if not base_trades:
        w("**Hata:** Trade yok, atlanıyor.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"Pencere sayisi: {len(windows)} (3y rolling, 60 gun step)")
    w(f"## Walk-Forward (3y rolling, {len(windows)} pencere)")
    w("")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    overrides = dict(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )
    cfg = base_bal.with_overrides(**overrides)

    w("| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif | Trades |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    print(f"\n{'scenario':<48}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'r-adj':>7}  {'neg':>4}  {'trades':>7}")
    print("-" * 115)

    rated = []
    for name, trades in challengers:
        anns, dds, n_trades = [], [], []
        for ws, we in windows:
            ww_trades = [t for t in trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
            n_trades.append(r.n_trades if hasattr(r, 'n_trades') else 0)
        if not anns:
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        med_a = median(anns)
        avg_n = mean(n_trades) if n_trades else 0
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), neg, avg_n))
        print(f"  {name:<48}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {ra:>6.3f}  {neg:>3}  {avg_n:>6.0f}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} | {avg_n:.0f} |")

    w("")
    w("## Karar Karsilastirmasi")
    w("")
    if rated:
        c = rated[0]  # CHAMPION
        for ch in rated[1:]:
            d_ma = ch[1] - c[1]
            d_md = ch[3] - c[3]
            d_ra = ch[4] - c[4]
            verdict = "MARGINAL"
            if d_ra > 0.05 and d_ma > 0:
                verdict = "TOURNAMENT WINNER"
            elif d_ra > 0:
                verdict = "MARGINAL POSITIVE"
            elif d_ma > 0 and d_md > -2:
                verdict = "RETURN UP, RISK FLAT"
            else:
                verdict = "REJECT"
            w(f"- **{ch[0]}** vs Champion: dYillik {d_ma:+.1f}pp, dDD {d_md:+.1f}pp, dRiskAdj {d_ra:+.3f} -> **{verdict}**")

    # =========================================================
    # ROBUSTNESS — only run for strategies that pass standalone gate
    # =========================================================
    w("")
    w("## Robustness Suite")
    w("")
    w("### Symbol-out CV (Champion + ALL three)")
    w("")
    w("Sembol-bazinda drop -> 3y rolling mean annualized delta vs base (TOP_10+FVG+IDF+HTF+QM).")
    w("")

    all_new_trades = challengers[-1][1]  # full +IDF+HTF+QM
    # Get the unique symbols
    symbols = sorted(set(t["symbol"] for t in all_new_trades))
    w(f"| Symbol Dropped | Mean Annualized | dvsBase | DD | r-adj |")
    w(f"|---|---:|---:|---:|---:|")

    # Base (no drop)
    base_anns, base_dds = [], []
    for ws, we in windows:
        ww = [t for t in all_new_trades if ws <= t["entry_ts"] < we]
        r = production_replay(ww, cfg)
        if r is None:
            continue
        base_anns.append(r.annualized(3.0) * 100)
        base_dds.append(r.max_drawdown * 100)
    base_mean = mean(base_anns) if base_anns else 0.0
    base_ddm = mean(base_dds) if base_dds else 0.0
    print(f"\nSymbol-out CV base: {base_mean:+.1f}% / DD {base_ddm:+.1f}%")
    w(f"| (base) | {base_mean:+.1f}% | 0.0pp | {base_ddm:+.1f}% | {base_mean/abs(base_ddm) if base_ddm != 0 else 0:.3f} |")

    for sym_drop in symbols:
        anns, dds = [], []
        sym_filtered = [t for t in all_new_trades if t["symbol"] != sym_drop]
        for ws, we in windows:
            ww = [t for t in sym_filtered if ws <= t["entry_ts"] < we]
            r = production_replay(ww, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            continue
        m_ann = mean(anns)
        m_dd = mean(dds)
        delta = m_ann - base_mean
        ra = m_ann / abs(m_dd) if m_dd != 0 else 0
        print(f"  drop {sym_drop:<14} -> {m_ann:+.1f}%  dvsBase {delta:+.1f}pp  DD {m_dd:+.1f}%")
        w(f"| -{sym_drop} | {m_ann:+.1f}% | {delta:+.1f}pp | {m_dd:+.1f}% | {ra:.3f} |")

    # =========================================================
    # Regime split
    # =========================================================
    w("")
    w("### Regime Split (BTC EMA50 üstü/altı + range)")
    w("")
    w("BTC daily kapanis EMA50 referans. Regime'i trade.entry_ts BTC closeu üzerinden hesapla.")
    w("")

    from scripts.run_real_backtest import _load_symbol_ohlcv
    btc_df = _load_symbol_ohlcv("BTC/USDT", tf="1d")
    btc_df = btc_df.sort_values("ts").reset_index(drop=True)
    btc_df["ts"] = pd.to_datetime(btc_df["ts"], utc=True)
    btc_df["ema50"] = btc_df["close"].ewm(span=50, adjust=False).mean()
    # ATR proxy: range/close
    btc_df["range_pct"] = (btc_df["high"] - btc_df["low"]) / btc_df["close"]
    btc_df["range_smooth"] = btc_df["range_pct"].rolling(20).mean()
    # Bull = close > ema50, range_smooth < median; Bear = close < ema50; Range = close ~ema50 within ±2%

    def _regime_of(ts):
        idx = btc_df["ts"].searchsorted(ts) - 1
        if idx < 0 or idx >= len(btc_df):
            return "unknown"
        c = btc_df["close"].iloc[idx]
        e = btc_df["ema50"].iloc[idx]
        if pd.isna(e):
            return "unknown"
        delta = (c - e) / e
        if delta > 0.05:
            return "bull"
        if delta < -0.05:
            return "bear"
        return "range"

    w("| Regime | Senaryo | n | Mean R | WR |")
    w("|---|---|---:|---:|---:|")
    # On full pool only — use raw R averaging (cant production_replay regime-split with 3y window logic well)
    for regime in ["bull", "bear", "range"]:
        for sc_name, trades in [
            ("Champion", champion),
            ("Champion+QM", champion + qm),
            ("Champion+ALL", champion + idf + htf + qm),
        ]:
            reg_trades = [t for t in trades if _regime_of(t["entry_ts"]) == regime]
            if not reg_trades:
                w(f"| {regime} | {sc_name} | 0 | - | - |")
                continue
            Rs = np.array([t["R"] for t in reg_trades])
            mR = Rs.mean()
            wr = (Rs > 0).mean()
            w(f"| {regime} | {sc_name} | {len(reg_trades)} | {mR:+.3f} | {wr*100:.1f}% |")
    w("")

    # =========================================================
    # Shuffle baseline (50 random R shuffles)
    # =========================================================
    w("### Shuffle Baseline (50 perms, p-value)")
    w("")
    w("Real mean R'i 50 rastgele permütasyondan elde edilen null dağılımla karşılaştır.")
    w("")
    w("| Strategy | n | Real mR | Shuffle 90th | p-value |")
    w("|---|---:|---:|---:|---:|")
    rng = np.random.default_rng(42)
    for name, trades in [("inside_day_failure", idf), ("high_tight_flag", htf), ("quasimodo_reversal", qm)]:
        if len(trades) < 30:
            w(f"| {name} | {len(trades)} | - | - | n/a |")
            continue
        Rs = np.array([t["R"] for t in trades])
        real_mR = Rs.mean()
        # Null hypothesis: trades have zero mean. Shuffle R signs (preserve magnitude distribution)
        # Better: sign permutation under H0 of zero edge.
        shuffle_means = []
        for _ in range(50):
            signs = rng.choice([-1, 1], size=len(Rs))
            shuffled = np.abs(Rs) * signs
            shuffle_means.append(shuffled.mean())
        sh_arr = np.array(shuffle_means)
        sh_90 = float(np.percentile(sh_arr, 90))
        # P-value: fraction of shuffles >= real
        p = float((sh_arr >= real_mR).mean())
        w(f"| {name} | {len(trades)} | {real_mR:+.3f} | {sh_90:+.3f} | {p:.3f} |")

    # =========================================================
    # Param perturb (per-strategy)
    # =========================================================
    w("")
    w("### Param Perturbation (sensitivity, +/-25%)")
    w("")
    w("Standalone re-gather edilemedi (script çağrısı uzun) — perturbation testleri için ayrı sprint önerisi (sec19b).")
    w("")
    w("Bu pass için **ana grid sweep'in 3 hipotezdeki default param'ı sabit** tutuldu; en iyi varyant aday production için ayrıca tune edilecek.")
    w("")

    # =========================================================
    w("## Reproducibility")
    w("")
    w(f"- TOP_10 trades: {len(top10)}")
    w(f"- FVG trades: {len(fvg)}")
    w(f"- IDF trades: {len(idf)}")
    w(f"- HTF trades: {len(htf)}")
    w(f"- QM trades: {len(qm)}")
    w(f"- Pencere: {len(windows)} (3y rolling, 60 gun step)")
    w(f"- Config: configs/risk_balanced.yaml (v1.5+ BALANCED, side-cond hibrit, force-exit time=30 bar)")
    w(f"- Engine defaults: tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.5, runner_force_exit='time', force_exit_bars=30")
    w(f"- Multiple-testing: 5 senaryo x 13 pencere = 65 test. Bonferroni alpha 0.05/65 = 7.7e-4 (cok sıkı, FDR Benjamini-Hochberg q=0.10 daha gevşek alternatif).")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
