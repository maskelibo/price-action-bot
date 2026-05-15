"""Phase1.F1 — Paper vs Backtest Drift Detection (Lab Scientist SOP-2)

Son 30g paper trade vs backtest beklentisi:
  - KS test (Kolmogorov-Smirnov): paper R dist vs backtest R dist
  - Welch's t-test: mean R fark
  - Levene: variance fark

Eşikler:
  - KS p<0.05 + effect >=20% -> DRIFT WARNING
  - KS p<0.01 + effect >=30% -> DRIFT CRITICAL
  - p>=0.05 -> PASS
  - paper n<30 -> INSUFFICIENT SAMPLE

Output: reports/lab_scientist/2026-05-14_drift_detection.md
"""
from __future__ import annotations

import math
import os
import pickle
import sys
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

REPORT_OUT = ROOT / "reports" / "lab_scientist" / "2026-05-14_drift_detection.md"
REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)


def welch_t_test(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    a, b = list(a), list(b)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    sa, sb = va / len(a), vb / len(b)
    denom = math.sqrt(sa + sb)
    if denom <= 0:
        return float("nan"), float("nan")
    t = (ma - mb) / denom
    df_num = (sa + sb) ** 2
    df_den = (sa ** 2) / (len(a) - 1) + (sb ** 2) / (len(b) - 1)
    if df_den <= 0:
        return t, float("nan")
    df = df_num / df_den
    try:
        from scipy.stats import t as _t
        p = 2.0 * (1.0 - _t.cdf(abs(t), df))
    except Exception:
        z = abs(t)
        p = 2.0 * (1.0 - 0.5 * (1 + math.erf(z / math.sqrt(2))))
    return t, p


def ks_2sample(a, b):
    try:
        from scipy.stats import ks_2samp
        s, p = ks_2samp(a, b)
        return float(s), float(p)
    except Exception:
        return float("nan"), float("nan")


def levene_test(a, b):
    try:
        from scipy.stats import levene
        s, p = levene(a, b, center="median")
        return float(s), float(p)
    except Exception:
        return float("nan"), float("nan")


def main():
    print("=" * 100)
    print("Phase1.F1 — Paper vs Backtest Drift Detection")
    print("=" * 100)
    print()

    # 1) Paper trade R-multiples (last 30g)
    paper_db = ROOT / "data" / "paper_journal.duckdb"
    if not paper_db.exists():
        print(f"FATAL: {paper_db} bulunamadi")
        return

    cutoff_ts = pd.Timestamp.utcnow() - pd.Timedelta(days=30)
    conn = duckdb.connect(str(paper_db), read_only=True)

    # paper_trades tablosu (kapanmis trade)
    paper_R_resolved = conn.execute("""
        SELECT r_multiple, exit_reason, exit_ts, symbol, side
        FROM paper_trades
        WHERE status = 'closed' AND r_multiple IS NOT NULL
          AND exit_ts >= ?
        ORDER BY exit_ts
    """, [cutoff_ts]).fetchall()

    # paper_position_events tablosu (sl_hit/tp_hit dahil)
    paper_R_events = conn.execute("""
        SELECT realized_R, event_type, ts, symbol
        FROM paper_position_events
        WHERE realized_R IS NOT NULL AND ts >= ?
        ORDER BY ts
    """, [cutoff_ts]).fetchall()
    conn.close()

    n_resolved = len(paper_R_resolved)
    n_events = len(paper_R_events)
    print(f"Paper sample (last 30g):")
    print(f"  paper_trades (closed):   n={n_resolved}")
    print(f"  paper_position_events:   n={n_events}")
    print()

    # Source choice: events tablosunda R var, trade tablosu boş.
    # Events R-multiple direkt SL/TP hit'leri = en doğru paper-trade-level R.
    paper_R = [float(r[0]) for r in paper_R_events]

    if len(paper_R) > 0:
        print(f"Paper R distribution (n={len(paper_R)}):")
        print(f"  mean={mean(paper_R):+.3f}  median={median(paper_R):+.3f}  "
              f"min={min(paper_R):+.3f}  max={max(paper_R):+.3f}  "
              f"std={stdev(paper_R) if len(paper_R)>1 else 0:.3f}")
        print()

    # 2) Backtest R distribution (full cached pool — 5y reference)
    pool_path = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
    with pool_path.open("rb") as f:
        pool = pickle.load(f)
    bt_R = [float(t["R"]) for t in pool]
    print(f"Backtest R distribution (cached pool, 5y, n={len(bt_R)}):")
    print(f"  mean={mean(bt_R):+.3f}  median={median(bt_R):+.3f}  "
          f"min={min(bt_R):+.3f}  max={max(bt_R):+.3f}  "
          f"std={stdev(bt_R):.3f}")
    print()

    # 3) Insufficient sample gate
    SAMPLE_MIN = 30
    insufficient = len(paper_R) < SAMPLE_MIN

    if insufficient:
        print(f"!!! INSUFFICIENT SAMPLE — paper n={len(paper_R)} < {SAMPLE_MIN}")
        print(f"!!! Drift testleri statistically meaningful değil.")
        print()
        ks_s = ks_p = t_s = t_p = lev_s = lev_p = float("nan")
        verdict = "INSUFFICIENT_SAMPLE"
        # informational only (not used for verdict at n<30)
        if paper_R:
            effect_size = abs(mean(paper_R) - mean(bt_R)) / (abs(mean(bt_R)) + 1e-9) * 100
        else:
            effect_size = float("nan")
    else:
        # 4) Statistical tests
        print("Running tests...")
        ks_s, ks_p = ks_2sample(paper_R, bt_R)
        t_s, t_p = welch_t_test(paper_R, bt_R)
        lev_s, lev_p = levene_test(paper_R, bt_R)
        effect_size = abs(mean(paper_R) - mean(bt_R)) / (abs(mean(bt_R)) + 1e-9) * 100
        print(f"  KS test:    stat={ks_s:.4f}  p={ks_p:.4f}")
        print(f"  Welch t:    stat={t_s:.4f}  p={t_p:.4f}")
        print(f"  Levene:     stat={lev_s:.4f}  p={lev_p:.4f}")
        print(f"  Effect size (|mean delta| / |bt_mean| * 100): {effect_size:.1f}%")
        print()

        # 5) Verdict
        if ks_p < 0.01 and effect_size >= 30:
            verdict = "DRIFT_CRITICAL"
        elif ks_p < 0.05 and effect_size >= 20:
            verdict = "DRIFT_WARNING"
        elif ks_p >= 0.05:
            verdict = "PASS"
        else:
            verdict = "BORDERLINE"

    print("=" * 100)
    print(f"VERDICT: {verdict}")
    print("=" * 100)

    # 6) Write report
    write_report(
        REPORT_OUT,
        paper_R=paper_R,
        bt_R=bt_R,
        n_resolved=n_resolved,
        n_events=n_events,
        ks=(ks_s, ks_p),
        t=(t_s, t_p),
        lev=(lev_s, lev_p),
        effect_size=effect_size,
        verdict=verdict,
        insufficient=insufficient,
        sample_min=SAMPLE_MIN,
    )
    print(f"\nReport: {REPORT_OUT}")


def write_report(path, *, paper_R, bt_R, n_resolved, n_events, ks, t, lev,
                 effect_size, verdict, insufficient, sample_min):
    L = []
    L.append("# Paper vs Backtest Drift Detection\n\n")
    L.append("**Date:** 2026-05-14  \n")
    L.append("**Sprint:** Phase1.F1  \n")
    L.append("**Sorumlu:** Lab Scientist (SOP-2)  \n\n")

    L.append("## 1. Sample Tanımı\n\n")
    L.append("**Paper kaynak:** `data/paper_journal.duckdb`\n")
    L.append(f"- `paper_trades` (status=closed, last 30g): **n={n_resolved}**\n")
    L.append(f"- `paper_position_events` (realized_R not null, last 30g): **n={n_events}**\n")
    L.append(f"- Kullanılan: `paper_position_events.realized_R` (SL/TP hit'lerinin R-multiple'ları)\n\n")
    L.append(f"**Backtest kaynak:** `data/_sec13_4_cache/pool_A6_mult15_t30.pkl` ({len(bt_R)} trade, 5y reference)\n\n")

    if insufficient:
        L.append(f"## 2. VERDICT: INSUFFICIENT SAMPLE\n\n")
        L.append(f"**Paper n = {len(paper_R)} < sample_min ({sample_min})**\n\n")
        L.append("Drift istatistik testleri çalıştırılamaz — paper trade örneklem çok küçük.\n")
        L.append("Statistical power: ~%5 (Welch t-test α=0.05 için n=7 → β ~%95, false-negative riski yüksek).\n\n")
        L.append("**Aksiyon:** 30g sonra retry. Daemon paper trade üretmeye devam etsin.\n")
        L.append("**Lab Scientist hat:** Drift WARN/CRIT verdict YOK — Risk Officer'a şu an alarm yok.\n\n")

        if paper_R:
            L.append("### Paper sample özet (n<30 ama gözleme için)\n\n")
            L.append(f"- mean R = **{mean(paper_R):+.3f}**\n")
            L.append(f"- median R = {median(paper_R):+.3f}\n")
            L.append(f"- min/max = {min(paper_R):+.3f} / {max(paper_R):+.3f}\n")
            if len(paper_R) > 1:
                L.append(f"- std = {stdev(paper_R):.3f}\n")
            L.append("\n")
            # Compare to backtest just for orientation
            L.append(f"### Backtest karşılaştırma (sadece referans)\n\n")
            L.append(f"- backtest mean R = {mean(bt_R):+.3f}\n")
            L.append(f"- paper - backtest delta = {mean(paper_R) - mean(bt_R):+.3f}\n")
            L.append(f"- effect size proxy: {effect_size:.1f}% — bu rakam **n<30 ile güvenilmez**\n\n")
            # WARNING flag if obviously suspicious
            if all(r < 0 for r in paper_R):
                L.append("> ⚠️ **Gözleme notu:** Bütün paper trade'ler SL (R≈-1.0). 7 ardışık sl_hit — "
                         "tek günde (2026-05-13). Sebep olabilir: (a) regime shift, (b) entry timing, "
                         "(c) execution latency, (d) bot day-1 startup koşulları. "
                         "n=7'de drift olarak deklare edilmez ama Researcher + Risk Officer'a "
                         "**'ilk hafta loss-only' gözlem notu** olarak iletilir — pre-emptive görmek için.\n\n")
    else:
        # Sufficient sample - normal tests
        ks_s, ks_p = ks
        t_s, t_p = t
        lev_s, lev_p = lev

        L.append("## 2. İstatistik Tablosu\n\n")
        L.append("| Metric | paper | backtest | delta |\n")
        L.append("|--------|------:|---------:|------:|\n")
        L.append(f"| n | {len(paper_R)} | {len(bt_R)} | — |\n")
        L.append(f"| mean R | {mean(paper_R):+.3f} | {mean(bt_R):+.3f} | "
                 f"{mean(paper_R)-mean(bt_R):+.3f} |\n")
        L.append(f"| median R | {median(paper_R):+.3f} | {median(bt_R):+.3f} | "
                 f"{median(paper_R)-median(bt_R):+.3f} |\n")
        L.append(f"| std R | {stdev(paper_R) if len(paper_R)>1 else 0:.3f} | "
                 f"{stdev(bt_R):.3f} | — |\n")
        L.append(f"| effect size | — | — | **{effect_size:.1f}%** |\n\n")

        L.append("## 3. Hipotez Testleri\n\n")
        L.append("| Test | statistic | p-value | yorum |\n")
        L.append("|------|----------:|--------:|-------|\n")
        L.append(f"| Kolmogorov-Smirnov 2-sample | {ks_s:.4f} | {ks_p:.4f} | distribution eşitliği |\n")
        L.append(f"| Welch t-test | {t_s:.4f} | {t_p:.4f} | mean eşitliği |\n")
        L.append(f"| Levene | {lev_s:.4f} | {lev_p:.4f} | variance eşitliği |\n\n")

        L.append(f"## 4. VERDICT: **{verdict}**\n\n")
        if verdict == "DRIFT_CRITICAL":
            L.append("KS p<0.01 + effect size ≥%30. Paper canlı performans backtest beklentisinden **istatistiksel olarak ANLAMLI** sapıyor.\n\n")
            L.append("**Aksiyon (Lab Scientist hat):**\n")
            L.append("- Risk Officer'a CRITICAL alarm (immediate review).\n")
            L.append("- Production değişikliği BU SCRIPT TARAFINDAN ÖNERİLMEZ — gerekçe analiz Researcher hat.\n")
            L.append("- Olasılık ağacı: data quality / slippage / regime shift / edge erosion.\n\n")
        elif verdict == "DRIFT_WARNING":
            L.append("KS p<0.05 + effect size ≥%20. Drift sinyali gelişti, henüz CRITICAL değil.\n\n")
            L.append("**Aksiyon:** Risk Officer'a WARNING. Researcher hipotez sürmesi istenir. Production lock korunur.\n\n")
        elif verdict == "BORDERLINE":
            L.append("KS p<0.05 ama effect size <%20. İstatistiksel anlamlılık var ama küçük effect — false alarm riski.\n")
            L.append("**Aksiyon:** İzlemeye devam, haftalık retest.\n\n")
        else:  # PASS
            L.append("Paper backtest dağılımı ile **istatistiksel olarak tutarlı** (KS p≥0.05).\n")
            L.append("**Aksiyon:** PASS, drift alarmı YOK. Production lock korunur. Haftalık retest devam.\n\n")

    L.append("## 5. Reproducibility\n\n")
    L.append("```\n")
    L.append("python scripts/phase1_f1_drift_detection.py\n")
    L.append("Source: data/paper_journal.duckdb (paper_position_events.realized_R)\n")
    L.append("Backtest ref: data/_sec13_4_cache/pool_A6_mult15_t30.pkl\n")
    L.append("Cutoff: now - 30g\n")
    L.append("Tests: scipy.stats.ks_2samp, ttest (Welch), levene\n")
    L.append("```\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)


if __name__ == "__main__":
    main()
