"""CEO sprint - HONEST pyramid accounting replay (BE-protect varsayimi KALDIRILDI)."""
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
SLIP = 0.06


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def build_pool(pool, mode, triggers, sizes, fee_bps):
    out = []
    for t in pool:
        t2 = dict(t)
        R = t["R"]
        pk = t["peak_R"]
        sl_pct = abs(t["initial_sl"] - t["entry_price"]) / t["entry_price"] if t["entry_price"] > 0 else 0.04
        fee_R = (fee_bps / (sl_pct * 10000.0)) if (fee_bps != 0.0 and sl_pct > 0) else 0.0
        if mode == "off":
            radj = R - fee_R
        elif mode in ("ideal", "honest"):
            clip = (mode == "ideal")
            radj = R
            for trig, sz in zip(triggers, sizes):
                if pk >= trig:
                    contrib = max(0.0, R - trig) if clip else max(R - trig, -trig)
                    radj += sz * contrib - SLIP * sz - fee_R * sz
            radj -= fee_R
        elif mode in ("B-ideal", "B-honest"):
            TRAIL_EFF = 0.55
            base_new = max(R, R + TRAIL_EFF * (pk - R)) if pk >= 1.0 else R
            clip = (mode == "B-ideal")
            radj = base_new
            for trig, sz in zip(triggers, sizes):
                if pk >= trig:
                    contrib = max(0.0, base_new - trig) if clip else max(base_new - trig, -trig)
                    radj += sz * contrib - SLIP * sz - fee_R * sz
            radj -= fee_R
        else:
            raise ValueError(mode)
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


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade" % len(pool), flush=True)
    base = ProductionConfig.from_yaml(str(YAML))
    TR, SZ = (1.0, 1.5), (0.5, 0.3)
    cfg_off = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(), fee_bps_per_trade=0.0
    )
    scenarios = [
        ("F   pyramid OFF (baseline)", "off"),
        ("CUR-IDEAL  (lab.py BE-protect)", "ideal"),
        ("CUR-HONEST (BE YOK, gercek)", "honest"),
        ("B-IDEAL pyr-aware exit (ideal)", "B-ideal"),
        ("B-HONEST pyr-aware exit (gercek)", "B-honest"),
    ]
    for fee in (0.0, 8.0):
        print("\n" + "=" * 94, flush=True)
        print("FEE = %+.0f bps   (HONEST pyramid muhasebe)" % fee, flush=True)
        print("=" * 94, flush=True)
        hdr = "%-36s%11s%9s%8s%6s%10s%9s%7s" % ("senaryo","annual","mean","r-adj","neg","maxloss","wmDD","CV")
        print(hdr, flush=True)
        print("-" * 94, flush=True)
        results = {}
        for name, mode in scenarios:
            p2 = build_pool(pool, mode, TR, SZ, fee)
            r = per_month(p2, cfg_off)
            results[name] = r
            print("%-36s%+10.1f%%%+8.2f%%%8.2f%6d%+9.2f%%%+8.1f%%%6.0f%%" % (
                name, r["annual"], r["mean"], r["r_adj"], r["neg"],
                r["max_loss"], r["worst_month_dd"], r["cv"]), flush=True)
        ci = results["CUR-IDEAL  (lab.py BE-protect)"]
        ch = results["CUR-HONEST (BE YOK, gercek)"]
        f0 = results["F   pyramid OFF (baseline)"]
        bh = results["B-HONEST pyr-aware exit (gercek)"]
        print("\n  IDEAL -> HONEST sapma (lab.py sismesi): annual %+.1fpp  r-adj %+.1f" % (
            ci["annual"] - ch["annual"], ci["r_adj"] - ch["r_adj"]), flush=True)
        print("  HONEST pyramid vs F baseline:           annual %+.1fpp  r-adj %+.1f  neg %+d" % (
            ch["annual"] - f0["annual"], ch["r_adj"] - f0["r_adj"], ch["neg"] - f0["neg"]), flush=True)
        print("  B-HONEST vs CUR-HONEST:                 annual %+.1fpp  r-adj %+.1f  neg %+d" % (
            bh["annual"] - ch["annual"], bh["r_adj"] - ch["r_adj"], bh["neg"] - ch["neg"]), flush=True)


if __name__ == "__main__":
    main()
