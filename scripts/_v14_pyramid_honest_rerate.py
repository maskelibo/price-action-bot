"""v14 HONEST re-rate — pyramid OFF (canlı-gerçekçi) vs MFE-touch ON (backtest-iddiası).

Bağlam (2026-06-18): canlı v14 8 gündür koşuyor, pyramid 0/47 ateşledi. Neden = canlı
trigger bar-close mark snapshot (futures_daemon.py:3099/3102, 15m'de 1 kez), backtest
ise peak_R/MFE = bar-HIGH touch (engine.py:458, lab.py:734). Havuz yalnız R+peak_R
saklar → bar-close yolunu birebir simüle edemeyiz; ama canlı fill ~0 olduğu için
canlı-gerçekçi beklenti = pyramid OFF tabanı. Bu script o tabanı ve MFE-touch tavanını
v14 havuzu+config'iyle sayısallaştırır.

Adapted from scripts/ceo_pyramid_honest_replay.py (aynı muhasebe, v14 parametreleri).
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

POOL = ROOT / "data" / "pool_19sym_20260610.pkl"          # v14 frontier havuzu
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_v14p3.yaml"  # canlı v14 config
SLIP = 0.06
TR, SZ = (1.2, 1.8), (0.50, 0.30)   # v14 pyramid triggers/sizes (ae04b28 de-overlap)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def build_pool(pool, mode, triggers, sizes, fee_bps):
    """mode: 'off' (pyr yok) | 'honest' (MFE-touch, BE-protect YOK, gerçekçi tavan)
    | 'ideal' (MFE-touch + BE-protect clip, en iyimser)."""
    out = []
    for t in pool:
        t2 = dict(t)
        R = t["R"]
        pk = t.get("peak_R", R)
        ep = t["entry_price"]
        sl_pct = abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04
        fee_R = (fee_bps / (sl_pct * 10000.0)) if (fee_bps != 0.0 and sl_pct > 0) else 0.0
        if mode == "off":
            radj = R - fee_R
        elif mode in ("ideal", "honest"):
            clip = (mode == "ideal")
            radj = R
            for trig, sz in zip(triggers, sizes):
                if pk >= trig:   # MFE-touch: backtest varsayımı (bar HIGH 1.2R'a değdi)
                    contrib = max(0.0, R - trig) if clip else max(R - trig, -trig)
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
    if n == 0:
        return None
    mu = sum(rets) / n
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "annual": annual,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "worst_month_dd": worst_dd,
    }


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade" % len(pool), flush=True)
    base = ProductionConfig.from_yaml(str(YAML))
    cfg_off = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(), fee_bps_per_trade=0.0
    )
    scenarios = [
        ("OFF  pyramid yok = CANLI-GERCEKCI", "off"),
        ("ON-HONEST MFE-touch (BE yok)", "honest"),
        ("ON-IDEAL  MFE-touch + BE-protect", "ideal"),
    ]
    for fee in (0.0, 8.0):
        print("\n" + "=" * 84, flush=True)
        print("FEE = %+.0f bps/leg   v14 triggers=%s sizes=%s" % (fee, TR, SZ), flush=True)
        print("=" * 84, flush=True)
        print("%-36s%10s%9s%6s%6s%10s%9s" % (
            "senaryo", "annual", "mean", "pos", "neg", "maxloss", "wmDD"), flush=True)
        print("-" * 84, flush=True)
        res = {}
        for name, mode in scenarios:
            r = per_month(build_pool(pool, mode, TR, SZ, fee), cfg_off)
            res[name] = r
            if r:
                print("%-36s%+9.1f%%%+8.2f%%%6d%6d%+9.2f%%%+8.1f%%" % (
                    name, r["annual"], r["mean"], r["pos"], r["neg"],
                    r["max_loss"], r["worst_month_dd"]), flush=True)
        off = res["OFF  pyramid yok = CANLI-GERCEKCI"]
        hon = res["ON-HONEST MFE-touch (BE yok)"]
        if off and hon:
            print("\n  PYRAMID KATKISI (MFE-touch tavan): annual %+.1fpp (%.1f -> %.1f)" % (
                hon["annual"] - off["annual"], off["annual"], hon["annual"]), flush=True)
            print("  → Canlı 8g/47poz/0-fill: bu katki SIFIR; canlı beklenti = OFF satiri.", flush=True)


if __name__ == "__main__":
    main()
