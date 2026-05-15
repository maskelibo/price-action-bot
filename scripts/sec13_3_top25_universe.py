"""sec13.3 — Universe expansion: 11 -> 20 sym (TOP_20) walk-forward test.

Pre-registered (bkz reports/lab/sec13_3_top25_universe.md):

PHASE A  Standalone (sym, strat) cell scan
  Yeni 9 sym x TOP_11 strat = 99 cell
  Edge filter: mean R > +0.10 olan cell'leri rapor et (info amacli)

PHASE B  TOP_20 ensemble walk-forward (3y rolling, 13 pencere)
  v1.3 PROD cfg = monthly_dd=0.06 + monthly_halt=21 + tp2_R=1.5 + FVG dahil
  Champion karsilastirmasi: TOP_11 baseline.

GATE:
  yillik return baseline +%60.2 ustune min +%2pp
  DD baseline -%33.4 tolerans +%5pp (yani -%38.4'ten kotu olamaz)
  13/13 pencere POZITIF (0 negatif)
  r-adj baseline 1.802 ustune min +0.05

Konfigurasyonlar:
  C0 baseline TOP_11 (champion replay)
  C1 TOP_20 ALL (yeni 9 hepsi dahil)
  C2 TOP_20 ALL + max_concurrent=12 (slot bottleneck rahatlatma)
  C3 TOP_20 EDGE-ONLY (Phase A'da mean R > +0.10 olan yeni sym + 11 baseline)

Output:
  reports/lab/sec13_3_top25_universe.md
  Konsol: tablo + verdict
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import TOP_10, SYMBOLS_11
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


# v1.3 production stack: TOP_11 = TOP_10 + FVG (sec11 final)
TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]

# Pre-registered new universe (9 sym — bkz ingest_top25_universe.py docstring)
NEW_SYMBOLS_9 = [
    "FIL/USDT", "AAVE/USDT", "NEAR/USDT",
    "ENJ/USDT", "BCH/USDT", "DASH/USDT", "LTC/USDT", "AXS/USDT", "TRX/USDT",
]

SYMBOLS_20 = SYMBOLS_11 + NEW_SYMBOLS_9


def gather_with_engine(module_name: str, class_name: str, symbols: list[str], *,
                       runner_trail_mult: float = 1.0,
                       trail_activate_stage: int = 2,
                       tp1_R: float = 1.0, tp2_R: float = 2.0,
                       tp1_close_pct: float = 0.30, tp2_close_pct: float = 0.30) -> list[dict]:
    """sec11 final stack engine ile per-(strat,sym) trade pool."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name}: {e}")
        return []

    out = []
    for sym in symbols:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(
                risk_officer=None, store_load=None,
                runner_trail_mult=runner_trail_mult,
                trail_activate_stage=trail_activate_stage,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
            )
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d", initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010}, slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    val = df["vol_z_pre"].iloc[idx]
                    if pd.notna(val):
                        vz = float(val)
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym, "side": str(t["side"]).lower(),
                    "conf": conf, "strategy": module_name, "vol_z": vz,
                })
        except Exception as e:
            print(f"  [WARN] {module_name} on {sym}: {e}")
    return out


def main() -> None:
    print("=" * 110)
    print("sec13.3 UNIVERSE EXPANSION — 11 sym -> 20 sym (TOP_20)")
    print("=" * 110)
    print(f"  baseline 11: {SYMBOLS_11}")
    print(f"  new 9      : {NEW_SYMBOLS_9}")
    print(f"  v1.3 prod cfg: monthly_dd=0.06 + halt=21 + tp2_R=1.5 + FVG (TOP_11)")

    # ============================================================
    # Phase A: Standalone (sym, strat) cell scan — yeni 9 sym ucucu
    # ============================================================
    print("\n" + "=" * 110)
    print("PHASE A — Standalone cell scan: yeni 9 sym x TOP_11 strat")
    print("=" * 110)

    # v1.3 stack engine kwargs: tp2_R=1.5 (sec11 B winner)
    engine_kwargs = dict(runner_trail_mult=1.0, tp1_R=1.0, tp2_R=1.5)

    cell_stats = {}  # (strat, sym) -> dict
    new_sym_pools = {sym: [] for sym in NEW_SYMBOLS_9}

    print(f"\n{'strategy':<32} {'symbol':<12} {'n':>5} {'mean_R':>8} {'sumR':>9} {'WR':>6}  edge")
    print("-" * 90)
    for module_name, class_name in TOP_11:
        trades = gather_with_engine(module_name, class_name, NEW_SYMBOLS_9,
                                    **engine_kwargs)
        for t in trades:
            new_sym_pools[t["symbol"]].append(t)
        # group by symbol
        by_sym = {}
        for t in trades:
            by_sym.setdefault(t["symbol"], []).append(t)
        for sym in NEW_SYMBOLS_9:
            ts = by_sym.get(sym, [])
            if not ts:
                cell_stats[(module_name, sym)] = (0, 0.0, 0.0, 0.0)
                continue
            n = len(ts)
            mr = mean(t["R"] for t in ts)
            sr = sum(t["R"] for t in ts)
            wr = sum(1 for t in ts if t["R"] > 0) / n
            cell_stats[(module_name, sym)] = (n, mr, sr, wr)
            edge = " * EDGE" if mr > 0.10 else ""
            print(f"  {module_name:<30} {sym:<12} {n:>5d} {mr:>+7.3f}R {sr:>+7.2f}R {wr*100:>5.1f}%{edge}")

    # Edge-only sym list: en az 1 strat'ta mean R > +0.10 olan yeni sym
    edge_syms = set()
    edge_pairs = []
    for (strat, sym), (n, mr, sr, wr) in cell_stats.items():
        if n >= 5 and mr > 0.10:
            edge_syms.add(sym)
            edge_pairs.append((strat, sym, n, mr, wr))

    print(f"\n  Edge sym sayisi (en az 1 strat'ta mean R > +0.10, n>=5): {len(edge_syms)}")
    for sym in sorted(edge_syms):
        n_strat = sum(1 for (st, sy), (n, mr, _, _) in cell_stats.items()
                      if sy == sym and n >= 5 and mr > 0.10)
        print(f"    {sym:<12}  edge_strat_count={n_strat}")

    # Per-sym total summary
    print("\n  Yeni sym standalone totaller:")
    print(f"  {'symbol':<12} {'n_total':>9} {'mean_R':>8} {'sumR':>9} {'WR':>6}")
    sym_totals = {}
    for sym in NEW_SYMBOLS_9:
        ts = new_sym_pools[sym]
        if ts:
            n = len(ts); mr = mean(t["R"] for t in ts); sr = sum(t["R"] for t in ts)
            wr = sum(1 for t in ts if t["R"] > 0) / n
        else:
            n, mr, sr, wr = 0, 0.0, 0.0, 0.0
        sym_totals[sym] = (n, mr, sr, wr)
        print(f"  {sym:<12} {n:>9d} {mr:>+7.3f}R {sr:>+7.2f}R {wr*100:>5.1f}%")

    # ============================================================
    # Phase B: TOP_20 ensemble walk-forward (3y rolling, 13 pencere)
    # ============================================================
    print("\n" + "=" * 110)
    print("PHASE B — Ensemble walk-forward (3y rolling)")
    print("=" * 110)

    # Trade pool: TOP_11 strat * SYMBOLS_20
    print("\n  Trade pool gen (TOP_11 strat x SYMBOLS_20)...")
    pool_all20 = []
    for module_name, class_name in TOP_11:
        ts = gather_with_engine(module_name, class_name, SYMBOLS_20, **engine_kwargs)
        pool_all20.extend(ts)
    pool_all20.sort(key=lambda x: x["entry_ts"])

    # baseline 11-sym pool (cache for C0)
    pool_11 = [t for t in pool_all20 if t["symbol"] in set(SYMBOLS_11)]
    pool_edge = [t for t in pool_all20
                 if t["symbol"] in set(SYMBOLS_11) | edge_syms]
    print(f"    pool_11 (baseline)     : {len(pool_11)} trade")
    print(f"    pool_20 (all)          : {len(pool_all20)} trade")
    print(f"    pool_edge ({11+len(edge_syms)} sym) : {len(pool_edge)} trade")
    print(f"    edge_syms              : {sorted(edge_syms)}")

    # Filter calendars (v1.3 stack)
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}

    # v1.3 prod cfg = BALANCED + monthly_dd=0.06 + halt=21
    base = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    cfg_v13 = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        monthly_dd=0.06,
        monthly_halt_days=21,
    )
    cfg_v13_slot12 = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        monthly_dd=0.06,
        monthly_halt_days=21,
        max_concurrent=12,
    )

    def run_wf(pool: list[dict], cfg: ProductionConfig, label: str):
        if not pool:
            return None
        start = pool[0]["entry_ts"]
        end = pool[-1]["exit_ts"]
        windows = []
        cur = start
        while cur + pd.Timedelta(days=3 * 365) <= end:
            windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
            cur += pd.Timedelta(days=60)
        anns, dds = [], []
        for ws, we in windows:
            ww = [t for t in pool if ws <= t["entry_ts"] < we]
            r = production_replay(ww, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            return None
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0.0
        neg = sum(1 for a in anns if a < 0)
        return {
            "label": label, "n_trade": len(pool), "n_win": len(windows),
            "ann_mean": ma, "ann_median": median(anns),
            "ann_min": min(anns), "ann_max": max(anns),
            "ann_std": stdev(anns) if len(anns) > 1 else 0.0,
            "dd_mean": md, "dd_max": min(dds), "neg": neg,
            "r_adj": ra,
        }

    scenarios = [
        ("C0 baseline TOP_11 (champion replay)", pool_11, cfg_v13),
        ("C1 TOP_20 ALL (yeni 9 hepsi dahil)", pool_all20, cfg_v13),
        ("C2 TOP_20 ALL + max_concurrent=12", pool_all20, cfg_v13_slot12),
        (f"C3 TOP_{11+len(edge_syms)} EDGE-only (yeni edge sym + 11)", pool_edge, cfg_v13),
    ]

    print(f"\n{'scenario':<55} {'n_trade':>7} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>7} {'maxDD':>7} {'r-adj':>7} {'neg':>5}")
    print("-" * 120)
    results = []
    for label, pool, cfg in scenarios:
        res = run_wf(pool, cfg, label)
        if not res:
            print(f"  {label:<55} -- bos")
            continue
        results.append(res)
        print(f"  {label:<55} {res['n_trade']:>7d} "
              f"{res['ann_mean']:>+7.1f}% {res['ann_median']:>+5.1f}% "
              f"{res['ann_min']:>+5.1f}% {res['ann_max']:>+5.1f}% "
              f"{res['dd_mean']:>+5.1f}% {res['dd_max']:>+5.1f}% "
              f"{res['r_adj']:>6.3f} {res['neg']:>3}/{res['n_win']}")

    # ============================================================
    # GATE evaluation
    # ============================================================
    if not results:
        print("\nNo results, abort.")
        return

    base_res = results[0]
    print("\n" + "=" * 110)
    print("GATE EVAL (vs C0 baseline TOP_11)")
    print("=" * 110)
    print(f"  baseline yillik = {base_res['ann_mean']:+.2f}%, DD = {base_res['dd_mean']:+.2f}%, r-adj = {base_res['r_adj']:.3f}")
    print(f"  Required: yillik >= baseline +%2pp, DD tolerance +%5pp, neg=0, r-adj >= baseline +0.05\n")

    print(f"  {'scenario':<55} {'roi_d':>7} {'dd_d':>7} {'radj_d':>8} {'verdict':>20}")
    for r in results[1:]:
        roi_d = r["ann_mean"] - base_res["ann_mean"]
        dd_d = r["dd_mean"] - base_res["dd_mean"]  # +ise DD daha az kotu (iyilesti)
        radj_d = r["r_adj"] - base_res["r_adj"]
        gates = []
        if roi_d >= 2: gates.append("ROI+2pp")
        else: gates.append(f"ROI{roi_d:+.1f}<2")
        if dd_d >= -5: gates.append("DD<+5pp")  # dd_d >= -5 means new dd <= base+5pp worse
        else: gates.append(f"DD{dd_d:+.1f}>+5")
        if r["neg"] == 0: gates.append("neg=0")
        else: gates.append(f"neg={r['neg']}")
        if radj_d >= 0.05: gates.append("radj+0.05")
        else: gates.append(f"radj{radj_d:+.2f}<0.05")
        passed = (roi_d >= 2 and dd_d >= -5 and r["neg"] == 0 and radj_d >= 0.05)
        verdict = "*** PASS ***" if passed else "FAIL"
        print(f"  {r['label']:<55} {roi_d:>+5.1f}pp {dd_d:>+5.1f}pp {radj_d:>+6.2f}  {verdict:>20}")
        print(f"    gates: {', '.join(gates)}")

    # Markdown report write
    write_report(results, cell_stats, sym_totals, edge_syms, edge_pairs, base_res)
    print(f"\nReport: reports/lab/sec13_3_top25_universe.md")


def write_report(results, cell_stats, sym_totals, edge_syms, edge_pairs, base_res):
    out = ROOT / "reports" / "lab" / "sec13_3_top25_universe.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# sec13.3 — Universe Expansion: 11 -> 20 sym")
    lines.append("")
    lines.append("**Sprint:** v1.4 universe expansion (Researcher)")
    lines.append("**Pre-registered:** 2026-05-13")
    lines.append("**Config:** v1.3 PROD (monthly_dd=0.06 + halt=21 + tp2_R=1.5 + FVG)")
    lines.append("")
    lines.append("## Universe selection")
    lines.append("")
    lines.append("Brief'te 14 yeni sym istendi (toplam 25). Listing-date >= 2021-05-15 + perp 30d avg vol >= $100M filtreleri")
    lines.append("uygulandiginda 14 aday icinde sadece 2 (FIL $125M, AAVE $117M) sert esigi geciyor; geri kalanlar:")
    lines.append("")
    lines.append("- **Listing fail (post-2021)**: APT (2022-10), ARB (2023-03), OP (2022-06), SUI (2023-05) — 5y data yok, walk-forward integrity zarar gorur.")
    lines.append("- **Vol fail (perp <$100M)**: TRX 52M, LTC 60M, BCH 64M, ATOM 19M, NEAR 96M, INJ 39M, UNI 55M, ICP 42M.")
    lines.append("")
    lines.append("**Methodological adjustment**: $100M/perp esigini esnetip $50M tabanina cektim (5y listed olma sarti SIKI tutuldu).")
    lines.append("Ek olarak alternatif altcoinler (ETC, FTM, XLM, ALGO, AXS, ENJ, DASH, vs.) vol-tabanli tarandı; $50M+ ve 5y listed")
    lines.append("kosullarini saglayan toplam 9 yeni sym sectim. ZEC ($727M) — privacy-coin halving pump anomalisi suphesi → REJECT.")
    lines.append("")
    lines.append("**Final 9 yeni sym (pre-registered):**")
    lines.append("")
    lines.append("| Sym | Listing | Perp 30d avg vol | Tier |")
    lines.append("|-----|---------|------------------|------|")
    lines.append("| FIL/USDT | 2020-10-15 | $125.1M | T1 |")
    lines.append("| AAVE/USDT | 2020-10-15 | $116.9M | T1 |")
    lines.append("| NEAR/USDT | 2020-10-14 | $96.0M | T1- |")
    lines.append("| ENJ/USDT | 2019-04-18 | $91.4M | T2 |")
    lines.append("| BCH/USDT | 2019-11-28 | $64.4M | T2 |")
    lines.append("| DASH/USDT | 2019-03-28 | $63.8M | T2 |")
    lines.append("| LTC/USDT | 2017-12-13 | $59.9M | T2 |")
    lines.append("| AXS/USDT | 2020-11-04 | $55.1M | T2 |")
    lines.append("| TRX/USDT | 2018-06-11 | $52.0M | T2 |")
    lines.append("")
    lines.append("(Vol kaynagi: Binance USDT-M Perpetual /fapi/v1/klines, 30d quote_vol average, snapshot 2026-05-13.)")
    lines.append("")
    lines.append("## Phase A — Standalone (sym, strat) edge scan")
    lines.append("")
    lines.append("| sym | n_total | mean_R | sumR | WR |")
    lines.append("|-----|--------:|-------:|-----:|---:|")
    for sym in sorted(sym_totals.keys()):
        n, mr, sr, wr = sym_totals[sym]
        lines.append(f"| {sym} | {n} | {mr:+.3f} | {sr:+.2f} | {wr*100:.1f}% |")
    lines.append("")
    lines.append(f"**Edge sym (en az 1 strat'ta mean R > +0.10, n>=5)**: {len(edge_syms)} adet")
    lines.append("")
    if edge_pairs:
        lines.append("| strategy | symbol | n | mean_R | WR |")
        lines.append("|----------|--------|--:|-------:|---:|")
        for st, sy, n, mr, wr in sorted(edge_pairs, key=lambda x: -x[3]):
            lines.append(f"| {st} | {sy} | {n} | {mr:+.3f} | {wr*100:.1f}% |")
        lines.append("")
    lines.append("## Phase B — Walk-forward ensemble (3y rolling)")
    lines.append("")
    lines.append("| scenario | n_trade | yillik | med | min | max | DD | maxDD | r-adj | neg |")
    lines.append("|----------|--------:|-------:|----:|----:|----:|---:|------:|------:|----:|")
    for r in results:
        lines.append(f"| {r['label']} | {r['n_trade']} | {r['ann_mean']:+.1f}% | "
                     f"{r['ann_median']:+.1f}% | {r['ann_min']:+.1f}% | {r['ann_max']:+.1f}% | "
                     f"{r['dd_mean']:+.1f}% | {r['dd_max']:+.1f}% | {r['r_adj']:.3f} | {r['neg']}/{r['n_win']} |")
    lines.append("")
    lines.append("## GATE eval (vs C0 baseline TOP_11)")
    lines.append("")
    lines.append(f"Baseline: yillik {base_res['ann_mean']:+.2f}%, DD {base_res['dd_mean']:+.2f}%, r-adj {base_res['r_adj']:.3f}")
    lines.append("")
    lines.append("Gates:")
    lines.append("- yillik >= baseline +%2pp")
    lines.append("- DD tolerance +%5pp (yani -33.4 -> en kotu -38.4)")
    lines.append("- 13/13 pencere POZITIF")
    lines.append("- r-adj iyilesme >= +0.05")
    lines.append("")
    lines.append("| scenario | ROI_delta | DD_delta | r-adj_delta | verdict |")
    lines.append("|----------|----------:|---------:|------------:|---------|")
    for r in results[1:]:
        roi_d = r["ann_mean"] - base_res["ann_mean"]
        dd_d = r["dd_mean"] - base_res["dd_mean"]
        radj_d = r["r_adj"] - base_res["r_adj"]
        passed = (roi_d >= 2 and dd_d >= -5 and r["neg"] == 0 and radj_d >= 0.05)
        verdict = "**PASS**" if passed else "FAIL"
        lines.append(f"| {r['label']} | {roi_d:+.1f}pp | {dd_d:+.1f}pp | {radj_d:+.2f} | {verdict} |")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
