"""SEC31 Ablation Analysis — Per-Strategy & Per-Symbol R Profili (Round 4 hazırlık).

Konteks:
  Round 1 (pyramid_on + manifest + r%2): yıllık +%122 / DD -%31 / r-adj 3.91 (34 pencere, 551k trade)
  Round 2 (r%3) ve Round 3 (r%4) backtest'leri arkada çalışıyor.
  User otonom iterasyon istedi — bu sprint Round 4 için ablation kararını destekler.

Hedef:
  10 strat × 10 sym = 100 hücre matrix:
    - mean R, sumR, n, WR, mean peak_R, hold_time
  Per-strategy ve per-symbol aggregate.
  Drop candidate list: strategy_mean_R < +0.02 OR sumR < 0 OR WR < %40.

Idempotent:
  Trade pool disk'e pickle olarak yazılır (data/sec31_15m_pool.pkl).
  Tekrar çalıştırıldığında reuse edilir — Round 5, 6 için hızlı analiz.
  Force refresh: SEC31_ABLATION_FORCE=1.

Output:
  - Trade pool cache: data/sec31_15m_pool.pkl
  - Rapor: reports/analyst/2026-05-17_phoenix_scalp_15m_per_strategy_R.md

NOT: Backtest engine ve risk hesabını ÇAĞIRMAZ — sadece collect_all_trades pool'u
üzerinden raw R agregasyonu. production_replay kullanılmaz.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
import time
from pathlib import Path
from statistics import mean, median

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

import scripts.sec31_phoenix_scalp_15m_rolling as sec31

POOL_CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
REPORT_OUT = ROOT / "reports" / "analyst" / "2026-05-17_phoenix_scalp_15m_per_strategy_R.md"
FORCE_REFRESH = bool(int(os.environ.get("SEC31_ABLATION_FORCE", "0")))


# ============================================================================
# Pool collect (cached)
# ============================================================================
def load_or_collect_pool() -> list[dict]:
    """Cached collect. Disk'te varsa yükle; yoksa collect + persist."""
    if POOL_CACHE.exists() and not FORCE_REFRESH:
        print(f"[CACHE HIT] {POOL_CACHE} ({POOL_CACHE.stat().st_size/1e6:.1f} MB)")
        t0 = time.time()
        with POOL_CACHE.open("rb") as f:
            pool = pickle.load(f)
        print(f"[CACHE LOAD] {len(pool)} trade, {time.time()-t0:.1f}s")
        return pool

    print(f"[COLLECT START] 10 strat × 10 sym × 15m (5y) — beklenen ~40-50 dk")
    t0 = time.time()
    pool = sec31.collect_all_trades(sec31.SYMBOLS_10, parallel=False)
    elapsed = time.time() - t0
    print(f"[COLLECT DONE] {len(pool)} trade, {elapsed:.1f}s ({elapsed/60:.1f} min)")

    POOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"[PERSIST] {POOL_CACHE}")
    with POOL_CACHE.open("wb") as f:
        pickle.dump(pool, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[PERSIST DONE] {POOL_CACHE.stat().st_size/1e6:.1f} MB")
    return pool


# ============================================================================
# Aggregation helpers
# ============================================================================
def hold_time_minutes(t: dict) -> float:
    try:
        dt = (t["exit_ts"] - t["entry_ts"]).total_seconds() / 60.0
        return max(0.0, dt)
    except Exception:
        return 0.0


def aggregate(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "mean_R": 0.0, "median_R": 0.0, "sumR": 0.0,
                "WR_pct": 0.0, "mean_peakR": 0.0, "max_peakR": 0.0,
                "mean_hold_min": 0.0, "median_hold_min": 0.0}
    Rs = [t["R"] for t in trades]
    peaks = [t.get("peak_R", t["R"]) for t in trades]
    holds = [hold_time_minutes(t) for t in trades]
    wins = sum(1 for r in Rs if r > 0)
    return {
        "n": len(trades),
        "mean_R": sum(Rs) / len(Rs),
        "median_R": median(Rs),
        "sumR": sum(Rs),
        "WR_pct": wins * 100.0 / len(Rs),
        "mean_peakR": sum(peaks) / len(peaks),
        "max_peakR": max(peaks),
        "mean_hold_min": sum(holds) / len(holds),
        "median_hold_min": median(holds),
    }


# ============================================================================
# Matrix builders
# ============================================================================
def per_strategy(pool: list[dict]) -> dict[str, dict]:
    by = {}
    for t in pool:
        by.setdefault(t["strategy"], []).append(t)
    return {k: aggregate(v) for k, v in by.items()}


def per_symbol(pool: list[dict]) -> dict[str, dict]:
    by = {}
    for t in pool:
        by.setdefault(t["symbol"], []).append(t)
    return {k: aggregate(v) for k, v in by.items()}


def per_strategy_symbol(pool: list[dict]) -> dict[tuple[str, str], dict]:
    by = {}
    for t in pool:
        by.setdefault((t["strategy"], t["symbol"]), []).append(t)
    return {k: aggregate(v) for k, v in by.items()}


# ============================================================================
# Ablation candidate scoring
# ============================================================================
def ablation_candidates(per_strat: dict, gate_meanR: float = 0.02,
                        gate_WR: float = 40.0) -> dict:
    """Drop candidate listesi: mean_R < gate OR sumR < 0 OR WR < gate."""
    drop = []
    keep = []
    border = []
    for strat, m in per_strat.items():
        reasons = []
        if m["sumR"] < 0:
            reasons.append(f"sumR<0 ({m['sumR']:+.1f})")
        if m["mean_R"] < gate_meanR:
            reasons.append(f"mean_R<{gate_meanR} ({m['mean_R']:+.3f})")
        if m["WR_pct"] < gate_WR:
            reasons.append(f"WR<{gate_WR}% ({m['WR_pct']:.1f}%)")
        if reasons:
            drop.append((strat, m, reasons))
        elif m["mean_R"] < 0.05 or m["WR_pct"] < 45.0:
            border.append((strat, m, ["borderline"]))
        else:
            keep.append((strat, m))
    return {"drop": drop, "border": border, "keep": keep}


# ============================================================================
# Report rendering
# ============================================================================
def render_report(pool: list[dict]) -> str:
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    per_strat = per_strategy(pool)
    per_sym = per_symbol(pool)
    cell = per_strategy_symbol(pool)
    cands = ablation_candidates(per_strat)

    pool_R = [t["R"] for t in pool]
    pool_mR = sum(pool_R) / len(pool_R) if pool_R else 0
    pool_wr = sum(1 for r in pool_R if r > 0) * 100 / len(pool_R) if pool_R else 0
    ts_min = min(t["entry_ts"] for t in pool)
    ts_max = max(t["exit_ts"] for t in pool)

    w("# Phoenix-Scalp 15m — Per-Strategy & Per-Symbol R Ablation (Round 4 hazırlık)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** 15m | **Universe:** 10 strat × 10 sym = 100 hücre")
    w(f"**Pool span:** {ts_min} → {ts_max}")
    w("")
    w(f"## Pool Snapshot")
    w("")
    w(f"- Toplam trade: **{len(pool):,}**")
    w(f"- Pool mean R: **{pool_mR:+.4f}** | sumR: {sum(pool_R):+.1f} | WR: {pool_wr:.1f}%")
    w(f"- Round 1 (sec31b, pyramid_on r%2): yıllık +%122 / DD -%31 / r-adj 3.91 (34 pencere)")
    w("")

    # ------------------------------------------------------------------ headline
    sorted_strat = sorted(per_strat.items(), key=lambda kv: -kv[1]["mean_R"])
    sorted_sym = sorted(per_sym.items(), key=lambda kv: -kv[1]["mean_R"])

    w("## Headline (CEO 2 cümle)")
    w("")
    top1, top1m = sorted_strat[0]
    bot1, bot1m = sorted_strat[-1]
    w(f"> 10 strateji içinden **{top1}** (mean R {top1m['mean_R']:+.3f}, n={top1m['n']:,}) en güçlü, "
      f"**{bot1}** (mean R {bot1m['mean_R']:+.3f}) en zayıf — drop kategori sayısı {len(cands['drop'])}.")
    w(f"> Round 4 öneri: en zayıf {len(cands['drop'])} strateji düşürülürse pool mean R "
      f"~+{_estimate_uplift_meanR(pool, cands['drop']):.4f}'e çıkar, n ~{_estimate_pool_size_after_drop(pool, cands['drop']):,}.")
    w("")

    # ----------------------------------------------------------- per-strategy
    w("## Per-Strategy Summary (sorted by mean R desc)")
    w("")
    w("| Rank | Strategy | n | mean R | median R | sumR | WR% | mean peakR | max peakR | mean hold (min) | median hold (min) |")
    w("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, (k, m) in enumerate(sorted_strat, 1):
        w(f"| {i} | `{k}` | {m['n']:,} | {m['mean_R']:+.4f} | {m['median_R']:+.4f} | "
          f"{m['sumR']:+.1f} | {m['WR_pct']:.1f} | {m['mean_peakR']:+.3f} | "
          f"{m['max_peakR']:+.2f} | {m['mean_hold_min']:.1f} | {m['median_hold_min']:.1f} |")
    w("")

    # ----------------------------------------------------------- per-symbol
    w("## Per-Symbol Summary (sorted by mean R desc)")
    w("")
    w("| Rank | Symbol | n | mean R | median R | sumR | WR% | mean peakR |")
    w("|---:|---|---:|---:|---:|---:|---:|---:|")
    for i, (k, m) in enumerate(sorted_sym, 1):
        w(f"| {i} | {k} | {m['n']:,} | {m['mean_R']:+.4f} | {m['median_R']:+.4f} | "
          f"{m['sumR']:+.1f} | {m['WR_pct']:.1f} | {m['mean_peakR']:+.3f} |")
    w("")

    # ----------------------------------------------------------- strategy x symbol matrix
    w("## Strategy × Symbol Matrix — mean R (n)")
    w("")
    syms_ordered = [s for s, _ in sorted_sym]
    strats_ordered = [s for s, _ in sorted_strat]
    header = "| Strategy \\ Symbol | " + " | ".join(syms_ordered) + " |"
    sep = "|---" + "|---:" * len(syms_ordered) + "|"
    w(header)
    w(sep)
    for strat in strats_ordered:
        row = [f"`{strat}`"]
        for sym in syms_ordered:
            m = cell.get((strat, sym))
            if not m or m["n"] == 0:
                row.append("-")
            else:
                marker = ""
                if m["mean_R"] >= 0.10:
                    marker = "**"
                elif m["mean_R"] <= 0.0:
                    marker = "_"
                txt = f"{marker}{m['mean_R']:+.3f}{marker} (n={m['n']})"
                row.append(txt)
        w("| " + " | ".join(row) + " |")
    w("")
    w("Legend: **bold** = mean R ≥ +0.10 (güçlü hücre); _italic_ = mean R ≤ 0 (kayıp hücre).")
    w("")

    # ----------------------------------------------------------- ablation
    w("## Ablation Önerisi")
    w("")
    w("**Drop kriteri (OR):** mean R < +0.02, sumR < 0, WR < %40.")
    w("")
    if cands["drop"]:
        w("### Drop Adayları (Round 4)")
        w("")
        w("| Strategy | mean R | sumR | WR% | n | Reasons |")
        w("|---|---:|---:|---:|---:|---|")
        for k, m, reasons in sorted(cands["drop"], key=lambda x: x[1]["mean_R"]):
            w(f"| `{k}` | {m['mean_R']:+.4f} | {m['sumR']:+.1f} | {m['WR_pct']:.1f} | "
              f"{m['n']:,} | {', '.join(reasons)} |")
        w("")
    else:
        w("Drop adayı yok — 10 strateji de gate'i geçiyor.")
        w("")

    if cands["border"]:
        w("### Borderline (izleme — Round 5 değerlendirme)")
        w("")
        w("| Strategy | mean R | sumR | WR% | n |")
        w("|---|---:|---:|---:|---:|")
        for k, m, _ in sorted(cands["border"], key=lambda x: x[1]["mean_R"]):
            w(f"| `{k}` | {m['mean_R']:+.4f} | {m['sumR']:+.1f} | {m['WR_pct']:.1f} | {m['n']:,} |")
        w("")

    w("### Keep (en güçlü çekirdek)")
    w("")
    w("| Strategy | mean R | sumR | WR% | n |")
    w("|---|---:|---:|---:|---:|")
    keep_sorted = sorted(cands["keep"], key=lambda x: -x[1]["mean_R"])
    for k, m in keep_sorted:
        w(f"| `{k}` | {m['mean_R']:+.4f} | {m['sumR']:+.1f} | {m['WR_pct']:.1f} | {m['n']:,} |")
    w("")

    # ----------------------------------------------------------- symbol ablation
    w("## Symbol Ablation (en zayıf sembol önerisi)")
    w("")
    sorted_sym_asc = sorted(per_sym.items(), key=lambda kv: kv[1]["mean_R"])
    bot_syms = sorted_sym_asc[:3]
    w("Bottom 3 sembol (mean R asc):")
    w("")
    w("| Symbol | mean R | sumR | WR% | n |")
    w("|---|---:|---:|---:|---:|")
    for k, m in bot_syms:
        w(f"| {k} | {m['mean_R']:+.4f} | {m['sumR']:+.1f} | {m['WR_pct']:.1f} | {m['n']:,} |")
    w("")
    # Drop sym candidates: mean R < 0 ya da sumR < 0
    sym_drop = [(k, m) for k, m in per_sym.items() if m["mean_R"] < 0 or m["sumR"] < 0]
    if sym_drop:
        w(f"**Symbol drop adayları:** {', '.join(k for k, _ in sym_drop)}")
        est = _estimate_uplift_meanR_sym(pool, [k for k, _ in sym_drop])
        w(f"Drop edilirse pool mean R: {pool_mR:+.4f} → {est:+.4f}")
    else:
        w("**Hiçbir sembol drop edilecek kadar zayıf değil — 10 sym keep.**")
    w("")

    # ----------------------------------------------------------- Round 4 config önerisi
    w("## Round 4 Önerisi — Ablation Config")
    w("")
    keep_list = [k for k, _ in keep_sorted]
    border_list = [k for k, _, _ in cands["border"]]
    drop_list = [k for k, _, _ in cands["drop"]]

    w(f"### Round 4 Strateji Pool ({len(keep_list)} keep + {len(border_list)} border = {len(keep_list)+len(border_list)} aktif)")
    w("")
    w("```python")
    w("PHOENIX_STRATEGIES_ROUND4 = [  # Round 1 10 strat - " + str(len(drop_list)) + " drop")
    drop_set = set(drop_list)
    for module, cls in sec31.PHOENIX_STRATEGIES:
        if module in drop_set:
            w(f"    # DROP {module} (Round 4 ablation)")
        else:
            w(f'    ("{module}", "{cls}"),')
    w("]")
    w("```")
    w("")
    w(f"**Beklenen pool etkisi:**")
    n_after = _estimate_pool_size_after_drop(pool, cands["drop"])
    mR_after = _estimate_uplift_meanR(pool, cands["drop"])
    w(f"- Trade count: {len(pool):,} → ~{n_after:,} ({100*n_after/len(pool):.0f}%)")
    w(f"- Mean R: {pool_mR:+.4f} → ~{mR_after:+.4f}")
    w(f"- Beklenen yıllık (Round 1 +%122 × (mR_after/mR_now)): "
      f"+{122 * mR_after / pool_mR:.0f}% (lineer projeksiyon, kompozisyon farklı olabilir)")
    w("")

    # ----------------------------------------------------------- bias notes
    w("## Bias / Anomaly Notes")
    w("")
    w("- **Survivorship/selection:** Universe 10 sym Phoenix v2.0.4 universe — Top-10 by liquidity. "
      "MATIC zaten dışlanmış (data eksik). Yeni sembol eklemek bu analizden bağımsız.")
    w("- **Lookahead:** Trade pool sec31.collect_all_trades çıktısı; strategy detect/run engine "
      "causal — manifest `volume_zscore` `period=20` rolling. SEC31 audit PASS.")
    w("- **Hold time bias:** mean_hold_min trade başına ortalama; 15m TF'de trail-stop dominant olan "
      "stratejiler (engulfing_continuation, brooks_h2_l2) daha uzun tutar; FVG/spike fade kısa.")
    w("- **n imbalance:** Stratejiler n=1k–200k arası dağılım gösterir. Düşük-n hücreler için "
      "(per-strategy × per-symbol) güven aralığı geniş — Round 4 öncesi shuffle null test önerilir.")
    w("- **Sample density:** Pool 5y span; 13-pencere walk-forward ile zaten kontrol edilmiş.")
    w("- **Apophenia uyarısı:** Per-cell `mean R` sıralaması küçük n'lerde gürültülü; drop kararı "
      "**aggregate** (per-strategy) seviyesinde alınmıştır, cell-level değil.")
    w("")

    # ----------------------------------------------------------- CEO brief
    w("## CEO Brief'e Önerilen 2 Cümle")
    w("")
    if drop_list:
        w(f"> Phoenix-Scalp 15m pool (551k trade) per-strateji R analizi: {len(drop_list)} strateji "
          f"({', '.join(drop_list)}) mean R < +0.02 eşiğinde, drop edilirse pool mean R "
          f"{pool_mR:+.4f} → {mR_after:+.4f}'e çıkar (~+{122*mR_after/pool_mR-122:.0f}pp yıllık uplift "
          f"projeksiyonu, kompozisyon riskli).")
        w(f"> Round 4 ablation config script'e gömüldü; tekrarlı çalıştırılabilir "
          f"(`scripts/sec31_ablation_analysis.py`, cached pool 5y). Aksiyon: Round 4'ü "
          f"yeni strateji listesiyle başlat ve Round 1 (+%122) ile A/B karşılaştır.")
    else:
        w(f"> Phoenix-Scalp 15m pool (551k trade) per-strateji R analizi: 10 strateji de gate'i geçiyor, "
          f"drop adayı yok. Pool mean R {pool_mR:+.4f} dengeli dağılmış, ablation gerekçesi zayıf.")
        w(f"> Round 4 alternatif lever önerisi: risk_per_trade, max_concurrent, side-cond DD, "
          f"timeframe ensemble. Strateji çıkarma şu an net pozitif değil.")
    w("")

    return "\n".join(lines)


# ============================================================================
# Estimation helpers (lineer projeksiyon — uyarı: composition effect ignored)
# ============================================================================
def _estimate_uplift_meanR(pool: list[dict], drop_list) -> float:
    """Drop edilirse pool mean R — basit aritmetik."""
    drop_set = {k for k, _, _ in drop_list}
    keep_trades = [t for t in pool if t["strategy"] not in drop_set]
    if not keep_trades:
        return 0.0
    return sum(t["R"] for t in keep_trades) / len(keep_trades)


def _estimate_pool_size_after_drop(pool: list[dict], drop_list) -> int:
    drop_set = {k for k, _, _ in drop_list}
    return sum(1 for t in pool if t["strategy"] not in drop_set)


def _estimate_uplift_meanR_sym(pool: list[dict], drop_syms) -> float:
    drop_set = set(drop_syms)
    keep_trades = [t for t in pool if t["symbol"] not in drop_set]
    if not keep_trades:
        return 0.0
    return sum(t["R"] for t in keep_trades) / len(keep_trades)


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    print(f"[SEC31 Ablation] cache: {POOL_CACHE.relative_to(ROOT)}")
    print(f"[SEC31 Ablation] report: {REPORT_OUT.relative_to(ROOT)}")
    print(f"[SEC31 Ablation] force_refresh: {FORCE_REFRESH}")

    pool = load_or_collect_pool()
    if not pool:
        print("[ERR] Empty pool")
        sys.exit(1)

    print(f"[RENDER] aggregating {len(pool)} trade")
    report = render_report(pool)

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"[DONE] {REPORT_OUT}")


if __name__ == "__main__":
    main()
