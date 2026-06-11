"""Trade-sırası Monte Carlo ile MaxDD güven bandı (2026-06-11).

Sorun: tek backtest'in continuous-curve DD'si path-dependent TEK örneklem —
komşu parametrelerde −17..−24 oynadığını gördük ama hep nokta tahmin raporladık.
Çözüm: per-trade getiri dizisini yeniden örnekleyip DD DAĞILIMI çıkarmak.

İki mod (ikisi de raporlanır):
  - PURE shuffle: trade'ler tamamen karıştırılır — volatilite kümelenmesini
    kırar, DD'yi OLDUĞUNDAN İYİ gösterir → iyimser alt sınır.
  - WEEKLY-BLOCK bootstrap: takvim-haftası blokları yeniden örneklenir —
    kümelenme korunur → gerçekçi band. Karar bandı BUDUR.

Uygulama: v14p3 kazananı (5-strateji, wght+grimes, r0.75, thr, hardened 57bps).
Reproduce: ./.venv/bin/python scripts/research/mc_dd_band.py
"""
from __future__ import annotations
import json, os, pickle, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
import random

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from frontier_20pct_sweep import sl_pct_of, to_utc
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig, production_replay
from stability25_v2_5m_sleeve import W_FULL
import hardened_rebacktest_v14 as H

CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
N_SIM = 1000
SEED = 42  # reproduce edilebilirlik
OUT = ROOT / "reports" / "research" / "2026-06-11_mc_dd_band.json"


def max_dd(factors):
    """Per-trade çarpan dizisi -> max drawdown (negatif %)."""
    eq, peak, worst = 1.0, 1.0, 0.0
    for f in factors:
        eq *= f
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak
        if dd < worst:
            worst = dd
    return worst * 100


def main():
    base = ProductionConfig.from_yaml(str(ROOT / "configs" / "risk_phoenix_scalp_15m_v14p3.yaml"))
    feats = btc_daily_features()
    with open(ROOT / "data" / "pool_19sym_20260610.pkl", "rb") as f:
        raw_main = pickle.load(f)
    with open(ROOT / "data" / "pool_grimes_abc_15m.pkl", "rb") as f:
        raw_g = pickle.load(f)
    raw = [t for t in (raw_main + raw_g) if to_utc(t["entry_ts"]) >= CLIP]
    H.PYR_TRIG = (1.2, 1.8)
    pool = H.build_pool_hardened(raw, H.HONEST_BPS)
    sub, _ = apply_filters(pool, feats, use_f2=True, use_f4=True)
    sub = [t for t in sub if sl_pct_of(t) >= 0.025 and t["conf"] >= 0.25]
    W = dict(W_FULL)
    W["grimes_abc_pullback"] = 1.0
    for t in sub:
        t["risk_weight"] = W.get(t["strategy"], 1.0)
    sub = sorted(sub, key=lambda x: to_utc(x["entry_ts"]))

    def throttle(dt_, m_):
        def fn(e, p, c):
            return m_ if p > 0 and (p - e) / p >= dt_ else 1.0
        return fn

    cfg = base.with_overrides(
        fee_bps_per_trade=0.0, pyramid_enabled=False,
        pyramid_triggers=(), pyramid_sizes=(),
        sl_pct_min=0.0, conf_min=0.25, risk_pct=0.0075,
        daily_dd=0.04, weekly_dd=0.08,
        max_concurrent=16, max_same_side_concurrent=4,
        dynamic_exposure_fn=throttle(0.06, 0.5),
    )
    r = production_replay(sub, cfg)
    eq = r.equity_curve
    ts = r.entry_ts_list
    if len(eq) == len(ts) + 1:
        base_eq = eq[0]
        deltas = [eq[i + 1] / eq[i] for i in range(len(eq) - 1)]
    else:
        base_eq = 10000.0
        deltas = [eq[0] / base_eq] + [eq[i] / eq[i - 1] for i in range(1, len(eq))]
    orig_dd = max_dd(deltas)
    print(f"[orijinal] n_trade={len(deltas)}  contDD={orig_dd:+.1f}%  "
          f"(replay raporu: {r.max_drawdown*100:+.1f}%)", flush=True)

    rng = random.Random(SEED)

    # MOD 1 — pure shuffle (iyimser alt sınır)
    dds_pure = []
    for _ in range(N_SIM):
        d = deltas[:]
        rng.shuffle(d)
        dds_pure.append(max_dd(d))

    # MOD 2 — haftalık-blok bootstrap (kümelenme korunur, karar bandı)
    weeks = defaultdict(list)
    for t_ts, d in zip(ts, deltas):
        iso = to_utc(t_ts).isocalendar()
        weeks[(iso[0], iso[1])].append(d)
    blocks = list(weeks.values())
    dds_block = []
    for _ in range(N_SIM):
        sampled = [blocks[rng.randrange(len(blocks))] for _ in range(len(blocks))]
        d = [x for b in sampled for x in b]
        dds_block.append(max_dd(d))

    def pct(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(q * len(s)))]

    rows = []
    for label, dds in (("PURE-shuffle (iyimser)", dds_pure),
                       ("WEEKLY-block (karar bandı)", dds_block)):
        p5, p50, p95 = pct(dds, 0.05), pct(dds, 0.50), pct(dds, 0.95)
        worse = sum(1 for x in dds if x <= orig_dd) / len(dds) * 100
        print(f"  {label:28s} p5={p5:+.1f}  medyan={p50:+.1f}  p95={p95:+.1f}  "
              f"min={min(dds):+.1f}  | orijinalden kötü senaryo: %{worse:.0f}", flush=True)
        rows.append({"mode": label, "p5": p5, "p50": p50, "p95": p95,
                     "min": min(dds), "pct_worse_than_original": worse})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": "v14p3 5-strat r0.75 wght+thr hardened",
        "n_sim": N_SIM, "seed": SEED, "n_trades": len(deltas),
        "original_dd": orig_dd, "bands": rows,
    }, indent=2, default=str))
    print(f"\n[saved] {OUT}", flush=True)


if __name__ == "__main__":
    main()
