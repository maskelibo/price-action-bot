"""Lab — 15m wide-stop DD-opt deployable config: YILLIK KIRILIM.

DD-opt sweep'ten cikan deploy-edilebilir 15m config'inin backtest sonuclari,
yil-yil (2021..2026). Her yil bagimsiz $10k replay = o yilin honest ROI'si.
Iki maliyet senaryosu: +55bps taker (konservatif) + +15bps post-only (iyimser).

Reproduce: python scripts/lab_15m_widestop_yearly.py
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


def reblend(t, nc):
    R, pk = t["R"], t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = nc
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        return c1n * TP1_R + (1.0 - c1n) * ((R - c1o * TP1_R) / (1.0 - c1o))
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    return R if R_run > pk else c1n * TP1_R + c2n * TP2_R + crn * R_run


def build_pool(pool, extra_bps):
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend(t, LIVE_CLOSE)
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


def months_of(trades):
    """Yil ici aylik getiriler (her ay bagimsiz $10k)."""
    if not trades:
        return []
    trades = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(trades[0]["entry_ts"]), to_utc(trades[-1]["entry_ts"])
    out, cy, cm = [], start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        m_tr = [t for t in trades if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) >= 10:
            r = production_replay(m_tr, CFG_HOLDER[0])
            if r is not None:
                out.append(r.total_return * 100)
        cm = (cm % 12) + 1
        cy += (cm == 1)
    return out


CFG_HOLDER = [None]


def yearly(pool_built, thr, cfg, label):
    sub = [t for t in pool_built if sl_pct_of(t) >= thr]
    CFG_HOLDER[0] = cfg
    by_year = {}
    for t in sub:
        y = to_utc(t["entry_ts"]).year
        by_year.setdefault(y, []).append(t)
    print("\n  %s  (sl>=%.3f, n=%d trade, %d yil)" % (label, thr, len(sub), len(by_year)), flush=True)
    print("  %-6s %8s %10s %9s %9s %10s" % (
        "Yil", "n-trade", "ROI(yil)", "DD", "neg-ay", "ay-mean"), flush=True)
    print("  " + "-" * 60, flush=True)
    comp = 1.0
    for y in sorted(by_year):
        yr = sorted(by_year[y], key=lambda x: to_utc(x["entry_ts"]))
        r = production_replay(yr, cfg)
        if r is None:
            continue
        roi = r.total_return * 100
        dd = r.max_drawdown * 100
        mrets = months_of(yr)
        negm = sum(1 for x in mrets if x < 0)
        mmean = sum(mrets) / len(mrets) if mrets else 0.0
        comp *= (1 + roi / 100)
        print("  %-6d %8d %+9.1f%% %+8.1f%% %5d/%-2d %+9.2f%%" % (
            y, len(yr), roi, dd, negm, len(mrets), mmean), flush=True)
    n_full = len(by_year)
    cagr = (comp ** (1.0 / n_full) - 1) * 100 if n_full else 0
    print("  " + "-" * 60, flush=True)
    print("  %d yil compound: x%.1f  |  yil-bazli CAGR ~%+.0f%%/yil "
          "(2021 ve 2026 kismi yil)" % (n_full, comp, cagr), flush=True)


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    base = ProductionConfig.from_yaml(str(YAML))
    print("  pool: %d trade  %s -> %s" % (
        len(pool), to_utc(pool[0]["entry_ts"]).date(),
        to_utc(pool[-1]["entry_ts"]).date()), flush=True)

    print("\n" + "=" * 72, flush=True)
    print("15m WIDE-STOP DD-OPT — YILLIK KIRILIM (honest backtest)", flush=True)
    print("=" * 72, flush=True)

    # Konservatif: taker +55bps, sl>=0.025, risk 0.5%, dd-tight d02/w05
    cfg_cons = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0, risk_pct=0.005, daily_dd=0.02, weekly_dd=0.05)
    yearly(build_pool(pool, 55.0), 0.025, cfg_cons,
           "KONSERVATIF — taker +55bps, risk %0.5, dd d02/w05")

    # Iyimser: post-only +15bps, sl>=0.025, risk 0.8%, dd-tight d03/w06
    cfg_opt = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0, risk_pct=0.008, daily_dd=0.03, weekly_dd=0.06)
    yearly(build_pool(pool, 15.0), 0.025, cfg_opt,
           "IYIMSER — post-only +15bps, risk %0.8, dd d03/w06")

    print("\n  NOT: 'ROI(yil)' = o yilin bagimsiz $10k replay'i (yil ici compound).", flush=True)
    print("  2021 (May-Ara) ve 2026 (Oca-May) KISMI yil — tam yil degil.", flush=True)
    print("  ay-mean = yil ici bagimsiz aylik replay ortalamasi (beklenti metrigi).", flush=True)
    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
