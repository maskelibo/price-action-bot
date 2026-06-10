"""Grimes ABC two-leg pullback — DÜRÜST değerlendirme (hardened_rebacktest_v14 deseni).

İlk geçiş: pyramid YOK, reblend YOK, +57bps honest cost, widestop sl>=0.025 &
conf>=0.25. Ay-bağımsız taze-$10k fixed-notional aylık ROI ort + continuous
compounding DD. Train(2021-05..2024-11) / OOS(2024-12+) ayrı. 15m + 4h.

Kullanım: ./.venv/bin/python scripts/research/eval_grimes_abc.py
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

from frontier_20pct_sweep import sl_pct_of, to_utc
from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_v14_frontier.yaml"
CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
OOS_START = datetime(2024, 12, 1, tzinfo=timezone.utc)
HONEST_BPS = 57.0
INITIAL = 10_000.0
RISK_KW = dict(risk_pct=0.0062, daily_dd=0.04, weekly_dd=0.08)


def honest_pool(pool):
    """+57bps R-düşümü, widestop filtresi (sl>=0.025 & conf>=0.25). Pyramid/reblend YOK."""
    out = []
    for t in pool:
        slp = sl_pct_of(t)
        if slp < 0.025 or t["conf"] < 0.25:
            continue
        t2 = dict(t)
        extra_R = (HONEST_BPS / (slp * 10000.0)) if slp > 0 else 0.0
        t2["R"] = t["R"] - extra_R
        out.append(t2)
    return sorted(out, key=lambda x: to_utc(x["entry_ts"]))


def per_month_independent(sub, cfg):
    """Ay-bağımsız taze-$10k fixed-notional replay (repo dürüst ROI başlığı)."""
    if not sub:
        return [], []
    start, end = to_utc(sub[0]["entry_ts"]), to_utc(sub[-1]["entry_ts"])
    cy, cm = start.year, start.month
    rets, keys = [], []
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        m_tr = [t for t in sub if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) >= 10:
            r = production_replay(m_tr, cfg)
            if r is not None:
                rets.append((r.final_equity - INITIAL) / INITIAL * 100)
                keys.append((cy, cm))
        cm = (cm % 12) + 1
        if cm == 1:
            cy += 1
    return keys, rets


def eval_pool(tag, pool, base):
    raw = [t for t in pool if to_utc(t["entry_ts"]) >= CLIP]
    sub = honest_pool(raw)
    cfg_fix = base.with_overrides(
        fee_bps_per_trade=0.0, pyramid_enabled=False,
        pyramid_triggers=(), pyramid_sizes=(),
        sl_pct_min=0.025, conf_min=0.25,
        fixed_notional_sizing=True, **RISK_KW,
    )
    # continuous-compounding DD (tek akış)
    r_full = production_replay(sub, cfg_fix)
    keys, rets = per_month_independent(sub, cfg_fix)
    n = len(rets)
    oos_pairs = [(k, ret) for k, ret in zip(keys, rets)
                 if datetime(k[0], k[1], 1, tzinfo=timezone.utc) >= OOS_START]
    tr_pairs = [(k, ret) for k, ret in zip(keys, rets)
                if datetime(k[0], k[1], 1, tzinfo=timezone.utc) < OOS_START]
    oos = [r for _, r in oos_pairs]
    tr = [r for _, r in tr_pairs]
    res = {
        "tf": tag,
        "n_trades_widestop": len(sub),
        "n_months": n,
        "monthly_mean": sum(rets) / n if n else None,
        "monthly_median": sorted(rets)[n // 2] if n else None,
        "neg_months": sum(1 for x in rets if x < 0),
        "worst_month": min(rets) if rets else None,
        "best_month": max(rets) if rets else None,
        "train_mean": sum(tr) / len(tr) if tr else None,
        "train_n": len(tr),
        "oos_mean": sum(oos) / len(oos) if oos else None,
        "oos_n": len(oos),
        "oos_neg": sum(1 for x in oos if x < 0),
        "continuous_dd_pct": r_full.max_drawdown * 100 if r_full else None,
        "monthly_returns": {f"{k[0]}-{k[1]:02d}": round(v, 3) for k, v in zip(keys, rets)},
    }
    print(("[%s] n_ws=%d months=%d  ay%%=%+.2f med=%+.2f  neg=%d/%d worst=%+.2f best=%+.2f  "
           "TRAIN=%+.2f(n=%d) OOS=%+.2f(n=%d oneg=%d)  contDD=%+.1f") % (
        tag, res["n_trades_widestop"], n, res["monthly_mean"], res["monthly_median"],
        res["neg_months"], n, res["worst_month"], res["best_month"],
        res["train_mean"], res["train_n"], res["oos_mean"] or 0, res["oos_n"], res["oos_neg"],
        res["continuous_dd_pct"]), flush=True)
    return res, keys, rets


def main():
    base = ProductionConfig.from_yaml(str(YAML))
    results = {}
    monthly_15m = None
    for tag in ["15m", "4h"]:
        pool = pickle.load(open(ROOT / "data" / f"pool_grimes_abc_{tag}.pkl", "rb"))
        res, keys, rets = eval_pool(tag, pool, base)
        results[tag] = res
        if tag == "15m":
            monthly_15m = dict(zip([f"{k[0]}-{k[1]:02d}" for k in keys], rets))

    # ===== Mevcut 15m kolu (vsa/brooks/avwap/engulf) ile ay-korelasyonu =====
    try:
        existing = pickle.load(open(ROOT / "data" / "pool_19sym_20260610.pkl", "rb"))
        ex_sub = honest_pool([t for t in existing if to_utc(t["entry_ts"]) >= CLIP])
        cfg_fix = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, conf_min=0.25,
            fixed_notional_sizing=True, **RISK_KW,
        )
        ek, er = per_month_independent(ex_sub, cfg_fix)
        ex_monthly = dict(zip([f"{k[0]}-{k[1]:02d}" for k in ek], er))
        common = sorted(set(monthly_15m) & set(ex_monthly))
        if len(common) >= 6:
            import numpy as np
            a = np.array([monthly_15m[m] for m in common])
            b = np.array([ex_monthly[m] for m in common])
            corr = float(np.corrcoef(a, b)[0, 1])
            results["corr_vs_existing_15m"] = {
                "n_common_months": len(common), "monthly_corr": round(corr, 3),
                "existing_arm_monthly_mean": round(float(b.mean()), 3),
            }
            print("[corr] grimes 15m vs mevcut 15m kol: common=%d months  corr=%+.3f  (mevcut kol ay%%=%+.2f)"
                  % (len(common), corr, b.mean()), flush=True)
    except Exception as e:
        print("[corr] atlandı: %s" % e, flush=True)

    out = ROOT / "memory" / "researcher" / "backtest_results" / "2026-06-11-grimes-abc-two-leg-pullback.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_id": "HYP-2026-05-14-GRIMES-ABC-TWO-LEG",
        "methodology": "hardened_v14 first-pass: no pyramid, no reblend, +57bps honest, "
                       "widestop sl>=0.025 & conf>=0.25, fixed-notional per-month fresh-$10k",
        "risk_config": RISK_KW,
        "results": results,
    }, indent=2, default=str))
    print("[saved] %s" % out, flush=True)


if __name__ == "__main__":
    main()
