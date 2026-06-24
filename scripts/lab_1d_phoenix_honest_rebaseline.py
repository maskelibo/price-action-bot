"""Lab Scientist — HONEST cost re-baseline (1d Phoenix champion v2.0.4).

GOREV (P0): Hafizadaki "+%302/yil, DD -%63, r-adj 5.33, 8-pencere" 1d Phoenix
v2.0.4 sayilari DURUST-MALIYET ile dogrulanmadi. Bu script gercek canli
maliyetlerle re-baseline yapar. 15m honest re-baseline ile BIREBIR metodoloji.

POOL: data/v203_full_pool_peakR_v11_2026-05-18.pkl
  sha256 796e867d... (hafizadaki 796e86... DOGRULANDI — AVWAP v1.1 champion pool)
  7145 trade, 2021-05-15 -> 2026-05-17, 11 sym x 11 strateji (wyckoff_phase_d OUT)
  Her trade R'si engine ciktisidir (flat 5bps slippage + 0.075% taker TP
  partial'larinda gomulu, close_pct 30/30/40 engine default).

CONFIG: configs/risk_phoenix_v204.yaml
  ProductionConfig.from_yaml -> fee_bps_per_trade=0.0 (execution: blogu VAR ama
  ProductionConfig MAP ETMIYOR -> pool da idealize uretilmis, fee=0).
  pyramid [1.0,2.0]x[0.50,0.30], exit_engine 30/30/40 (POOL ile AYNI -> close
  mismatch YOK, reblend gereksiz).

GERCEK CANLI MALIYET (1d-spesifik, 15m'den DUSUK):
  - Komisyon: ~15 bps round-trip taker (post_only_limit_enabled=false -> MARKET)
  - Slippage: 1d icin pre-reg band 10-20 bps (15m'de 45.4 bps; 1d hold uzun,
    pozisyon az, likit-bar girisi -> dusuk). Pool icindeki 5bps'in uzeri delta
    = 5-15 bps.
  - Round-trip ek maliyet bandi: 20 / 27.5 / 35 bps (low/mid/high)
  - extra_cost_R per trade = ek_bps / (sl_pct * 10000)

SENARYOLAR:
  IDEALIZED       — pool R oldugu gibi (fee=0, slip 5bps gomulu)
  HONEST_LOW      — +20 bps (fee15 + slip delta 5)
  HONEST_MID      — +27.5 bps (fee15 + slip delta 12.5)
  HONEST_HIGH     — +35 bps (fee15 + slip delta 15)

market.duckdb'ye DOKUNULMAZ — pool pkl R-bazli honest-replay.
Reproduce: python scripts/lab_1d_phoenix_honest_rebaseline.py
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone, timedelta
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

POOL = ROOT / "data" / "v203_full_pool_peakR_v11_2026-05-18.pkl"
YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"

# --- Maliyet senaryolari (round-trip ek bps) ---
COST_BPS = {"HONEST_LOW": 20.0, "HONEST_MID": 27.5, "HONEST_HIGH": 35.0}
SLIP_PYR = 0.06          # pyramid leg slippage erozyon katsayisi (lab.py parity)

# pyramid (v204 config) — DOGRULANDI ProductionConfig.from_yaml
PYR_TRIG = (1.0, 2.0)
PYR_SIZE = (0.50, 0.30)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    if ep > 0:
        return abs(t["initial_sl"] - ep) / ep
    return 0.10  # 1d median ~%9.5 fallback


def build_pool(pool, mode):
    """mode='idealized' -> pool R oldugu gibi.
       mode in COST_BPS  -> +bps ek maliyet (close_pct reblend YOK, pool=config).
       pyramid IDEAL (D BE-protect canli wiring sonrasi mesru, lab.py 691 semantik).
    """
    extra_bps = 0.0 if mode == "idealized" else COST_BPS[mode]
    out = []
    for t in pool:
        t2 = dict(t)
        R = t["R"]
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                contrib = max(0.0, R - trig)
                radj += sz * contrib - SLIP_PYR * sz
                radj -= extra_R * sz          # leg basina ek round-trip maliyet
        radj -= extra_R                       # base trade maliyeti
        t2["R"] = radj
        out.append(t2)
    return out


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
    mu = sum(rets) / n if n else 0
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    srt = sorted(rets, reverse=True)
    # top-5 ay haric compound yillik
    rest = srt[5:]
    comp_rest = 1.0
    for x in rest:
        comp_rest *= (1 + x / 100)
    annual_ex5 = (comp_rest ** (12.0 / len(rest)) - 1) * 100 if rest else 0
    med = sorted(rets)[n // 2] if n else 0
    return {
        "n": n, "mean": mu, "median": med, "annual": annual,
        "annual_ex5": annual_ex5,
        "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets) if rets else 0,
        "max_gain": max(rets) if rets else 0,
        "worst_month_dd": worst_dd, "rets": rets,
        "top3": srt[:3], "bot3": sorted(rets)[:3],
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
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
        "neg": sum(1 for a in anns if a < 0),
        "neg_pct": sum(1 for a in anns if a < 0) / len(anns) * 100,
        "min": min(anns), "max": max(anns),
    }


def pool_sumR(pool):
    return sum(t["R"] for t in pool)


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade  date %s -> %s" % (
        len(pool), to_utc(pool[0]["entry_ts"]).date(),
        to_utc(pool[-1]["entry_ts"]).date()), flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    cfg = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0,
    )

    # sl_pct dagilimi
    import statistics
    slp = sorted(sl_pct_of(t) for t in pool)
    print("  sl_pct: mean %.4f  median %.4f  p10 %.4f  p90 %.4f" % (
        statistics.mean(slp), slp[len(slp) // 2],
        slp[len(slp) // 10], slp[len(slp) * 9 // 10]), flush=True)
    # extra_cost_R median ornegi (MID senaryo)
    med_sl = slp[len(slp) // 2]
    print("  -> HONEST_MID extra_cost_R @median sl_pct = %.4f R/trade" % (
        27.5 / (med_sl * 10000.0)), flush=True)

    labels = ["IDEALIZED", "HONEST_LOW", "HONEST_MID", "HONEST_HIGH"]
    modes = {"IDEALIZED": "idealized", "HONEST_LOW": "HONEST_LOW",
             "HONEST_MID": "HONEST_MID", "HONEST_HIGH": "HONEST_HIGH"}
    results, wf_results = {}, {}
    for label in labels:
        p2 = build_pool(pool, modes[label])
        r = per_month(p2, cfg)
        r["sumR"] = pool_sumR(p2)
        wf = walk_forward(p2, cfg)
        results[label] = r
        wf_results[label] = wf

    print("\n" + "=" * 104, flush=True)
    print("RE-BASELINE — IDEALIZED vs HONEST  (1d Phoenix champion v2.0.4)", flush=True)
    print("=" * 104, flush=True)
    hdr = "%-14s%11s%9s%10s%9s%8s%11s%9s%7s%11s" % (
        "senaryo", "yillik", "mean", "median", "r-adj", "neg", "ex-top5",
        "wmDD", "CV", "pool-sumR")
    print(hdr, flush=True)
    print("-" * 104, flush=True)
    for label in labels:
        r = results[label]
        print("%-14s%+10.1f%%%+8.2f%%%+9.2f%%%9.2f%5d/%d%+10.1f%%%+8.1f%%%6.0f%%%+11.0f" % (
            label, r["annual"], r["mean"], r["median"], r["r_adj"],
            r["neg"], r["n"], r["annual_ex5"], r["worst_month_dd"],
            r["cv"], r["sumR"]), flush=True)

    ri = results["IDEALIZED"]
    print("\n  --- SISME (IDEALIZED -> HONEST_MID) ---", flush=True)
    rh = results["HONEST_MID"]
    print("  yillik ROI:   %+.1f%% -> %+.1f%%   = %+.1fpp sisme" % (
        ri["annual"], rh["annual"], ri["annual"] - rh["annual"]), flush=True)
    print("  mean ay:      %+.2f%% -> %+.2f%%   = %+.2fpp" % (
        ri["mean"], rh["mean"], ri["mean"] - rh["mean"]), flush=True)
    print("  r-adj:        %.2f -> %.2f   = %+.2f" % (
        ri["r_adj"], rh["r_adj"], ri["r_adj"] - rh["r_adj"]), flush=True)
    print("  negatif ay:   %d -> %d   = %+d ay" % (
        ri["neg"], rh["neg"], rh["neg"] - ri["neg"]), flush=True)
    print("  pool-sumR:    %+.0f -> %+.0f   = %+.0f R (%.1f%% erozyon)" % (
        ri["sumR"], rh["sumR"], rh["sumR"] - ri["sumR"],
        (rh["sumR"] - ri["sumR"]) / abs(ri["sumR"]) * 100), flush=True)

    print("\n" + "=" * 78, flush=True)
    print("WALK-FORWARD (2y train / 90d OOS / 30d step) — OOS robustness", flush=True)
    print("=" * 78, flush=True)
    hdr = "%-14s%13s%11s%9s%10s%9s" % (
        "senaryo", "mean_ann", "mean_dd", "r-adj", "neg", "windows")
    print(hdr, flush=True)
    print("-" * 68, flush=True)
    for label in labels:
        wf = wf_results[label]
        if wf is None:
            print("%-14s  (no windows)" % label, flush=True)
            continue
        print("%-14s%+12.1f%%%+10.1f%%%9.2f%6d/%d (%4.1f%%)%6d" % (
            label, wf["mean_annual"], wf["mean_dd"], wf["r_adj"],
            wf["neg"], wf["windows"], wf["neg_pct"], wf["windows"]), flush=True)

    print("\n" + "=" * 78, flush=True)
    print("ROBUSTNESS — per-month dagilim (HONEST_MID)", flush=True)
    print("=" * 78, flush=True)
    print("  n ay          : %d" % rh["n"], flush=True)
    print("  mean / median : %+.2f%% / %+.2f%%" % (rh["mean"], rh["median"]), flush=True)
    print("  pos / neg     : %d / %d" % (rh["pos"], rh["neg"]), flush=True)
    print("  en iyi 3 ay   : %s" % ", ".join("%+.1f%%" % x for x in rh["top3"]), flush=True)
    print("  en kotu 3 ay  : %s" % ", ".join("%+.1f%%" % x for x in rh["bot3"]), flush=True)
    print("  compound yillik           : %+.1f%%" % rh["annual"], flush=True)
    print("  top-5 ay HARIC yillik     : %+.1f%%" % rh["annual_ex5"], flush=True)
    print("  CV                        : %.0f%%" % rh["cv"], flush=True)

    # aylik ROI -> %10/ay hedefe katki
    print("\n" + "=" * 78, flush=True)
    print("HEDEF DEGERLENDIRME — Principal hedefi durust aylik ortalama >= %10", flush=True)
    print("=" * 78, flush=True)
    for label in labels:
        r = results[label]
        # compound yillik -> aylik geometrik ortalama
        monthly_geo = ((1 + r["annual"] / 100) ** (1 / 12.0) - 1) * 100
        print("  %-14s aritmetik aylik %+.2f%%  | geometrik aylik %+.2f%%  | "
              "median %+.2f%%" % (label, r["mean"], monthly_geo, r["median"]),
              flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
