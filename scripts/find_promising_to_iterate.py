"""Realistic backtest sonuçlarından 'pozitif edge ama kötü risk' stratejileri
tespit et + Researcher'a iterate talebi (inbox doc) yaz.

Faz 14.22 (2026-05-27): Researcher mevcut yapıda pozitif aylık ROI üretmiş
ama DD/risk kötü olan stratejileri REDDEDEBİLİR. Bu israftır — pozitif
edge nadir kaynak. Bu script bu stratejileri tespit eder, Researcher
inbox'a 'iterate-v2' talebi koyar (improve risk profile, keep edge).

Kriter:
  - monthly_roi_pct_mean > 0 (pozitif aylık)
  - max_dd > champion_dd * 1.5 VEYA max_dd > -25%
  - n_trades > 100 (n yeterli)
  - henüz aynı stratejide v2+ iterate hipotezi yazılmamış

Output:
  - reports/researcher_iterate_queue/<date>-iterate-queue.md
  - memory/researcher/iterate_targets.json (tracker)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "memory" / "researcher" / "realistic_backtest_results"
QUEUE_DIR = ROOT / "reports" / "researcher_iterate_queue"
TRACKER_PATH = ROOT / "memory" / "researcher" / "iterate_targets.json"
HYPOTHESES_DIR = ROOT / "memory" / "researcher" / "hypotheses"

# Eşikler (canlı bot baseline'a göre)
CHAMPION_DD_PCT = 15.5  # vsa wide-stop maxDD
CHAMPION_MONTHLY_ROI = 13.0  # vsa wide-stop aylık
MIN_MONTHLY_ROI = 0.5  # bu altında pozitif edge sayılmaz
MIN_N_TRADES = 100  # n yeterli
MAX_DD_BAD_THRESHOLD = -25.0  # bu altı 'kötü risk'
MAX_ITERATE_VERSIONS = 5


def _load_results() -> list[dict]:
    """Tüm realistic backtest sonuçlarını oku."""
    rows = []
    if not RESULTS_DIR.exists():
        return rows
    for f in sorted(RESULTS_DIR.glob("*.realistic.json")):
        try:
            d = json.loads(f.read_text())
            r = d.get("result", d)  # bazı format'larda direkt root
            r["_source_file"] = f.name
            rows.append(r)
        except Exception:
            continue
    return rows


def _count_existing_iterates(base_name: str) -> int:
    """Bu base strategy için kaç tane iterate hipotezi yazılmış."""
    if not HYPOTHESES_DIR.exists():
        return 0
    cnt = 0
    base_lower = base_name.lower().replace("_", "-")
    for f in HYPOTHESES_DIR.glob("*.md"):
        name = f.stem.lower()
        if base_lower in name and ("iterate" in name or "-v2" in name or "-v3" in name):
            cnt += 1
    return cnt


def find_promising() -> list[dict]:
    """Iterate yapılması gereken stratejileri shortlist'le."""
    results = _load_results()
    candidates = []
    for r in results:
        # Status filter
        if r.get("status") != "OK":
            continue
        roi = float(r.get("monthly_roi_mean", r.get("monthly_roi_pct_mean", 0)))
        dd = float(r.get("max_dd", r.get("max_drawdown_pct", 0)))
        n = int(r.get("n_trades", 0))
        if roi < MIN_MONTHLY_ROI:
            continue
        if n < MIN_N_TRADES:
            continue
        # Risk kötü mü?
        bad_dd = (dd < MAX_DD_BAD_THRESHOLD) or (abs(dd) > CHAMPION_DD_PCT * 1.5)
        if not bad_dd:
            continue
        # FIX 2026-07-02 (fabrika RW P1-5): FELAKET-DD üst sınırı. "Pozitif
        # edge ama kötü risk → iterate et" tasarımının üst sınırı yoktu;
        # maxDD −58..−87 ölü sinyaller kuyruğu dolduruyordu (iterate_targets
        # 5 çöp seed, 33 gün boşa iterate). DD < −40 veya ayların >%40'ı
        # negatifse sinyalin KENDİSİ bozuk — tp/risk ayarı düzeltemez, alma.
        neg_m = int(r.get("neg_months", 0) or 0)
        tot_m = int(r.get("total_months", 0) or 0)
        if dd < -40.0 or (tot_m > 0 and neg_m / tot_m > 0.40):
            continue
        # Strategy adı çıkar
        strategy = r.get("strategy", r.get("hyp", "unknown"))
        if isinstance(strategy, str):
            base = strategy.split("-")[0] if "-" in strategy else strategy
        else:
            base = str(strategy)
        # Çoktan iterate edilmiş mi?
        existing_iters = _count_existing_iterates(base)
        if existing_iters >= MAX_ITERATE_VERSIONS:
            continue
        candidates.append(
            {
                "hypothesis_id": r.get("hyp", r.get("hypothesis_id", "?")),
                "base_strategy": base,
                "monthly_roi": roi,
                "max_dd": dd,
                "n_trades": n,
                "annualized": float(r.get("annualized", r.get("annualized_compound_pct", 0))),
                "neg_months": int(r.get("monthly_neg_count", 0)),
                "total_months": int(r.get("monthly_total", 0)),
                "existing_iterate_versions": existing_iters,
                "next_version": existing_iters + 2,  # v1 = base, v2 = first iterate
                "source_file": r["_source_file"],
            }
        )
    # Pozitif ROI'ye göre sırala (en umut verici önce)
    candidates.sort(key=lambda c: c["monthly_roi"], reverse=True)
    return candidates


def write_iterate_queue(candidates: list[dict]) -> Path:
    """Researcher için iterate talep doc'u yaz."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    out_path = QUEUE_DIR / f"iterate-queue-{date_str}.md"

    body = [
        f"# Researcher Iterate Queue — {date_str} UTC",
        "",
        "## Talep",
        "",
        "Aşağıdaki stratejiler **pozitif aylık ROI** üretti ama **DD/risk metriği kötü**.",
        "Persona SOP-4b'ye göre **REDDEDİLEMEZLER** — iterate edilmeli.",
        "",
        "Her aday için **min 1 yeni hipotez** (v2/v3/...) yaz:",
        "  - Risk reduction (risk_pct azalt)",
        "  - Trade quality filter (confluence/vol_z/sl_pct eşiği yükselt)",
        "  - Position management (BE-protect, trailing, time-exit)",
        "  - Symbol/regime subset",
        "",
        f"**Champion baseline:** aylık +{CHAMPION_MONTHLY_ROI}%, DD -{CHAMPION_DD_PCT}%",
        "",
        "## Adaylar (pozitif edge — DD kontrol gerek)",
        "",
        "| Strateji | Aylık ROI | DD | n_trades | Önceki versiyonlar | Sıradaki versiyon |",
        "|---|---|---|---|---|---|",
    ]
    if not candidates:
        body.append("| (boş — şu an iterate adayı yok) |")
    for c in candidates:
        body.append(
            f"| `{c['hypothesis_id'][:50]}` | "
            f"**+{c['monthly_roi']:.2f}%** | "
            f"**{c['max_dd']:.1f}%** | "
            f"{c['n_trades']} | "
            f"{c['existing_iterate_versions']} | "
            f"v{c['next_version']} |"
        )
    body.extend(
        [
            "",
            "## Eylem",
            "",
            "Researcher: bu listeye bak. Her aday için **min 1 iterate hipotezi**",
            "pre-register et (`memory/researcher/hypotheses/<date>-<base>-iterate-v<N>-<theme>.md`).",
            "",
            "Tahmini compute: her iterate ~15-30 dk Lab tournament + realistic_backtest.",
            "",
            "## Çıktı şablonu",
            "",
            "```yaml",
            "doc_type: hypothesis",
            "iterate_from: <base hyp_id>",
            "iterate_version: v2",
            "iterate_theme: risk_reduction | trade_quality | position_management | symbol_subset",
            "param_grid:",
            "  risk_pct: [0.001, 0.002, 0.003]  # baseline 0.005'ten azaltılmış",
            "  ...",
            "accept_gates:",
            "  monthly_roi_mean >= 5%",
            "  max_dd >= -20%",
            "  neg_month_count <= 10/61",
            "```",
        ]
    )
    out_path.write_text("\n".join(body), encoding="utf-8")
    return out_path


def update_tracker(candidates: list[dict]) -> None:
    """Iterate tracker güncelle (process state)."""
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if TRACKER_PATH.exists():
        try:
            existing = json.loads(TRACKER_PATH.read_text())
        except Exception:
            existing = {}
    existing["last_scan"] = datetime.now(UTC).isoformat()
    existing["n_candidates"] = len(candidates)
    existing["candidates"] = candidates
    TRACKER_PATH.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")


def main() -> int:
    candidates = find_promising()
    queue_path = write_iterate_queue(candidates)
    update_tracker(candidates)

    print(f"Iterate queue yazıldı: {queue_path}")
    print(f"Aday sayısı: {len(candidates)}")
    print()
    if candidates:
        print(f"{'Strateji':50} {'Aylık':>8} {'DD':>8} {'n':>6}")
        print("-" * 80)
        for c in candidates:
            print(
                f"{c['hypothesis_id'][:50]:50} {c['monthly_roi']:>+7.2f}% "
                f"{c['max_dd']:>+7.2f}% {c['n_trades']:>6}"
            )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
