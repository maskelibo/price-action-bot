"""Frontier sweep — hedef: dürüst aylık ROI >= %20, continuous DD <= %20.

Metodoloji lab_15m_widestop_dd_opt.py ile birebir: vsa2_top4 pool + honest
+55bps + LIVE_CLOSE reblend + production_replay. Faz 0 champion kalibrasyonu
(beklenen: ~+13%/ay, DD ~-15.5%, n~4457), Faz 1 grid sweep, Faz 2 survivor
OOS (son 18 ay) raporu.

Reproduce: ./.venv/bin/python scripts/research/frontier_20pct_sweep.py
"""
from __future__ import annotations
import io, json, os, pickle, sys
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11_vsa2_top4.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_frontier_20pct_sweep.json"

# Honest cost sabitleri (lab_15m_widestop_dd_opt.py birebir)
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)
HONEST_BPS = 55.0
OOS_MONTHS = 18


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


def build_pool(pool, extra_bps, pyramid=False):
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE)
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        if pyramid:
            for trig, sz in zip(PYR_TRIG, PYR_SIZE):
                if pk >= trig:
                    radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
                    radj -= extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


def monthly_stats(entry_ts, equity):
    """Continuous equity curve -> ay-sonu equity -> aylık return istatistikleri."""
    if not entry_ts or not equity:
        return None
    if len(equity) == len(entry_ts) + 1:
        equity = equity[1:]  # eq_curve[0] = initial_capital
    if len(entry_ts) != len(equity):
        return None
    month_last = {}
    for ts, eq in zip(entry_ts, equity):
        ts = to_utc(ts)
        month_last[(ts.year, ts.month)] = eq
    keys = sorted(month_last)
    rets = []
    prev = 10000.0
    for k in keys:
        eq = month_last[k]
        rets.append((eq / prev - 1.0) * 100)
        prev = eq
    n = len(rets)
    if n == 0:
        return None
    mu = sum(rets) / n
    return {
        "n_months": n,
        "mean": mu,
        "median": sorted(rets)[n // 2],
        "neg": sum(1 for x in rets if x < 0),
        "worst": min(rets),
        "best": max(rets),
        "rets": rets,
    }


def replay_full(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    r = production_replay(pool, cfg)
    if r is None or not r.equity_curve:
        return None
    ms = monthly_stats(r.entry_ts_list, r.equity_curve)
    if ms is None:
        return None
    # OOS: son OOS_MONTHS ayın return'leri
    oos = ms["rets"][-OOS_MONTHS:]
    return {
        "n_trades": r.trades,
        "dd": r.max_drawdown * 100,
        "total_return": r.total_return * 100,
        "monthly_mean": ms["mean"],
        "monthly_median": ms["median"],
        "neg_months": ms["neg"],
        "n_months": ms["n_months"],
        "worst_month": ms["worst"],
        "oos_mean": sum(oos) / len(oos) if oos else None,
        "oos_neg": sum(1 for x in oos if x < 0),
    }


def fmt(label, res):
    if res is None:
        return "  %-52s   (replay bos)" % label
    return ("  %-52s n=%5d  ay%%=%+6.2f  med=%+6.2f  DD=%+6.1f  neg=%d/%d "
            "worst=%+6.2f  OOS%%=%+6.2f oneg=%d") % (
        label, res["n_trades"], res["monthly_mean"], res["monthly_median"],
        res["dd"], res["neg_months"], res["n_months"], res["worst_month"],
        res["oos_mean"], res["oos_neg"])


def main():
    print("[load] %s" % POOL.name, flush=True)
    with POOL.open("rb") as f:
        raw_pool = pickle.load(f)
    print("  pool: %d trade" % len(raw_pool), flush=True)

    base = ProductionConfig.from_yaml(str(YAML))

    # ===== FAZ 0: champion kalibrasyon =====
    print("\nFAZ 0 — CHAMPION KALIBRASYON (hedef: ay%~13.1, DD~-15.5, n~4457)", flush=True)
    results = {}
    pools = {}
    for pyr in (False, True):
        pools[pyr] = build_pool(raw_pool, HONEST_BPS, pyramid=pyr)
        for sl_thr in (0.018, 0.025):
            cfg = base.with_overrides(
                fee_bps_per_trade=0.0, pyramid_enabled=False,
                pyramid_triggers=(), pyramid_sizes=(),
                sl_pct_min=sl_thr, risk_pct=0.005,
            )
            res = replay_full(pools[pyr], cfg)
            label = "champ pyr=%d sl>=%.3f r0.5%%" % (pyr, sl_thr)
            print(fmt(label, res), flush=True)
            results[label] = res
    pool55 = pools[False]

    # ===== FAZ 1: frontier grid =====
    print("\nFAZ 1 — FRONTIER GRID (kisit: DD>=-20%%; hedef ay%%>=20)", flush=True)
    risks = (0.005, 0.006, 0.007, 0.008, 0.009, 0.010, 0.012, 0.015)
    sl_thrs = (0.018, 0.025)
    dd_sets = (
        ("ddchamp d02/w05", dict(daily_dd=0.02, weekly_dd=0.05)),
        ("ddmid   d03/w06", dict(daily_dd=0.03, weekly_dd=0.06)),
        ("ddbase  d04/w08", dict(daily_dd=0.04, weekly_dd=0.08)),
    )
    rows = []
    for sl_thr in sl_thrs:
        for risk in risks:
            for dlabel, dd in dd_sets:
                cfg = base.with_overrides(
                    fee_bps_per_trade=0.0, pyramid_enabled=False,
                    pyramid_triggers=(), pyramid_sizes=(),
                    sl_pct_min=sl_thr, risk_pct=risk, **dd,
                )
                res = replay_full(pool55, cfg)
                if res is None:
                    continue
                label = "sl>=%.3f r%.1f%% %s" % (sl_thr, risk * 100, dlabel)
                rows.append((label, res))
    rows.sort(key=lambda x: x[1]["monthly_mean"], reverse=True)
    for label, res in rows:
        ok = "  <= DD-OK" if res["dd"] >= -20.0 else ""
        hit = " ***20%HEDEF***" if (res["dd"] >= -20.0 and res["monthly_mean"] >= 20.0) else ""
        print(fmt(label, res) + ok + hit, flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool": str(POOL), "yaml": str(YAML), "honest_bps": HONEST_BPS,
        "calibration": results,
        "grid": [{"label": l, **{k: v for k, v in r.items() if k != "rets"}} for l, r in rows],
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
