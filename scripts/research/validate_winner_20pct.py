"""Kazanan config sağlamlık bataryası — r0.62 d04/w08 (P19 F2+F4 sl>=0.025).

1. TRAIN-SEÇİM: tüm keşfedilen grid (risk x dd x conf) YALNIZ train (<=2024-11)
   metrikleriyle seçilir (DD>=-20 train kısıtı) -> dokunulmamış OOS raporu.
2. Maliyet duyarlılığı: +45 / +55 / +65 bps.
3. Komşu platosu: r±0.04, dd komşuları (zaten taranmış; burada özetlenir).
4. Yıl kırılımı + ex-top5% ay + winner-skew.
5. Sembol-çıkarma: en büyük 5 sembol tek tek düşürülür.

Reproduce: ./.venv/bin/python scripts/research/validate_winner_20pct.py
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from frontier_20pct_sweep import (
    HONEST_BPS, build_pool, fmt, monthly_stats, replay_full, to_utc,
)
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig, production_replay

POOL19 = ROOT / "data" / "pool_19sym_20260610.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_winner_validation.json"
CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
TRAIN_END = datetime(2024, 12, 1, tzinfo=timezone.utc)

WIN = dict(risk=0.0062, daily=0.04, weekly=0.08)


def mkcfg(base, risk, daily, weekly, conf=0.25, sl=0.025):
    return base.with_overrides(
        fee_bps_per_trade=0.0, pyramid_enabled=False,
        pyramid_triggers=(), pyramid_sizes=(),
        sl_pct_min=sl, conf_min=conf, risk_pct=risk,
        daily_dd=daily, weekly_dd=weekly,
    )


def main():
    with POOL19.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP]
    feats = btc_daily_features()
    base = ProductionConfig.from_yaml(str(YAML))
    payload = {}

    pool55 = build_pool(raw, HONEST_BPS, pyramid=True)
    sub55, _ = apply_filters(pool55, feats, use_f2=True, use_f4=True)
    sub55_train = [t for t in sub55 if to_utc(t["entry_ts"]) < TRAIN_END]
    sub55_oos = [t for t in sub55 if to_utc(t["entry_ts"]) >= TRAIN_END]

    # ===== 1. TRAIN-SECIM (kesfedilen tam grid) -> OOS =====
    print("1) TRAIN-SECIM (<=2024-11, DD>=-20 kisiti) -> dokunulmamis OOS", flush=True)
    grid = []
    for risk in (0.004, 0.005, 0.0055, 0.0058, 0.006, 0.0062, 0.0065, 0.007, 0.008):
        for daily, weekly in ((0.02, 0.05), (0.03, 0.06), (0.035, 0.07),
                              (0.04, 0.07), (0.04, 0.08), (0.045, 0.085)):
            grid.append((risk, daily, weekly))
    best = None
    for risk, daily, weekly in grid:
        tres = replay_full(sub55_train, mkcfg(base, risk, daily, weekly))
        if tres is None or tres["dd"] < -20.0:
            continue
        if best is None or tres["monthly_mean"] > best[1]["monthly_mean"]:
            best = ((risk, daily, weekly), tres)
    (risk, daily, weekly), tres = best
    ores = replay_full(sub55_oos, mkcfg(base, risk, daily, weekly))
    print(fmt("TRAIN kazanan r%.2f%% d%g/w%g" % (risk * 100, daily, weekly), tres), flush=True)
    print(fmt("  -> OOS (2024-12..2026-06)", ores), flush=True)
    payload["train_select"] = {"params": [risk, daily, weekly],
                               "train": {k: v for k, v in tres.items() if k != "rets"},
                               "oos": {k: v for k, v in ores.items() if k != "rets"}}

    # ===== 2. Maliyet duyarliligi (kazanan r0.62 d04/w08) =====
    print("\n2) MALIYET DUYARLILIGI (r0.62 d04/w08)", flush=True)
    payload["cost_sens"] = {}
    for bps in (45.0, 55.0, 65.0):
        p = build_pool(raw, bps, pyramid=True)
        s, _ = apply_filters(p, feats, use_f2=True, use_f4=True)
        res = replay_full(s, mkcfg(base, **WIN))
        print(fmt("+%dbps" % bps, res), flush=True)
        payload["cost_sens"][int(bps)] = {k: v for k, v in res.items() if k != "rets"}

    # ===== 3. Yil kirilimi + skew (kazanan) =====
    print("\n3) YIL KIRILIMI + SKEW (r0.62 d04/w08, +55bps)", flush=True)
    cfg = mkcfg(base, **WIN)
    sub_sorted = sorted(sub55, key=lambda x: to_utc(x["entry_ts"]))
    r = production_replay(sub_sorted, cfg)
    ms = monthly_stats(r.entry_ts_list, r.equity_curve)
    months = sorted({(to_utc(t).year, to_utc(t).month) for t in r.entry_ts_list})
    by_year = defaultdict(list)
    for (y, m), ret in zip(months, ms["rets"]):
        by_year[y].append(ret)
    for y in sorted(by_year):
        v = by_year[y]
        print("  %d: %+6.2f%%/ay  neg %d/%d  worst %+6.2f" % (
            y, sum(v) / len(v), sum(1 for x in v if x < 0), len(v), min(v)), flush=True)
    srt = sorted(ms["rets"], reverse=True)
    ex5 = srt[max(1, round(len(srt) * 0.05)):]
    print("  ex-top5%% ay ortalamasi: %+.2f (tum: %+.2f)" % (
        sum(ex5) / len(ex5), ms["mean"]), flush=True)
    payload["yearly"] = {str(y): sum(v) / len(v) for y, v in by_year.items()}
    payload["ex_top5_mean"] = sum(ex5) / len(ex5)

    # ===== 4. Sembol-cikarma (en buyuk 5) =====
    print("\n4) SEMBOL-CIKARMA (en cok trade'li 5 sembol tek tek dusuruldu)", flush=True)
    cnt = defaultdict(int)
    for t in sub55:
        cnt[t["symbol"]] += 1
    top5 = [s for s, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:5]]
    payload["symbol_out"] = {}
    for sym in top5:
        s2 = [t for t in sub55 if t["symbol"] != sym]
        res = replay_full(s2, cfg)
        print(fmt("  -%s" % sym, res), flush=True)
        payload["symbol_out"][sym] = {k: v for k, v in res.items() if k != "rets"}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "winner": WIN, **payload,
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
