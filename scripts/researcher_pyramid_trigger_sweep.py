"""Researcher sprint — Pyramid leg trigger sweep (Phoenix 15m).

B-3 cakismasi (leg-2 trigger ~= TP1, cift round-trip fee) icin INCE trigger sweep.
CEO E[2.0,3.0]/E2[2.5,3.5] buyuk kaydirmalarda net-negatif buldu; bu sprint
TP1(1.0R)/TP2(1.5R) arasindaki ~1.2-1.3R bosluk bolgesini ve ustunu tarar.

Muhasebe: HONEST (BE-protect KALDIRILDI — leg ters donerse -trigger e kadar zarar).
  D commit 6d4d719 canli BE-protect i ekledi AMA honest model karsilastirma icin
  korunur — trigger kaydirmasinin ALPHA etkisini izole etmek istiyoruz.

Reproduce: python scripts/researcher_pyramid_trigger_sweep.py
Pool: data/sec53_15m_pool_v11.pkl   Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml
market.duckdb e DOKUNULMAZ — pool pkl yeterli.
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
SLIP = 0.06  # CEO honest replay ile birebir slippage_erosion katsayisi

# Multi-target TP seviyeleri (engine.py sat 415-425): TP1@1.0R, TP2@1.5R bandi.
TP1_R = 1.0
TP2_R = 1.5
# Round-trip fee tahmini: taker 0.075% x2 + slippage ~ 16 bps round-trip.
ROUND_TRIP_BPS = 16.0

# Test edilen trigger setleri (sizes sabit [0.50,0.30] — gorev sadece trigger sweep).
TRIGGER_SETS = [
    ("[1.0,1.5] baseline/canli", (1.0, 1.5)),
    ("[1.2,1.7]", (1.2, 1.7)),
    ("[1.25,1.75]", (1.25, 1.75)),
    ("[1.3,1.8]", (1.3, 1.8)),
    ("[1.2,2.0]", (1.2, 2.0)),
    ("[1.5,2.5]", (1.5, 2.5)),
]
SIZES = (0.5, 0.3)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def build_pool(pool, triggers, sizes, fee_bps, mode="honest"):
    """Trigger-parametrik HONEST/IDEAL pyramid pool. CEO honest replay semantigi."""
    out = []
    for t in pool:
        t2 = dict(t)
        R = t["R"]
        pk = t["peak_R"]
        sl_pct = abs(t["initial_sl"] - t["entry_price"]) / t["entry_price"] if t["entry_price"] > 0 else 0.04
        fee_R = (fee_bps / (sl_pct * 10000.0)) if (fee_bps != 0.0 and sl_pct > 0) else 0.0
        if mode == "off":
            t2["R"] = R - fee_R
            out.append(t2)
            continue
        clip = (mode == "ideal")
        radj = R
        for trig, sz in zip(triggers, sizes):
            if pk >= trig:
                contrib = max(0.0, R - trig) if clip else max(R - trig, -trig)
                radj += sz * contrib - SLIP * sz - fee_R * sz
        radj -= fee_R
        t2["R"] = radj
        out.append(t2)
    return out


def eligibility_stats(pool, triggers):
    """Trigger eligibility + B-3 cakisma sayisi + fee tahmini.

    B-3 cakisma modeli: leg-2 fill (AL) ile TP1 reduceOnly (SAT) ayni bar
    civarinda gerceklesirse 'cakisma' — fiyat ayni 0.15R bandinda her ikisini
    de tetikler. Trigger ile TP1 arasi mesafe > 0.15R ise iki olay AYRI barlarda
    olur (cakisma yok) AMA pyramid leg yine de calisir.
    Cakisma sayisi = leg-2 trigger TP1 +/-0.15R bandinda VE trade leg-2 ye ulasti.
    """
    leg2_trig, leg3_trig = triggers[0], triggers[1]
    n = len(pool)
    leg2_elig = sum(1 for t in pool if t["peak_R"] >= leg2_trig)
    leg3_elig = sum(1 for t in pool if t["peak_R"] >= leg3_trig)
    band = 0.15
    leg2_overlap = abs(leg2_trig - TP1_R) <= band
    leg3_overlap = abs(leg3_trig - TP2_R) <= band
    # cakisma olayi: leg-2 fill olan (peak>=leg2_trig) trade ler — trigger TP1 e
    # yakinsa bu fill ile TP1 SAT cift round-trip yapar.
    overlap_n = (leg2_elig if leg2_overlap else 0) + (leg3_elig if leg3_overlap else 0)
    return {
        "leg2_elig": leg2_elig, "leg2_pct": leg2_elig / n * 100,
        "leg3_elig": leg3_elig, "leg3_pct": leg3_elig / n * 100,
        "leg2_overlap": leg2_overlap, "leg3_overlap": leg3_overlap,
        "overlap_active": leg2_overlap or leg3_overlap, "overlap_n": overlap_n,
    }


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me))
        cm = (cm % 12) + 1
        if cm == 1:
            cy += 1
    rets, dds = [], []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            continue
        rets.append(r.total_return * 100)
        dds.append(r.max_drawdown * 100)
    n = len(rets)
    mu = sum(rets) / n
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "annual": annual,
        "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "worst_month_dd": worst_dd,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def pool_sumR(pool):
    return sum(t["R"] for t in pool)


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    """2y train / 90d OOS / 30d step walk-forward — robustness."""
    from datetime import timedelta
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
    while cur + timedelta(days=train_days + oos_days) <= end:
        os_s = cur + timedelta(days=train_days)
        os_e = os_s + timedelta(days=oos_days)
        oos_tr = [t for t in pool if os_s <= to_utc(t["entry_ts"]) < os_e]
        if len(oos_tr) >= 10:
            r = production_replay(oos_tr, cfg)
            if r is not None:
                anns.append(r.annualized(oos_days / 365.0) * 100)
                dds.append(r.max_drawdown * 100)
        cur += timedelta(days=step_days)
    if not anns:
        return None
    ma = sum(anns) / len(anns)
    md = sum(dds) / len(dds)
    return {
        "windows": len(anns), "mean_annual": ma, "mean_dd": md,
        "r_adj": ma / abs(md) if md else 0,
        "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns),
    }


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade" % len(pool), flush=True)
    base = ProductionConfig.from_yaml(str(YAML))
    # pyramid OFF cfg — replay sirasinda pyramid yeniden uygulanmasin (R zaten
    # build_pool da pyramid-adjusted). CEO honest replay ile birebir.
    cfg_off = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(), fee_bps_per_trade=0.0
    )

    for fee in (0.0, 8.0):
        print("\n" + "=" * 100, flush=True)
        print("FEE = %+.0f bps   (HONEST pyramid muhasebe — BE-protect YOK)" % fee, flush=True)
        print("=" * 100, flush=True)

        # Eligibility + cakisma tablosu
        print("\n--- ELIGIBILITY + B-3 CAKISMA ---", flush=True)
        hdr = "%-26s%10s%10s%14s%18s" % (
            "trigger", "leg2 elig", "leg3 elig", "B3-cakisma", "fee-tasarruf*")
        print(hdr, flush=True)
        print("-" * 80, flush=True)
        elig_all = {}
        base_overlap = None
        # ortalama sl_pct — round-trip bps -> R donusumu icin
        sl_pcts = [abs(t["initial_sl"] - t["entry_price"]) / t["entry_price"]
                   for t in pool if t["entry_price"] > 0]
        mean_sl_pct = sum(sl_pcts) / len(sl_pcts)
        for name, trig in TRIGGER_SETS:
            es = eligibility_stats(pool, trig)
            elig_all[name] = es
            if base_overlap is None:
                base_overlap = es["overlap_n"]
            # fee tasarrufu: cakisma sayisindaki azalma x round-trip. Her cakisma
            # = bir gereksiz round-trip (TP1 SAT + leg-2 AL ayni bar). Trigger
            # kayinca cakisma kalkar -> her trade bir round-trip fee tasarruf eder.
            saved_overlaps = base_overlap - es["overlap_n"]
            fee_saved_bps = saved_overlaps * ROUND_TRIP_BPS
            # bps -> pool-R: bir trade nin fee_R = bps / (sl_pct*10000)
            fee_saved_R = saved_overlaps * (ROUND_TRIP_BPS / (mean_sl_pct * 10000.0))
            fee_str = ("%d tr / %.0f R" % (saved_overlaps, fee_saved_R)) if saved_overlaps else "—"
            ovl_str = ("%d" % es["overlap_n"]) if es["overlap_active"] else "0 band-disi"
            print("%-26s%9d %5.1f%%%9d %5.1f%%%14s%16s" % (
                name, es["leg2_elig"], es["leg2_pct"],
                es["leg3_elig"], es["leg3_pct"], ovl_str, fee_str), flush=True)
        print("  * fee-tasarruf = (baseline cakisma - bu cakisma) -> tasarruf-R", flush=True)
        print("    cakisma = leg-2 trig TP1(1.0R) +/-0.15R VEYA leg-3 trig TP2(1.5R) +/-0.15R bandinda", flush=True)
        print("    NOT: bu tasarruf-R ZATEN per-month pool-sumR icine 16bps fee modeliyle dahil", flush=True)
        print("         (mean sl_pct=%.4f kullanildi); ayri kazanc DEGIL — referans amacli." % mean_sl_pct, flush=True)

        # Per-month performans tablosu
        print("\n--- PER-MONTH (61 ay 2021-05 -> 2026-05) ---", flush=True)
        hdr = "%-26s%11s%9s%8s%6s%10s%9s%7s%12s" % (
            "trigger", "annual", "mean", "r-adj", "neg", "maxloss", "wmDD", "CV", "pool-sumR")
        print(hdr, flush=True)
        print("-" * 100, flush=True)
        results = {}
        for name, trig in TRIGGER_SETS:
            p2 = build_pool(pool, trig, SIZES, fee, mode="honest")
            r = per_month(p2, cfg_off)
            r["sumR"] = pool_sumR(p2)
            results[name] = r
            print("%-26s%+10.1f%%%+8.2f%%%8.2f%6d%+9.2f%%%+8.1f%%%6.0f%%%+12.1f" % (
                name, r["annual"], r["mean"], r["r_adj"], r["neg"],
                r["max_loss"], r["worst_month_dd"], r["cv"], r["sumR"]), flush=True)

        # Walk-forward (robustness — per-month compound artefaktina karsi OOS)
        print("\n--- WALK-FORWARD (2y train / 90d OOS / 30d step) ---", flush=True)
        hdr = "%-26s%12s%11s%9s%7s%8s" % (
            "trigger", "mean_ann", "mean_dd", "r-adj", "neg", "windows")
        print(hdr, flush=True)
        print("-" * 73, flush=True)
        wf_results = {}
        for name, trig in TRIGGER_SETS:
            p2 = build_pool(pool, trig, SIZES, fee, mode="honest")
            wf = walk_forward(p2, cfg_off)
            wf_results[name] = wf
            if wf is None:
                print("%-26s%12s" % (name, "(no windows)"), flush=True)
                continue
            print("%-26s%+11.1f%%%+10.1f%%%9.2f%7d%8d" % (
                name, wf["mean_annual"], wf["mean_dd"], wf["r_adj"],
                wf["neg"], wf["windows"]), flush=True)

        # Delta vs baseline
        base_name = TRIGGER_SETS[0][0]
        bl = results[base_name]
        wfb = wf_results[base_name]
        print("\n--- DELTA vs BASELINE [1.0,1.5] ---", flush=True)
        for name, _ in TRIGGER_SETS[1:]:
            r = results[name]
            wf = wf_results[name]
            wins_roi = r["annual"] >= bl["annual"]
            wins_neg = r["neg"] <= bl["neg"]
            wins_dd = r["max_loss"] >= bl["max_loss"]  # max_loss negatif — buyuk = iyi
            verdict = "YENER" if (wins_roi and wins_neg and wins_dd) else "kaybeder"
            wf_ann_d = (wf["mean_annual"] - wfb["mean_annual"]) if (wf and wfb) else 0.0
            print("  %-26s PM-annual %+9.1fpp  r-adj %+7.2f  neg %+d  maxloss %+6.2fpp  sumR %+9.1f  WF-ann %+9.1fpp -> %s" % (
                name, r["annual"] - bl["annual"], r["r_adj"] - bl["r_adj"],
                r["neg"] - bl["neg"], r["max_loss"] - bl["max_loss"],
                r["sumR"] - bl["sumR"], wf_ann_d, verdict), flush=True)


if __name__ == "__main__":
    main()
