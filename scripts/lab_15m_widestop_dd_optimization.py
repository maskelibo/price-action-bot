"""Lab Scientist — 15m wide-stop DD-profile joint optimization (P0).

GOREV: Researcher (2026-05-21) 15m wide-stop honest edge bulgusu: sl_pct>=%1.8
filtre honest +55bps altinda pool-R pozitif, aylik-mean +21.72%. KRITIK SERH:
"+21.72%" = 61 BAGIMSIZ $10k replay ORTALAMASI; surekli-equity-egrisi DEGIL.
Gercek surekli-egri DD -41% -> deploy edilemez.

Bu script: sl_pct esik x risk% x DD-throttle JOINT optimizasyon. Hedef fonksiyon
SUREKLI-EQUITY-EGRISI uzerinde: DD <= -25% KISITINI saglarken honest aylik ROI
maksimize et.

ANTI-OVERFIT:
  - Parametreler TRAIN penceresinde secilir (2021-05..2024-11, ~3.5y), OOS'ta
    (2024-11..2026-05, ~1.5y) raporlanir. Researcher WF metodolojisi gibi.
  - Grid search (deterministik, reproduce edilebilir). N_trial Bonferroni + DSR.
  - Surekli-egri DD = production_replay(tum_pool).max_drawdown — TEK kosum, gercek.

HONEST-COST ZORUNLU: +55bps taker baseline (fee 15 + slippage delta 40).
  Duyarlilik: +45bps (slippage 30 alt-bant) + +65bps (slippage 50 ust-bant).
  Idealize fee=0 KULLANILMAZ.

market.duckdb DOKUNULMAZ — pool pkl R-bazli honest replay (Lab metodolojisi).
lab.py + production YAML + canli daemon DOKUNULMAZ.

Reproduce: python scripts/lab_15m_widestop_dd_optimization.py
"""
from __future__ import annotations
import hashlib
import io
import math
import os
import pickle
import sys
from datetime import datetime, timedelta, timezone
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

# --- Honest cost (lab_honest_cost_rebaseline.py birebir) ---
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)

# --- Train / OOS split (anti-overfit) ---
# Pool: 2021-05-16 -> 2026-05-14 (~1824 gun). Split ~70/30.
TRAIN_END = datetime(2024, 11, 1, tzinfo=timezone.utc)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, new_close):
    R = t["R"]
    pk = t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        return c1n * TP1_R + (1.0 - c1n) * R_rest
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        return R
    return c1n * TP1_R + c2n * TP2_R + crn * R_run


def build_pool(pool, extra_bps):
    """Honest cost + close reblend + pyramid IDEAL. R-bazli replay icin."""
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE)
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
                radj -= extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


# ============================================================================
# Continuous-curve metrics (single production_replay over a contiguous pool)
# ============================================================================
def continuous_metrics(trades, cfg):
    """Surekli-egri metrikleri. TEK production_replay kosumu — gercek DD.

    Returns dict veya None.
    """
    if len(trades) < 30:
        return None
    r = production_replay(trades, cfg)
    if r is None:
        return None
    return {
        "n": r.trades, "final": r.final_equity, "ret": r.total_return * 100,
        "dd": r.max_drawdown * 100, "wr": r.win_rate * 100, "sumR": r.sum_r,
        "avg_r": r.avg_r,
    }


def monthly_on_curve(trades, cfg):
    """Surekli-egriden AYLIK getiri serisi cikar. Tek production_replay degil —
    bagimsiz $10k aylik replay (Researcher per_month metodu) DEGIL; bu, surekli
    equity'nin ay-ay yuzdesel buyumesini olcer.

    Yontem: pool'u ay-sinirina bol; her ay icin production_replay AMA initial
    capital = onceki ayin final_equity. Boylece surekli-egri compound korunur
    ama ay-bazli yuzde + DD okunabilir.

    NOT: bu yine de bir yaklasim — gercek surekli engine state (acik pozisyon,
    breaker watermark) ay sinirinda resetlenir. DD icin continuous_metrics()
    tam-pool kosumu KANONIK; aylik seri sadece dagilim (mean/median/neg) icin.
    """
    trades = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    if not trades:
        return None
    start, end = to_utc(trades[0]["entry_ts"]), to_utc(trades[-1]["entry_ts"])
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
    rets = []
    equity = cfg.initial_capital
    for ms, me in months:
        m_tr = [t for t in trades if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        cfg_m = cfg.with_overrides(initial_capital=equity)
        r = production_replay(m_tr, cfg_m)
        if r is None:
            continue
        rets.append(r.total_return * 100)
        equity = r.final_equity
        if equity <= 0:
            equity = 1.0
    n = len(rets)
    if n == 0:
        return None
    mu = sum(rets) / n
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    srt = sorted(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {
        "n": n, "mean": mu, "median": median,
        "neg": sum(1 for x in rets if x < 0),
        "pos": sum(1 for x in rets if x > 0),
        "max_loss": min(rets), "max_gain": max(rets),
        "cv": std / abs(mu) * 100 if mu else 1e9, "rets": rets,
    }


def walk_forward(trades, cfg, train_days=730, oos_days=90, step_days=30):
    trades = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    if not trades:
        return None
    start = to_utc(trades[0]["entry_ts"])
    end = to_utc(trades[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
    while cur + timedelta(days=train_days + oos_days) <= end:
        os_s = cur + timedelta(days=train_days)
        os_e = os_s + timedelta(days=oos_days)
        oos_tr = [t for t in trades if os_s <= to_utc(t["entry_ts"]) < os_e]
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


# ============================================================================
# Joint optimization
# ============================================================================
def split_pool(pool):
    train = [t for t in pool if to_utc(t["entry_ts"]) < TRAIN_END]
    oos = [t for t in pool if to_utc(t["entry_ts"]) >= TRAIN_END]
    return train, oos


def make_cfg(base_cfg, params):
    """params: dict(risk_pct, daily_dd, weekly_dd, monthly_dd, vol_target_atr_pct).
    DD-throttle = daily/weekly/monthly DD halt esikleri + vol-target sizing."""
    return base_cfg.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0,
        risk_pct=params["risk_pct"],
        daily_dd=params["daily_dd"],
        weekly_dd=params["weekly_dd"],
        monthly_dd=params["monthly_dd"],
        monthly_dd_long=params["monthly_dd"],
        monthly_dd_short=min(params["monthly_dd"], 0.06),
        vol_target_atr_pct=params["vol_target_atr_pct"],
        vol_target_enabled=True,
    )


def annual_from_curve(metrics, years):
    """Surekli-egri toplam getiriden yillik compound. Fizik-disi compound
    artefaktindan kacinmak icin: ret cok buyukse log-space annual."""
    if metrics is None or metrics["final"] <= 0:
        return -100.0
    growth = metrics["final"] / 10000.0
    if growth <= 0:
        return -100.0
    return (growth ** (1.0 / years) - 1.0) * 100.0


def objective(train_metrics, train_monthly, dd_constraint=-25.0):
    """Hedef fonksiyon (TRAIN penceresinde): DD <= dd_constraint KISITI altinda
    aylik mean ROI maksimize. Kisit ihlali -> agir ceza.

    Surekli-egri DD train continuous_metrics'ten. Aylik mean train_monthly'den.
    """
    if train_metrics is None or train_monthly is None:
        return -1e9, "no-data"
    dd = train_metrics["dd"]  # negatif
    monthly_mean = train_monthly["mean"]
    if dd < dd_constraint:  # DD daha kotuyse (ornek -41 < -25)
        # kisit ihlali — ihlal buyuklugu ile orantili ceza
        penalty = (dd_constraint - dd) * 10.0  # her 1pp ihlal -10 puan
        return monthly_mean - penalty, "DD-VIOLATION"
    return monthly_mean, "OK"


def main():
    print("=" * 100, flush=True)
    print("LAB — 15m WIDE-STOP DD-PROFILE JOINT OPTIMIZATION", flush=True)
    print("Hedef: surekli-egri DD <= -25% KISITI altinda honest aylik ROI maks.", flush=True)
    print("=" * 100, flush=True)

    with POOL.open("rb") as f:
        pool_raw = pickle.load(f)
    h = hashlib.sha256()
    with POOL.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    print("[load] %s  sha256=%s  trades=%d" % (
        POOL.name, h.hexdigest()[:16], len(pool_raw)), flush=True)
    print("  date: %s -> %s" % (pool_raw[0]["entry_ts"], pool_raw[-1]["entry_ts"]),
          flush=True)

    base_cfg = ProductionConfig.from_yaml(str(YAML))

    # ========================================================================
    # PRE-RUN: honest pool inşası (3 maliyet senaryosu)
    # ========================================================================
    cost_pools = {}
    for bps in (45.0, 55.0, 65.0):
        cost_pools[bps] = build_pool(pool_raw, bps)
    print("\n[honest-cost pools built] +45bps (slippage 30 alt) / +55bps (baseline) "
          "/ +65bps (slippage 50 ust)", flush=True)

    # ========================================================================
    # BASELINE — Researcher continuous-curve dogrula (filtresiz + sl>=1.8/2.5)
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("BASELINE DOGRULAMA — surekli-egri (honest +55bps, default risk/throttle)",
          flush=True)
    print("=" * 100, flush=True)
    p55 = cost_pools[55.0]
    cfg_base = base_cfg.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0)
    for thr in (0.0, 0.018, 0.025):
        sub = [t for t in p55 if sl_pct_of(t) >= thr]
        m = continuous_metrics(sub, cfg_base)
        mo = monthly_on_curve(sub, cfg_base)
        tag = "FULL pool" if thr == 0 else "sl>=%.3f" % thr
        if m and mo:
            print("  %-12s n=%6d  cont-DD %+6.1f%%  sumR %+8.0f  WR %.1f%%  | "
                  "monthly mean %+6.2f%%  median %+6.2f%%  neg %d/%d" % (
                      tag, m["n"], m["dd"], m["sumR"], m["wr"],
                      mo["mean"], mo["median"], mo["neg"], mo["n"]), flush=True)

    # ========================================================================
    # JOINT GRID — sl_pct x risk% x DD-throttle (TRAIN penceresinde)
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("JOINT GRID OPTIMIZATION — TRAIN penceresi (2021-05 -> 2024-11)", flush=True)
    print("=" * 100, flush=True)

    train_raw, oos_raw = split_pool(pool_raw)
    print("  train: %d trade  |  OOS: %d trade  (split %s)" % (
        len(train_raw), len(oos_raw), TRAIN_END.date()), flush=True)

    # Parametre uzayi (pre-registered — asagidaki hipotez dosyasiyla birebir)
    SL_GRID = [0.018, 0.020, 0.022, 0.025, 0.030]
    RISK_GRID = [0.005, 0.0075, 0.010, 0.015, 0.020]
    # DD-throttle: (daily, weekly, monthly) uclu — gevsekten sikiya 4 kademe
    THROTTLE_GRID = [
        ("loose",  0.04, 0.08, 0.99),
        ("med",    0.03, 0.06, 0.20),
        ("tight",  0.025, 0.05, 0.12),
        ("vtight", 0.02, 0.04, 0.08),
    ]
    VT_GRID = [0.008, 0.010, 0.012]  # vol_target_atr_pct

    DD_CONSTRAINT = -25.0

    train55 = build_pool(train_raw, 55.0)
    # sl_pct alt-havuzlari onceden ayir (hiz)
    train_by_sl = {s: [t for t in train55 if sl_pct_of(t) >= s] for s in SL_GRID}

    results = []  # (params, train_metrics, train_monthly, score, status)
    n_trial = 0
    print("\n  grid: %d sl x %d risk x %d throttle x %d vt = %d kombinasyon" % (
        len(SL_GRID), len(RISK_GRID), len(THROTTLE_GRID), len(VT_GRID),
        len(SL_GRID) * len(RISK_GRID) * len(THROTTLE_GRID) * len(VT_GRID)),
        flush=True)
    print("  (TRAIN'de continuous_metrics + monthly_on_curve hesaplaniyor...)\n",
          flush=True)

    for sl in SL_GRID:
        sub_tr = train_by_sl[sl]
        for rpct in RISK_GRID:
            for tname, dd, wd, md in THROTTLE_GRID:
                for vt in VT_GRID:
                    n_trial += 1
                    params = {
                        "sl_thr": sl, "risk_pct": rpct, "throttle": tname,
                        "daily_dd": dd, "weekly_dd": wd, "monthly_dd": md,
                        "vol_target_atr_pct": vt,
                    }
                    cfg = make_cfg(base_cfg, params)
                    tm = continuous_metrics(sub_tr, cfg)
                    tmo = monthly_on_curve(sub_tr, cfg)
                    score, status = objective(tm, tmo, DD_CONSTRAINT)
                    results.append((params, tm, tmo, score, status))

    print("  %d trial tamamlandi.\n" % n_trial, flush=True)

    # DD kisitini saglayan adaylar (train continuous-DD >= -25%)
    feasible = [(p, tm, tmo, sc, st) for (p, tm, tmo, sc, st) in results
                if tm is not None and tm["dd"] >= DD_CONSTRAINT and tmo is not None]
    print("  DD<=-25%% kisitini TRAIN'de saglayan: %d / %d trial" % (
        len(feasible), n_trial), flush=True)

    feasible.sort(key=lambda x: x[3], reverse=True)

    print("\n  --- TRAIN feasible TOP-12 (DD kisiti OK, aylik mean'e gore) ---",
          flush=True)
    print("  %-7s %-6s %-7s %-6s | %8s %9s %8s %7s" % (
        "sl", "risk", "thr", "vt", "cont-DD", "mon-mean", "mon-med", "neg"),
        flush=True)
    for p, tm, tmo, sc, st in feasible[:12]:
        print("  %.3f  %.4f %-7s %.3f | %+7.1f%% %+8.2f%% %+7.2f%% %3d/%d" % (
            p["sl_thr"], p["risk_pct"], p["throttle"], p["vol_target_atr_pct"],
            tm["dd"], tmo["mean"], tmo["median"], tmo["neg"], tmo["n"]),
            flush=True)

    if not feasible:
        print("\n  *** TRAIN'de DD<=-25%% saglayan HICBIR kombinasyon YOK ***", flush=True)
        print("  -> wide-stop 15m DD<=-25%% kisiti altinda deploy edilemez.", flush=True)
        print("\n[done]", flush=True)
        return

    # ========================================================================
    # OOS DOGRULAMA — TRAIN top adaylari OOS penceresinde test et
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("OOS DOGRULAMA — TRAIN top-6 aday, OOS penceresi (2024-11 -> 2026-05)",
          flush=True)
    print("=" * 100, flush=True)

    oos55 = build_pool(oos_raw, 55.0)
    full55 = build_pool(pool_raw, 55.0)

    top_candidates = feasible[:6]
    oos_rows = []
    for i, (p, tm, tmo, sc, st) in enumerate(top_candidates):
        cfg = make_cfg(base_cfg, p)
        oos_sub = [t for t in oos55 if sl_pct_of(t) >= p["sl_thr"]]
        full_sub = [t for t in full55 if sl_pct_of(t) >= p["sl_thr"]]
        om = continuous_metrics(oos_sub, cfg)
        omo = monthly_on_curve(oos_sub, cfg)
        # tam-pool surekli-egri (5y) — KANONIK deploy DD
        fm = continuous_metrics(full_sub, cfg)
        fmo = monthly_on_curve(full_sub, cfg)
        wf = walk_forward(full_sub, cfg)
        oos_rows.append((p, tm, tmo, om, omo, fm, fmo, wf))
        print("\n  >>> Aday #%d: sl>=%.3f  risk=%.4f  throttle=%s  vt=%.3f" % (
            i + 1, p["sl_thr"], p["risk_pct"], p["throttle"],
            p["vol_target_atr_pct"]), flush=True)
        print("      TRAIN  cont-DD %+6.1f%%  monthly mean %+6.2f%%  neg %d/%d" % (
            tm["dd"], tmo["mean"], tmo["neg"], tmo["n"]), flush=True)
        if om and omo:
            print("      OOS    cont-DD %+6.1f%%  monthly mean %+6.2f%%  median "
                  "%+6.2f%%  neg %d/%d  sumR %+.0f" % (
                      om["dd"], omo["mean"], omo["median"], omo["neg"], omo["n"],
                      om["sumR"]), flush=True)
        else:
            print("      OOS    (yetersiz veri)", flush=True)
        if fm and fmo:
            print("      FULL5y cont-DD %+6.1f%%  monthly mean %+6.2f%%  median "
                  "%+6.2f%%  neg %d/%d  sumR %+.0f  CV %.0f%%" % (
                      fm["dd"], fmo["mean"], fmo["median"], fmo["neg"], fmo["n"],
                      fm["sumR"], fmo["cv"]), flush=True)
        if wf:
            print("      WF-OOS mean_ann %+8.1f%%  mean_dd %+6.1f%%  neg %d/%d  "
                  "r-adj %.2f" % (
                      wf["mean_annual"], wf["mean_dd"], wf["neg"], wf["windows"],
                      wf["r_adj"]), flush=True)

    # ========================================================================
    # MALIYET DUYARLILIK — best aday +45/+55/+65 bps
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("MALIYET DUYARLILIK — en iyi OOS-tutarlı aday, +45/+55/+65 bps", flush=True)
    print("=" * 100, flush=True)
    # OOS'ta DD<=-25 + monthly mean>0 olan adaylardan en iyisi
    best = None
    for (p, tm, tmo, om, omo, fm, fmo, wf) in oos_rows:
        if fm is None or fmo is None:
            continue
        # FULL 5y surekli-egri DD<=-25 ve OOS monthly mean pozitif
        if fm["dd"] >= DD_CONSTRAINT and omo is not None and omo["mean"] > 0:
            if best is None or fmo["mean"] > best[6]["mean"]:
                best = (p, tm, tmo, om, omo, fm, fmo, wf)
    if best is None:
        print("  *** OOS+FULL'da DD<=-25%% + pozitif aylik saglayan aday YOK ***",
              flush=True)
        # yine de en dusuk-DD adayi goster
        cand = [r for r in oos_rows if r[5] is not None]
        cand.sort(key=lambda r: r[5]["dd"], reverse=True)
        if cand:
            best = cand[0]
            print("  en yuksek-DD (en az kotu) aday gosteriliyor:", flush=True)
    if best:
        p = best[0]
        for bps in (45.0, 55.0, 65.0):
            cp = build_pool(pool_raw, bps)
            sub = [t for t in cp if sl_pct_of(t) >= p["sl_thr"]]
            cfg = make_cfg(base_cfg, p)
            m = continuous_metrics(sub, cfg)
            mo = monthly_on_curve(sub, cfg)
            if m and mo:
                print("  +%dbps  cont-DD %+6.1f%%  monthly mean %+6.2f%%  median "
                      "%+6.2f%%  neg %d/%d  sumR %+.0f" % (
                          int(bps), m["dd"], mo["mean"], mo["median"],
                          mo["neg"], mo["n"], m["sumR"]), flush=True)

    # ========================================================================
    # MULTIPLE-TESTING — Bonferroni + DSR
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("MULTIPLE-TESTING DISIPLINI", flush=True)
    print("=" * 100, flush=True)
    print("  toplam trial: %d  (grid search, deterministik)" % n_trial, flush=True)
    print("  Bonferroni alpha = 0.05 / %d = %.6f" % (n_trial, 0.05 / n_trial),
          flush=True)
    print("  -> bir adayin 'gercek edge' sayilmasi icin OOS p-value < %.6f olmali"
          % (0.05 / n_trial), flush=True)
    print("  DSR (Deflated Sharpe): N=%d deneme cok yuksek -> deflation agir." % n_trial,
          flush=True)
    print("  Anti-overfit asıl korunak: TRAIN'de secim + OOS'ta dogrulama (yukarida).",
          flush=True)
    print("  TRAIN->OOS aylik-mean tutarliligi (degradasyon) = gercek overfit metrigi.",
          flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
