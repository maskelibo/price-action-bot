"""Sec15.2 — Yeni signal source survey v3.

Hedef: v1.5.0 production (TOP_11 + A6 force-exit + side-cond HIBRIT + mc=12) baseline:
  yillik +%116.3 / DD -%34.9 / r-adj 3.332

Aday yeni signal source'lar (3 implement):
  1) bollinger_squeeze_breakout (1d) — YENI
  2) three_bar_reversal (1d, Brooks) — YENI
  3) microstructure_proxy (1d, OHLC buy/sell pressure) — YENI

Karsilastirma:
  CHAMPION:    v1.5 baseline (pool_A6_mult15_t30.pkl) - 6650 trade
  CHALLENGERS: v1.5 + her bir yeni signal (3'lu test) ve TOP_14 (combined)

Risk config: configs/risk_balanced.yaml (v1.5: mc=12, side-cond HIBRIT, A6 default)
Engine kwargs: A6 = mult=1.5 + force_exit_method=time, bars=30 (production-safe runner)

Edge gates:
  Standalone: mR > +0.10, n > 50, WR > 35%
  Ensemble  : Yillik delta > +5pp vs v1.5, DD tolerans +5pp, 0/13 negatif, r-adj iyilesme >= +0.10
"""
from __future__ import annotations

import os
import pickle
import sys
import warnings
from pathlib import Path
from statistics import mean, median

os.environ.setdefault("PA_LOG_QUIET", "1")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import (
    ProductionConfig, production_replay, _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import SYMBOLS_11
from scripts.v097_balanced_optimization import build_fng_short_skip


REPORT_OUT = ROOT / "reports" / "lab" / "sec15_2_new_signals_v3.md"
CACHE_DIR = ROOT / "data" / "_sec15_2_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_POOL_PATH = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"


# v1.5 stack — A6 engine kwargs (sec13.4 winner)
A6_ENGINE_KW = dict(
    runner_trail_mult=1.5,
    trail_activate_stage=2,
    tp1_R=1.0,
    tp2_R=1.5,
    tp1_close_pct=0.30,
    tp2_close_pct=0.30,
    runner_force_exit_method="time",
    runner_force_exit_bars=30,
    runner_force_exit_ema=20,
)


# Yeni stratejiler
NEW_STRATEGIES = [
    ("bollinger_squeeze_breakout", "BollingerSqueezeBreakoutStrategy"),
    ("three_bar_reversal", "ThreeBarReversalStrategy"),
    ("microstructure_proxy", "MicrostructureProxyStrategy"),
]


def gather_with_engine(module_name, class_name, **engine_kwargs):
    """Engine kwargs ile pool gen (sec13.4 patern)."""
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN-import] {module_name}: {e}")
        return []

    out = []
    for sym in SYMBOLS_11:
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
                **engine_kwargs,
            )
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d", initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
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
            print(f"  [WARN-sim] {module_name}/{sym}: {e}")
    return out


def gather_or_load(module_name, class_name):
    cache_p = CACHE_DIR / f"pool_{module_name}.pkl"
    if cache_p.exists():
        with cache_p.open("rb") as f:
            d = pickle.load(f)
        print(f"  [cache HIT] {module_name}: {len(d)} trades")
        return d
    print(f"  [pool gen] {module_name} (A6 engine kwargs)...")
    pool = gather_with_engine(module_name, class_name, **A6_ENGINE_KW)
    pool.sort(key=lambda x: x["entry_ts"])
    with cache_p.open("wb") as f:
        pickle.dump(pool, f)
    print(f"     -> {len(pool)} trades  saved")
    return pool


def summary(trades, name):
    if not trades:
        return {"name": name, "n": 0, "mR": 0.0, "sumR": 0.0, "WR": 0.0,
                "n_long": 0, "n_short": 0}
    Rs = np.array([t["R"] for t in trades], dtype=float)
    return {
        "name": name,
        "n": len(trades),
        "mR": float(Rs.mean()),
        "sumR": float(Rs.sum()),
        "WR": float((Rs > 0).mean()),
        "n_long": sum(1 for t in trades if t["side"] == "long"),
        "n_short": sum(1 for t in trades if t["side"] == "short"),
    }


def make_windows(start, end, span_days=3 * 365, step_days=60):
    out = []
    cur = start
    while cur + pd.Timedelta(days=span_days) <= end:
        out.append((cur, cur + pd.Timedelta(days=span_days)))
        cur += pd.Timedelta(days=step_days)
    return out


def evaluate_pool(trades, cfg, windows):
    if not trades:
        return None
    anns, dds, n_trades = [], [], []
    for ws, we in windows:
        w = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(w, cfg)
        if r is None:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
        n_trades.append(int(r.trades) if r.trades else 0)
    if not anns:
        return None
    ma, md = mean(anns), mean(dds)
    ra = ma / abs(md) if md != 0 else 0
    return {
        "mean_ann": ma,
        "median_ann": median(anns),
        "min_ann": min(anns),
        "max_ann": max(anns),
        "mean_dd": md,
        "min_dd": min(dds),
        "r_adj": ra,
        "negatives": sum(1 for a in anns if a < 0),
        "n_windows": len(anns),
        "avg_trades": mean(n_trades) if n_trades else 0,
    }


def main():
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines = []

    def w(line=""):
        print(line)
        out_lines.append(line)

    w("# Sec15.2 - Yeni Signal Source Survey v3 (2026-05-13)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("**Hedef:** v1.5.0 production (TOP_11 + A6 force-exit + side-cond HIBRIT + mc=12)")
    w("- v1.5 baseline (sec13.4 measured): yillik +%69.82 / DD -%34.8 / r-adj 2.004")
    w("- NOT: prompt v1.5 +%116.3 anar (mevcut sec13.4 cache mc=12 yaml ile measured: %69.82)")
    w("- Anlamli karsilastirma DELTA bazli yapilir (CHAMPION pool ile CHALLENGERS pool ayni cfg).")
    w("")
    w("**Adaylar (3 YENI):**")
    w("- bollinger_squeeze_breakout (1d) — BB width 60d median'in %50 alti -> consolidation, breakout direction")
    w("- three_bar_reversal (1d, Brooks) — 3-bar pullback to EMA20 + reversal trigger")
    w("- microstructure_proxy (1d) — OHLC buy/sell pressure (close-low)/(high-low) absorption signal")
    w("")
    w("**Engine kwargs (yeni signal pool gen icin A6 ile birebir parite):**")
    w(f"- {A6_ENGINE_KW}")
    w("")

    # ========== 1) Baseline pool yukle ==========
    if not BASELINE_POOL_PATH.exists():
        print(f"FATAL: baseline pool yok: {BASELINE_POOL_PATH}")
        return
    with BASELINE_POOL_PATH.open("rb") as f:
        baseline_pool = pickle.load(f)
    print(f"[baseline] v1.5 A6 pool: {len(baseline_pool)} trades")

    # ========== 2) Yeni signal'leri gather (A6 engine ile) ==========
    print("\n[gather] Yeni stratejiler (3 adet):")
    new_pools = {}
    for mod, cls in NEW_STRATEGIES:
        new_pools[mod] = gather_or_load(mod, cls)

    # ========== 3) Standalone Edge Table ==========
    w("## Standalone Edge (5y, 11 sym, A6 engine kwargs)")
    w("")
    w("Edge gate: mR > +0.10, n > 50, WR > 35%")
    w("")
    w("| Strategy | n | mR | sumR | WR | long/short | Edge |")
    w("|---|---:|---:|---:|---:|---:|---|")
    for mod, _ in NEW_STRATEGIES:
        s = summary(new_pools[mod], mod)
        passes = s["mR"] > 0.10 and s["n"] > 50 and s["WR"] > 0.35
        verdict = "PASS" if passes else "FAIL"
        w(f"| {mod} | {s['n']} | {s['mR']:+.3f} | {s['sumR']:+.1f} | {s['WR']*100:.1f}% | "
          f"{s['n_long']}/{s['n_short']} | **{verdict}** |")
    w("")

    # ========== 4) Build CHALLENGERS ==========
    bb = new_pools["bollinger_squeeze_breakout"]
    tbr = new_pools["three_bar_reversal"]
    mp = new_pools["microstructure_proxy"]

    challengers = [
        ("CHAMPION (v1.5 TOP_11)",                        baseline_pool),
        ("v1.5 + bollinger_squeeze",                      sorted(baseline_pool + bb,  key=lambda x: x["entry_ts"])),
        ("v1.5 + three_bar_reversal",                     sorted(baseline_pool + tbr, key=lambda x: x["entry_ts"])),
        ("v1.5 + microstructure_proxy",                   sorted(baseline_pool + mp,  key=lambda x: x["entry_ts"])),
        ("v1.5 + bb + tbr",                               sorted(baseline_pool + bb + tbr, key=lambda x: x["entry_ts"])),
        ("v1.5 + bb + mp",                                sorted(baseline_pool + bb + mp,  key=lambda x: x["entry_ts"])),
        ("v1.5 + tbr + mp",                               sorted(baseline_pool + tbr + mp, key=lambda x: x["entry_ts"])),
        ("v1.5 + 3 yeni (TOP_14)",                        sorted(baseline_pool + bb + tbr + mp, key=lambda x: x["entry_ts"])),
    ]

    # ========== 5) Filter calendars + cfg ==========
    print("\n[filters] BTC halt + funding + F&G short-skip...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}

    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_balanced.yaml"))
    cfg = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        btc_halt_calendar=halt_cal,
        # v1.5 yaml zaten mc=12 + side-cond + 0.06/21
    )
    print(f"\nv1.5 cfg: mc={cfg.max_concurrent}  mdd={cfg.monthly_dd}  halt={cfg.monthly_halt_days}d  "
          f"long_dd={cfg.monthly_dd_long} short_dd={cfg.monthly_dd_short}")
    print(f"         risk_pct={cfg.risk_pct}  short_skip={len(combined_short_skip)} gun")

    # ========== 6) Walk-forward windows ==========
    base_trades = challengers[-1][1]  # TOP_14 pool — en genis
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = make_windows(start, end)
    print(f"Walk-forward pencere: {len(windows)} (3y rolling, 60g step)")
    print(f"Range: {start.date()} -> {end.date()}\n")

    # ========== 7) Evaluate ==========
    w(f"## Walk-Forward (3y rolling, {len(windows)} pencere) — v1.5 cfg (mc=12, side-cond HIBRIT)")
    w("")
    w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif | Avg Trades |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    rated = []
    print(f"{'scenario':<42} {'yillik':>9}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>7}  {'r-adj':>7}  {'neg':>4}  {'n':>5}")
    print("-" * 115)
    for name, trades in challengers:
        res = evaluate_pool(trades, cfg, windows)
        if res is None:
            print(f"  {name:<40}  EVAL_NONE")
            continue
        rated.append((name, res))
        print(f"  {name:<40}  {res['mean_ann']:>+7.1f}%  {res['median_ann']:>+5.1f}%  "
              f"{res['min_ann']:>+5.1f}%  {res['max_ann']:>+5.1f}%  {res['mean_dd']:>+5.1f}%  "
              f"{res['r_adj']:>6.3f}  {res['negatives']:>3}  {res['avg_trades']:>4.0f}")
        w(f"| {name} | {res['mean_ann']:+.1f}% | {res['median_ann']:+.1f}% | "
          f"{res['min_ann']:+.1f}% | {res['max_ann']:+.1f}% | {res['mean_dd']:+.1f}% | "
          f"{res['r_adj']:.3f} | {res['negatives']} | {res['avg_trades']:.0f} |")
    w("")


    # ========== 8) Statistical Gates ==========
    if not rated:
        print("FATAL: no rated results")
        return
    champ_name, champ = rated[0]
    b_ann = champ["mean_ann"]
    b_dd = champ["mean_dd"]
    b_radj = champ["r_adj"]

    w(f"### Statistical Gates vs CHAMPION ({champ_name}: {b_ann:+.1f}% / {b_dd:+.1f}% / r-adj {b_radj:.3f})")
    w("")
    w(f"- **G1 RETURN**  : yillik delta > +5.0pp")
    w(f"- **G2 DD**      : DD delta tolerans > -5.0pp (worse OK if within 5pp)")
    w(f"- **G3 NEG**     : negatives == 0")
    w(f"- **G4 R-ADJ**   : r-adj iyilesme >= +0.10")
    w("")
    w(f"| Scenario | dYillik | dDD | dR-adj | Gates | Verdict |")
    w(f"|---|---:|---:|---:|---|---|")

    for nm, res in rated[1:]:
        d_ann = res["mean_ann"] - b_ann
        d_dd = res["mean_dd"] - b_dd
        d_ra = res["r_adj"] - b_radj
        g1 = d_ann > 5.0
        g2 = d_dd > -5.0
        g3 = res["negatives"] == 0
        g4 = d_ra >= 0.10
        all_ok = g1 and g2 and g3 and g4
        if all_ok:
            verdict = "TOURNAMENT WINNER"
        elif d_ra > 0 and d_ann > 0:
            verdict = "MARGINAL POSITIVE"
        elif d_ann > 0 and d_dd > -3.0:
            verdict = "RETURN UP, RISK FLAT"
        else:
            verdict = "REJECT"
        gate_str = " ".join(["+" if v else "-" for v in (g1, g2, g3, g4)])
        w(f"| {nm} | {d_ann:+.1f}pp | {d_dd:+.1f}pp | {d_ra:+.3f} | [{gate_str}] | **{verdict}** |")
    w("")

    # ========== 8b) BOTTLENECK PROBE — concentration cap relaxed ==========
    print("\n[probe] Bottleneck dogrulama: concentration cap 0.20 -> 0.30")
    cfg_relaxed = cfg.with_overrides(concentration_max_per_symbol_pct=0.30)
    w(f"## Bottleneck Probe — concentration cap 0.20 -> 0.30 (CHAMPION + TOP_14)")
    w("")
    w("Mevcut cap=0.20 yeni signal'leri sym-bazinda blokluyor (sec13.2 bulgu). Cap=0.30 gevsetince katki gorunur mu?")
    w("")
    w(f"| Senaryo | cfg cap | Yillik | DD | r-adj | dYillik vs CHAMPION |")
    w(f"|---|---|---:|---:|---:|---:|")
    probe_rows = [
        ("CHAMPION (v1.5)", baseline_pool, cfg, "0.20"),
        ("CHAMPION (v1.5)", baseline_pool, cfg_relaxed, "0.30"),
        ("TOP_14 (v1.5+3yeni)", challengers[-1][1], cfg_relaxed, "0.30"),
    ]
    for name, trades, cfg_use, cap_lbl in probe_rows:
        res = evaluate_pool(trades, cfg_use, windows)
        if res is None:
            continue
        d = res["mean_ann"] - b_ann
        w(f"| {name} | {cap_lbl} | {res['mean_ann']:+.1f}% | {res['mean_dd']:+.1f}% | "
          f"{res['r_adj']:.3f} | {d:+.1f}pp |")
        print(f"  {name:<24} cap={cap_lbl}  ann={res['mean_ann']:+.1f}%  DD={res['mean_dd']:+.1f}%  r-adj={res['r_adj']:.3f}")
    w("")

    # ========== 9) Sonuc + sonraki adim ==========
    w("## Findings & Karar")
    w("")
    standalone_pass = []
    for mod, _ in NEW_STRATEGIES:
        s = summary(new_pools[mod], mod)
        if s["mR"] > 0.10 and s["n"] > 50 and s["WR"] > 0.35:
            standalone_pass.append(mod)
    w(f"### Standalone (5y, 11 sym, A6 engine)")
    for mod, _ in NEW_STRATEGIES:
        s = summary(new_pools[mod], mod)
        passes = "PASS" if s["mR"] > 0.10 and s["n"] > 50 and s["WR"] > 0.35 else "FAIL"
        w(f"- **{mod}** [{passes}] n={s['n']}, mR={s['mR']:+.3f}, sumR={s['sumR']:+.1f}, WR={s['WR']*100:.1f}%")
    w("")
    w("### Ensemble (v1.5 baseline ile)")
    for nm, res in rated[1:]:
        d_ann = res["mean_ann"] - b_ann
        d_dd = res["mean_dd"] - b_dd
        d_ra = res["r_adj"] - b_radj
        w(f"- {nm}: dYillik {d_ann:+.1f}pp | dDD {d_dd:+.1f}pp | dR-adj {d_ra:+.3f}")
    w("")
    winners = [nm for nm, res in rated[1:]
               if (res["mean_ann"] - b_ann > 5.0 and res["mean_dd"] - b_dd > -5.0
                   and res["negatives"] == 0 and res["r_adj"] - b_radj >= 0.10)]
    if winners:
        w(f"### TOURNAMENT WINNER(S): {', '.join(winners)}")
    else:
        w("### TOURNAMENT WINNER: yok")
        w("")
        w("Slot bottleneck (concentration_max_per_symbol_pct=0.20 + cooldown=3) bagliyici. "
          "Yeni 1d signal'ler zaman dilimi cakismasi nedeniyle pool'a EKLENSE de "
          "production_replay'de slot bulamiyor.")

    w("")
    w("## Reproducibility")
    w("")
    w(f"- Baseline pool (v1.5, sec13.4 A6): {len(baseline_pool)} trades")
    for mod, _ in NEW_STRATEGIES:
        w(f"- {mod}: {len(new_pools[mod])} trades")
    w(f"- Walk-forward: {len(windows)} pencere (3y rolling, 60g step)")
    w(f"- Risk config: configs/risk_balanced.yaml (v1.5: mc=12, side-cond, A6 force-exit)")
    w(f"- Engine kwargs: {A6_ENGINE_KW}")
    w(f"- Filter: BTC halt + funding short-skip + F&G short-skip (<=20)")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport written -> {REPORT_OUT}")


if __name__ == "__main__":
    main()
