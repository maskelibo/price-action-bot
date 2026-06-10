"""Frontier v3 — taze 19-sembol havuz, F2+F4 rejim filtreleri, risk x dd grid.

v2 bulgusu: P0(10sym)+F2+F4 r0.6 d03/w06 = +17.5/ay DD -19.5 (DD-OK en iyi).
v3: pool_19sym_20260610.pkl (4 strat x 19 sym, 2026-06-10 vintage) ile ayni
metodoloji. Adil kiyas icin 2021-05-16 oncesi trade'ler kirpilir (10-sym havuz
o tarihte basliyor; ZEC/XLM/FIL/NEAR 2020'ye uzaniyor -> ay-ortalama seyrelmesin).

Reproduce: ./.venv/bin/python scripts/research/frontier_v3_19sym.py
"""
from __future__ import annotations
import json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from frontier_20pct_sweep import HONEST_BPS, build_pool, fmt, replay_full, to_utc
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig

POOL19 = ROOT / "data" / "pool_19sym_20260610.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_frontier_v3_19sym.json"
CLIP_TS = datetime(2021, 5, 16, tzinfo=timezone.utc)


def main():
    print("[load] %s" % POOL19.name, flush=True)
    with POOL19.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP_TS]
    print("  pool (2021-05-16+ kirpilmis): %d trade" % len(raw), flush=True)

    pool = build_pool(raw, HONEST_BPS, pyramid=True)
    feats = btc_daily_features()
    sub, dropped = apply_filters(pool, feats, use_f2=True, use_f4=True)
    print("  F2+F4 drop: %s" % dropped, flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    rows = []
    print("\nFRONTIER v3 GRID (19sym, F2+F4, sl>=0.025, pyr-pool, +55bps)", flush=True)
    for risk in (0.004, 0.005, 0.006, 0.007, 0.008):
        for dlabel, daily, weekly in (("d02/w05", 0.02, 0.05), ("d03/w06", 0.03, 0.06)):
            cfg = base.with_overrides(
                fee_bps_per_trade=0.0, pyramid_enabled=False,
                pyramid_triggers=(), pyramid_sizes=(),
                sl_pct_min=0.025, risk_pct=risk,
                daily_dd=daily, weekly_dd=weekly,
            )
            res = replay_full(sub, cfg)
            if res is None:
                continue
            label = "P19 F2+F4 r%.1f%% %s" % (risk * 100, dlabel)
            rows.append((label, res))
    rows.sort(key=lambda x: x[1]["monthly_mean"], reverse=True)
    for label, res in rows:
        okf = "  <= DD-OK" if res["dd"] >= -20.0 else ""
        hit = " ***20%HEDEF***" if (res["dd"] >= -20.0 and res["monthly_mean"] >= 20.0) else ""
        print(fmt(label, res) + okf + hit, flush=True)

    # ===== ANTI-OVERFIT: train-pencere secimi (<=2024-11), OOS raporu =====
    print("\nTRAIN-SECIM (2021-05..2024-11) -> OOS (2024-12..2026-06) DOGRULAMA", flush=True)
    train_end = datetime(2024, 12, 1, tzinfo=timezone.utc)
    sub_train = [t for t in sub if to_utc(t["entry_ts"]) < train_end]
    sub_oos = [t for t in sub if to_utc(t["entry_ts"]) >= train_end]
    train_rows = []
    for risk in (0.004, 0.005, 0.006, 0.007, 0.008):
        for dlabel, daily, weekly in (("d02/w05", 0.02, 0.05), ("d03/w06", 0.03, 0.06)):
            cfg = base.with_overrides(
                fee_bps_per_trade=0.0, pyramid_enabled=False,
                pyramid_triggers=(), pyramid_sizes=(),
                sl_pct_min=0.025, risk_pct=risk,
                daily_dd=daily, weekly_dd=weekly,
            )
            tres = replay_full(sub_train, cfg)
            if tres is None or tres["dd"] < -20.0:
                continue
            train_rows.append(((risk, daily, weekly, dlabel), tres))
    if train_rows:
        train_rows.sort(key=lambda x: x[1]["monthly_mean"], reverse=True)
        (risk, daily, weekly, dlabel), tres = train_rows[0]
        cfg = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, risk_pct=risk,
            daily_dd=daily, weekly_dd=weekly,
        )
        ores = replay_full(sub_oos, cfg)
        print(fmt("TRAIN kazanan r%.1f%% %s" % (risk * 100, dlabel), tres), flush=True)
        print(fmt("  -> OOS (dokunulmamis 18 ay)", ores), flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool": str(POOL19), "clip": str(CLIP_TS),
        "grid": [{"label": l, **{k: v for k, v in r.items() if k != "rets"}}
                 for l, r in rows],
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
