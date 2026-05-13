"""SEC11.B — Multi-target TP parametre grid optimization.

Hipotez: v0.8'de PROMOTE edilen multi-target engine (1R partial + 2R partial + runner)
parametre tuning v0.8'den beri yenilenmedi. Bugun production v1.1.0 BALANCED+F&G+monthly_dd=0.08
ile farkli (tp1_R, tp2_R) kombinasyonlari belki daha iyi olabilir.

Grid:
  tp1_R (partial_close_at_R) ∈ {0.5, 1.0 (baseline), 1.5}
  tp2_R (primary_R)          ∈ {1.5, 2.0 (baseline), 2.5, 3.0}
  Constraint: tp1_R < tp2_R (anlamli ordering)

Methodology:
  - Her grid hücresi için trade'leri engine ile YENIDEN topla (engine.tp1_R/tp2_R override).
  - 11 sym × Top10 strategy = trade pool (5y backtest).
  - 13 pencere 3y rolling, BALANCED + halt + F&G + monthly_dd=0.08 (v1.1 baseline).
  - production_replay() — canonical.

Statistical gates:
  - Yillik return baseline (+%37.5) üstüne min +%1pp
  - DD baseline (-%31.8) tolerans +%5pp (yani DD >= -36.8% kabul edilir)
  - 13 pencere 0 negatif
  - r-adj iyilesme >= +0.05

Output: reports/lab/sec11b_multitarget_grid.md
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
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
from price_action.backtest.lab import (
    ProductionConfig,
    production_replay,
    _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from price_action.signals.filters import volume_zscore
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import SYMBOLS_11, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip


# --- Engine-parametrize trade gather (multi-target params override) ---


def _gather_with_engine_params(
    module_name: str,
    class_name: str,
    *,
    tp1_R: float = 1.0,
    tp2_R: float = 2.0,
    tp1_close_pct: float = 0.30,
    tp2_close_pct: float = 0.30,
) -> list[dict]:
    """v09_optimize_top10._gather'in engine-parametrize varyanti.

    Engine'i tp1_R/tp2_R/tp1_close_pct/tp2_close_pct override ile insa eder.
    Trade dict shape: v09_optimize_top10._gather ile birebir uyumlu.
    """
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
    except Exception:
        return []

    out: list[dict] = []
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
                risk_officer=None,
                store_load=None,
                tp1_R=tp1_R,
                tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct,
                tp2_close_pct=tp2_close_pct,
            )
            r = e.run(
                s,
                [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=10_000.0,
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
                    vz = float(df["vol_z_pre"].iloc[idx]) if not pd.isna(df["vol_z_pre"].iloc[idx]) else 0
                out.append({
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                })
        except Exception:
            continue
    return out


# --- Walk-forward 13 pencere over BALANCED + F&G + monthly_dd=0.08 (v1.1) ---


@dataclass
class GridResult:
    label: str
    tp1_R: float
    tp2_R: float
    tp1_close_pct: float
    tp2_close_pct: float
    n_trades_pool: int
    annual_mean: float       # %
    annual_median: float     # %
    annual_min: float        # %
    annual_max: float        # %
    dd_mean: float           # % (negatif)
    dd_worst: float          # %
    r_adj: float             # ann_mean / |dd_mean|
    n_negative: int
    n_windows: int

    def passes_gates(self, baseline_ann: float, baseline_dd: float, baseline_radj: float) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if self.annual_mean < baseline_ann + 1.0:
            reasons.append(f"yillik {self.annual_mean:+.2f}% < baseline+1pp ({baseline_ann + 1.0:+.2f}%)")
        # DD daha negatif olamaz baseline+5pp tolerans (baseline -31.8 -> -36.8 alt sinir)
        dd_floor = baseline_dd - 5.0  # -31.8 - 5 = -36.8
        if self.dd_mean < dd_floor:
            reasons.append(f"DD {self.dd_mean:+.2f}% < tolerans ({dd_floor:+.2f}%)")
        if self.n_negative > 0:
            reasons.append(f"negatif pencere = {self.n_negative} (>0)")
        if self.r_adj < baseline_radj + 0.05:
            reasons.append(f"r-adj {self.r_adj:.3f} < baseline+0.05 ({baseline_radj + 0.05:.3f})")
        return len(reasons) == 0, reasons


def run_walkforward(trades: list[dict], cfg: ProductionConfig, windows: list[tuple]) -> tuple[float, float, float, float, float, float, int, int, float]:
    """13 pencere production_replay -> (ann_mean, ann_median, ann_min, ann_max, dd_mean, dd_worst, n_neg, n_win, r_adj).

    cfg: BALANCED + halt + F&G + drop_pairs vs. yi olan production config.
    """
    anns: list[float] = []
    dds: list[float] = []
    for ws, we in windows:
        ww_t = [t for t in trades if ws <= t["entry_ts"] < we]
        r = production_replay(ww_t, cfg)
        if r is None or r.trades == 0:
            continue
        anns.append(r.annualized(3.0) * 100)
        dds.append(r.max_drawdown * 100)
    if not anns:
        return 0, 0, 0, 0, 0, 0, 0, 0, 0
    ann_mean = mean(anns)
    ann_median = median(anns)
    ann_min = min(anns)
    ann_max = max(anns)
    dd_mean = mean(dds)
    dd_worst = min(dds)
    n_neg = sum(1 for a in anns if a < 0)
    n_win = len(anns)
    r_adj = ann_mean / abs(dd_mean) if dd_mean != 0 else 0
    return ann_mean, ann_median, ann_min, ann_max, dd_mean, dd_worst, n_neg, n_win, r_adj


def main() -> None:
    print("=" * 110)
    print("SEC11.B — MULTI-TARGET TP GRID (v1.1 BALANCED+F&G+mDD=0.08 baseline)")
    print("=" * 110)

    # --- Calendar / config setup (v1.1 baseline) ---
    print("\n[1/3] Filter calendars...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": False,  # BALANCED'da kapali
    })
    fng_short_20 = build_fng_short_skip(20)
    print(f"  halt: {sum(1 for v in halt_cal.values() if v)}/{len(halt_cal)} gun")
    print(f"  F&G short-skip (<=20): {len(fng_short_20)} gun")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    cfg_v11 = base_bal.with_overrides(
        btc_halt_calendar=halt_cal,
        alt_data_skip_long=None,
        alt_data_skip_short=dict(fng_short_20),
        # drop_pairs zaten YAML'da yok (yorum satirinda) — frozenset() kalir.
    )
    print(f"  cfg risk_pct={cfg_v11.risk_pct}, monthly_dd={cfg_v11.monthly_dd}, max_concurrent={cfg_v11.max_concurrent}")

    # --- Grid definition ---
    print("\n[2/3] Grid sweep — engine ile her hücre için trade pool RE-GENERATE...")
    tp1_values = [0.5, 1.0, 1.5]   # partial_close_at_R
    tp2_values = [1.5, 2.0, 2.5, 3.0]  # primary_R
    grid = [(t1, t2) for t1 in tp1_values for t2 in tp2_values if t1 < t2]
    # 0.5x{1.5,2.0,2.5,3.0}=4 + 1.0x{1.5,2.0,2.5,3.0}=4 + 1.5x{2.0,2.5,3.0}=3 -> 11 hücre
    print(f"  Toplam grid hücresi (tp1<tp2): {len(grid)}")

    # tp1_close_pct / tp2_close_pct degismez (production %30/%30/%40)
    tp1_close_pct = 0.30
    tp2_close_pct = 0.30

    # --- Generate baseline pool first to set up rolling windows uniformly ---
    print("\n  [BASELINE pool] tp1_R=1.0, tp2_R=2.0 — ortak rolling pencere icin...")
    baseline_pool: list[dict] = []
    for m, c in TOP_10:
        baseline_pool.extend(
            _gather_with_engine_params(m, c, tp1_R=1.0, tp2_R=2.0, tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct)
        )
    baseline_pool.sort(key=lambda x: x["entry_ts"])
    print(f"  Baseline pool: {len(baseline_pool)} trade")

    if not baseline_pool:
        print("HATA: baseline trade pool bos!")
        return
    start = baseline_pool[0]["entry_ts"]
    end = baseline_pool[-1]["exit_ts"]
    windows: list[tuple] = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"  Pencere sayisi (3y rolling, 60d step): {len(windows)}")

    # Run baseline first
    print("\n  [BASELINE] (1.0R / 2.0R) — production v1.1.0 referans:")
    base = run_walkforward(baseline_pool, cfg_v11, windows)
    base_ann, base_med, base_min, base_max, base_dd, base_dd_w, base_neg, base_n, base_radj = base
    print(
        f"    yillik mean={base_ann:+.2f}% (med {base_med:+.2f}, min {base_min:+.2f}, max {base_max:+.2f}) "
        f"DD mean={base_dd:+.2f}% (worst {base_dd_w:+.2f}) r-adj={base_radj:.3f} "
        f"neg={base_neg}/{base_n}"
    )

    # Save baseline GridResult
    base_grid = GridResult(
        label="BASELINE_v1.1",
        tp1_R=1.0, tp2_R=2.0, tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
        n_trades_pool=len(baseline_pool),
        annual_mean=base_ann, annual_median=base_med, annual_min=base_min, annual_max=base_max,
        dd_mean=base_dd, dd_worst=base_dd_w, r_adj=base_radj, n_negative=base_neg, n_windows=base_n,
    )

    # --- Grid execution ---
    print("\n[3/3] GRID HÜCRELERI:\n")
    header = f"  {'cell':<14} {'n_pool':>7} {'ann_mean':>9} {'ann_med':>8} {'ann_min':>8} {'DD_mean':>8} {'DD_worst':>9} {'r-adj':>6} {'neg':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    # Print baseline first (in same format)
    print(
        f"  {'1.0/2.0 BASE':<14} {len(baseline_pool):>7} "
        f"{base_ann:>+8.2f}% {base_med:>+7.2f}% {base_min:>+7.2f}% "
        f"{base_dd:>+7.2f}% {base_dd_w:>+8.2f}% {base_radj:>6.3f} {base_neg:>3}/{base_n:>2}"
    )

    results: list[GridResult] = [base_grid]
    for tp1, tp2 in grid:
        if tp1 == 1.0 and tp2 == 2.0:
            # Already done as baseline
            continue
        label = f"{tp1}/{tp2}"
        # Re-generate pool with these engine params
        pool: list[dict] = []
        for m, c in TOP_10:
            pool.extend(
                _gather_with_engine_params(
                    m, c,
                    tp1_R=tp1, tp2_R=tp2,
                    tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
                )
            )
        pool.sort(key=lambda x: x["entry_ts"])
        if not pool:
            print(f"  {label:<14} {0:>7}  (POOL EMPTY)")
            continue
        ann_m, ann_med, ann_min, ann_max, dd_m, dd_w, n_neg, n_win, r_adj = run_walkforward(pool, cfg_v11, windows)
        gr = GridResult(
            label=label,
            tp1_R=tp1, tp2_R=tp2, tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
            n_trades_pool=len(pool),
            annual_mean=ann_m, annual_median=ann_med, annual_min=ann_min, annual_max=ann_max,
            dd_mean=dd_m, dd_worst=dd_w, r_adj=r_adj, n_negative=n_neg, n_windows=n_win,
        )
        results.append(gr)
        print(
            f"  {label:<14} {len(pool):>7} "
            f"{ann_m:>+8.2f}% {ann_med:>+7.2f}% {ann_min:>+7.2f}% "
            f"{dd_m:>+7.2f}% {dd_w:>+8.2f}% {r_adj:>6.3f} {n_neg:>3}/{n_win:>2}"
        )

    # --- Stats gates evaluation ---
    print("\n--- STATISTICAL GATES (vs BASELINE) ---")
    print(f"  Baseline: ann={base_ann:+.2f}%, DD={base_dd:+.2f}%, r-adj={base_radj:.3f}")
    print(f"  Pass: ann>=+{base_ann + 1.0:.2f}% AND DD>={base_dd - 5.0:+.2f}% AND r-adj>={base_radj + 0.05:.3f} AND neg=0\n")
    print(f"  {'cell':<14} {'PASS':<5} {'reasons':<80}")
    print("  " + "-" * 100)
    passed: list[GridResult] = []
    for gr in results:
        if gr.label == "BASELINE_v1.1":
            continue
        ok, reasons = gr.passes_gates(base_ann, base_dd, base_radj)
        tag = "OK" if ok else "FAIL"
        print(f"  {gr.label:<14} {tag:<5} {('; '.join(reasons))[:80]}")
        if ok:
            passed.append(gr)

    # --- Best config ---
    print("\n--- BEST CONFIG (PASS only, sorted by r-adj desc) ---")
    if passed:
        passed.sort(key=lambda g: g.r_adj, reverse=True)
        best = passed[0]
        print(f"  WINNER: tp1_R={best.tp1_R}, tp2_R={best.tp2_R}")
        print(f"    yillik {best.annual_mean:+.2f}% (vs baseline {base_ann:+.2f}, +{best.annual_mean - base_ann:+.2f}pp)")
        print(f"    DD     {best.dd_mean:+.2f}% (vs baseline {base_dd:+.2f}, +{best.dd_mean - base_dd:+.2f}pp)")
        print(f"    r-adj  {best.r_adj:.3f} (vs baseline {base_radj:.3f}, +{best.r_adj - base_radj:.3f})")
    else:
        print("  HIC PASS YOK — baseline (1.0R/2.0R) optimum kalir.")

    # --- Markdown report ---
    out_md = ROOT / "reports" / "lab" / "sec11b_multitarget_grid.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    write_report(out_md, base_grid, results, passed)
    print(f"\nReport: {out_md}")


def write_report(path: Path, base: GridResult, results: list[GridResult], passed: list[GridResult]) -> None:
    lines: list[str] = []
    lines.append("# SEC11.B — Multi-Target TP Grid Optimization")
    lines.append("")
    lines.append("**Tarih:** 2026-05-13")
    lines.append("**Branch:** main (v1.1.0 baseline — BALANCED+F&G+monthly_dd=0.08)")
    lines.append("**Methodology:** 11 sym × Top10 strategy × 13 pencere 3y rolling, production_replay canonical.")
    lines.append("")
    lines.append("## Hipotez")
    lines.append("")
    lines.append("v0.8'de PROMOTE edilen multi-target engine (HYP-2026-05-09-009: +%6.5pp uplift) parametre tuning")
    lines.append("v0.8'den beri yenilenmedi. Bugün v1.1 BALANCED+F&G+monthly_dd=0.08 cercevesinde farkli")
    lines.append("(tp1_R, tp2_R) kombinasyonlari belki baseline 1R/2R'i yenebilir.")
    lines.append("")
    lines.append("Asıl soru: **v0.8'de seçilen 1R/2R asimetrisi gerçekten optimum muydu, yoksa o zamanki sweep dar mıydı?**")
    lines.append("")
    lines.append("## Engine değişikliği")
    lines.append("")
    lines.append("`src/price_action/backtest/engine.py` — `BacktestEngine.__init__` 4 yeni parametre:")
    lines.append("- `tp1_R` (default 1.0): TP1'in R-multiple uzakligi (`partial_close_at_R`)")
    lines.append("- `tp2_R` (default 2.0): TP2'nin R-multiple uzakligi (`primary_R`)")
    lines.append("- `tp1_close_pct` (default 0.30): TP1'de kapanan qty fraksiyonu")
    lines.append("- `tp2_close_pct` (default 0.30): TP2'de kapanan qty fraksiyonu")
    lines.append("")
    lines.append("Default'lar production v1.0/v1.1 davranisini bire bir korur (geriye uyumlu).")
    lines.append("")
    lines.append("## Grid")
    lines.append("")
    lines.append("- `tp1_R` ∈ {0.5, 1.0 baseline, 1.5}")
    lines.append("- `tp2_R` ∈ {1.5, 2.0 baseline, 2.5, 3.0}")
    lines.append("- Constraint: `tp1_R < tp2_R` -> 11 anlamli hücre")
    lines.append("- `tp1_close_pct=0.30`, `tp2_close_pct=0.30` (production sabit)")
    lines.append("")
    lines.append("## Statistical gates")
    lines.append("")
    lines.append(f"- Yillik return >= baseline + 1pp ({base.annual_mean + 1.0:+.2f}%)")
    lines.append(f"- DD >= baseline - 5pp tolerans ({base.dd_mean - 5.0:+.2f}%)")
    lines.append(f"- r-adj >= baseline + 0.05 ({base.r_adj + 0.05:.3f})")
    lines.append("- 13 pencere 0 negatif")
    lines.append("")
    lines.append("## Sonuçlar")
    lines.append("")
    lines.append("| cell (tp1_R / tp2_R) | n_pool | ann_mean | ann_med | ann_min | DD_mean | DD_worst | r-adj | neg/n |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r.label} | {r.n_trades_pool} | {r.annual_mean:+.2f}% | {r.annual_median:+.2f}% | {r.annual_min:+.2f}% | "
            f"{r.dd_mean:+.2f}% | {r.dd_worst:+.2f}% | {r.r_adj:.3f} | {r.n_negative}/{r.n_windows} |"
        )
    lines.append("")
    lines.append("## Gate evaluation")
    lines.append("")
    lines.append("| cell | PASS | reasons |")
    lines.append("|---|---|---|")
    for r in results:
        if r.label == "BASELINE_v1.1":
            lines.append(f"| {r.label} | (ref) | n/a |")
            continue
        ok, reasons = r.passes_gates(base.annual_mean, base.dd_mean, base.r_adj)
        tag = "PASS" if ok else "FAIL"
        rsn = "; ".join(reasons) if reasons else "-"
        lines.append(f"| {r.label} | {tag} | {rsn} |")
    lines.append("")
    lines.append("## Karar")
    lines.append("")
    if passed:
        passed.sort(key=lambda g: g.r_adj, reverse=True)
        best = passed[0]
        lines.append(f"**WINNER:** tp1_R={best.tp1_R}, tp2_R={best.tp2_R}, tp1_close_pct={best.tp1_close_pct}, tp2_close_pct={best.tp2_close_pct}")
        lines.append("")
        lines.append(f"- Yillik: {best.annual_mean:+.2f}% (baseline {base.annual_mean:+.2f}%, delta {best.annual_mean - base.annual_mean:+.2f}pp)")
        lines.append(f"- DD: {best.dd_mean:+.2f}% (baseline {base.dd_mean:+.2f}%, delta {best.dd_mean - base.dd_mean:+.2f}pp)")
        lines.append(f"- r-adj: {best.r_adj:.3f} (baseline {base.r_adj:.3f}, delta {best.r_adj - base.r_adj:+.3f})")
        lines.append(f"- 13 pencere negatif: {best.n_negative}")
        lines.append("")
        lines.append("**Aksiyon:** `configs/risk_balanced.yaml`'da `take_profit.partial_close_at_R` ve `take_profit.primary_R` guncelle. Engine'de hard-coded 1R/2R'i yeni default'a tasi (sec11b promote).")
    else:
        lines.append("**RED.** Hicbir grid hücresi 4 gate'i (ann + DD + r-adj + neg=0) gecemedi.")
        lines.append("")
        lines.append("Yapısal yorum: v0.8'de seçilen 1R/2R asimetrisi 3 yıl rolling pencerelerde halen optimum.")
        lines.append("Big winners'i daha geç partial close (1.5R) veya daha uzak primary (3.0R) ile maksimize")
        lines.append("etmeye calismak give-back riskini DD tarafinda dengeleyemedi (ya da r-adj'i iyilestiremedi).")
        lines.append("")
        lines.append("**Aksiyon:** Mevcut production parametre (1.0R / 2.0R / %30+%30) korunur. Bu sprint")
        lines.append("RED hipotez olarak memory'e kaydedilir. Sonraki adim: tp1_close_pct/tp2_close_pct grid")
        lines.append("(simdi sabit %30/%30 — belki %20/%40 veya %40/%20 farklidir).")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
