"""Lab — 15m wide-stop honest edge: DD-optimizasyon.

GOREV (P0): Researcher'in wide-stop edge'i (sl_pct>=0.018, honest aylik-mean
+21.72%) surekli-egri DD -41% ile deploy edilemiyor. sl_pct esigi x risk_pct x
DD-throttle joint sweep -> surekli-egri DD <= -25% kisitinda honest aylik ROI'yi
maksimize et.

Metodoloji: Researcher'in researcher_15m_honest_edge_hunt.py'si ile birebir
(build_pool honest cost + reblend + pyramid IDEAL; per_month engine replay).
Yenilik: continuous_replay — tum havuz tek seferde -> surekli equity-egri DD.

Faz 1: continuous replay sweep (hizli, 1 replay/config) -> DD <= 25% survivor'lar.
Faz 2: survivor'larda per_month -> honest aylik mean.

market.duckdb DOKUNULMADI — pool pkl R-bazli honest replay.
Reproduce: python scripts/lab_15m_widestop_dd_opt.py
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"

SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)


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


def build_pool(pool, extra_bps, reblend=True):
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE) if reblend else t["R"]
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


def continuous_replay(pool, cfg):
    """Tum havuz tek seferde -> surekli equity-egri. DD = gercek deploy DD."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if len(pool) < 30:
        return None
    span_days = (to_utc(pool[-1]["exit_ts"]) - to_utc(pool[0]["entry_ts"])).days
    years = max(span_days / 365.0, 0.1)
    r = production_replay(pool, cfg)
    if r is None:
        return None
    return {
        "total_return": r.total_return * 100,
        "annual": r.annualized(years) * 100,
        "dd": r.max_drawdown * 100,
        "years": years,
    }


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
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
    rets = []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            continue
        rets.append(r.total_return * 100)
    n = len(rets)
    if n == 0:
        return None
    mu = sum(rets) / n
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100
    srt = sorted(rets, reverse=True)
    comp5 = 1.0
    for x in srt[5:]:
        comp5 *= (1 + x / 100)
    annual5 = (comp5 ** (12.0 / max(len(srt) - 5, 1)) - 1) * 100
    return {
        "n": n, "mean": mu, "median": sorted(rets)[n // 2], "annual": annual,
        "annual_ex_top5": annual5,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets),
    }


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade\n" % len(pool), flush=True)

    base = ProductionConfig.from_yaml(str(YAML))

    # Honest cost: +55bps taker (konservatif primary) + +15bps post-only
    pools = {55: build_pool(pool, 55.0), 15: build_pool(pool, 15.0)}

    # ===== FAZ 1: continuous replay sweep =====
    print("=" * 122, flush=True)
    print("FAZ 1 — CONTINUOUS-EGRI SWEEP (surekli 5y replay, DD = gercek deploy DD)", flush=True)
    print("=" * 122, flush=True)
    sl_thrs = [0.018, 0.025]
    risks = [0.005, 0.0075, 0.01, 0.015, 0.02]
    dd_sets = [
        ("dd-base d04/w08", dict(daily_dd=0.04, weekly_dd=0.08)),
        ("dd-tight d03/w06", dict(daily_dd=0.03, weekly_dd=0.06)),
        ("dd-tight d02/w05", dict(daily_dd=0.02, weekly_dd=0.05)),
        ("dd+eqprot30 d03/w06", dict(daily_dd=0.03, weekly_dd=0.06, equity_protect_30=True)),
    ]
    survivors = []
    rows = []
    for bps in (55, 15):
        for thr in sl_thrs:
            sub = [t for t in pools[bps] if sl_pct_of(t) >= thr]
            for risk in risks:
                for dlabel, dd in dd_sets:
                    cfg = base.with_overrides(
                        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
                        fee_bps_per_trade=0.0, risk_pct=risk, **dd,
                    )
                    cr = continuous_replay(sub, cfg)
                    if cr is None:
                        continue
                    key = (bps, thr, risk, dlabel)
                    rows.append((key, cr, len(sub), cfg))
                    ok = cr["dd"] >= -25.0
                    rows[-1] = (key, cr, len(sub), cfg, ok)
                    if ok:
                        survivors.append((key, cr, len(sub), cfg))
    rows.sort(key=lambda x: x[1]["annual"], reverse=True)
    print("  %-44s %6s %9s %8s %9s" % ("config", "n", "tot%", "annual%", "DD%"), flush=True)
    for key, cr, n, cfg, ok in rows:
        bps, thr, risk, dlabel = key
        flag = "  <= DD-OK" if ok else ""
        print("  +%2dbps sl>=%.3f risk%.1f%% %-20s %6d %+8.0f %+8.1f %+8.1f%s" % (
            bps, thr, risk * 100, dlabel, n, cr["total_return"],
            cr["annual"], cr["dd"], flag), flush=True)

    # ===== FAZ 2: per-month on DD<=25% survivors =====
    print("\n" + "=" * 122, flush=True)
    print("FAZ 2 — PER-MONTH (honest aylik ROI) — yalniz DD<=-25%% survivor'lar", flush=True)
    print("=" * 122, flush=True)
    if not survivors:
        print("  HIC SURVIVOR YOK — DD<=-25%% kisitini saglayan config bulunamadi.", flush=True)
    else:
        survivors.sort(key=lambda x: x[1]["annual"], reverse=True)
        best = None
        for key, cr, n, cfg in survivors:
            bps, thr, risk, dlabel = key
            sub = [t for t in pools[bps] if sl_pct_of(t) >= thr]
            pm = per_month(sub, cfg)
            if pm is None:
                continue
            tag = "+%dbps sl>=%.3f risk%.1f%% %s" % (bps, thr, risk * 100, dlabel)
            print("  %-50s contDD %+6.1f%% | aylik-mean %+6.2f%% med %+6.2f%% "
                  "neg %2d/%d exTop5-ann %+8.1f%% maxL %+6.2f%%" % (
                      tag, cr["dd"], pm["mean"], pm["median"], pm["neg"], pm["n"],
                      pm["annual_ex_top5"], pm["max_loss"]), flush=True)
            score = pm["mean"] if pm["mean"] else -1e9
            if best is None or score > best[0]:
                best = (score, tag, cr, pm)
        if best:
            print("\n  >>> EN IYI (DD<=-25%% kisitinda aylik-mean max):", flush=True)
            _, tag, cr, pm = best
            print("      %s" % tag, flush=True)
            print("      continuous DD %+.1f%%  | honest aylik-mean %+.2f%%  medyan %+.2f%%  "
                  "neg %d/%d  exTop5-annual %+.1f%%" % (
                      cr["dd"], pm["mean"], pm["median"], pm["neg"], pm["n"],
                      pm["annual_ex_top5"]), flush=True)
            verdict = "HEDEF TUTAR" if pm["mean"] >= 10.0 else "HEDEF ALTI"
            print("      HUKUM: aylik-mean %+.2f%% vs hedef %%10 -> %s" % (pm["mean"], verdict), flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
