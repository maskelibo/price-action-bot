"""İstikrarlı %25/ay hedefi — concurrency + strateji-ağırlık sweep'i.

Hedef (Principal): aylık ortalama ~%25, İSTİKRARLI (tek-ay patlaması yasak).
İstikrar tanımı (önceden deklare): mean>=25, median>=20, p10>=+5, worst>=-5,
neg<=3, ex-top5% mean>=22 — ay-bağımsız taze-$10k ölçümünde.

Kaldıraçlar (train-seçim <=2024-11, OOS dokunulmaz):
  A. max_concurrent 16 -> 24 / 32  (uygun trade'lerin ~%93'ü tavandan işlenmiyor)
  B. max_same_side  4 -> 6 / 8     (yön-konsantrasyon limiti; G16 riskine dikkat)
  C. Strateji risk ağırlığı (ölçümden, fit DEĞİL): vsa 1.4 / brooks 1.1 /
     avwap 0.6 / engulf 0.6 — per-trade risk_weight (lab.py:1013 mevcut hook).
     Tek set; grid taraması YOK (multiple-testing disiplini).

Kısıt (train, continuous compounding eğri): DD >= -22; sonra mean maksimize,
istikrar metrikleriyle birlikte raporla. Finalistlere per-month + OOS.

Reproduce: ./.venv/bin/python scripts/research/stability25_sweep.py
"""
from __future__ import annotations
import json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
import statistics as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))
logging.getLogger("price_action").setLevel(logging.ERROR)

from frontier_20pct_sweep import to_utc
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig, production_replay
import hardened_rebacktest_v14 as H

POOL19 = ROOT / "data" / "pool_19sym_20260610.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_v14_frontier.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_stability25_sweep.json"
CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
TRAIN_END = datetime(2024, 12, 1, tzinfo=timezone.utc)
INITIAL = 10_000.0

STRAT_W = {"vsa_climax_test": 1.4, "brooks_failed_breakout": 1.1,
           "anchored_vwap_reversal": 0.6, "engulfing_continuation": 0.6}


def load_sub(weighted: bool):
    with POOL19.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP]
    H.PYR_TRIG = (1.2, 1.8)
    pool = H.build_pool_hardened(raw, H.HONEST_BPS)
    feats = btc_daily_features()
    sub, _ = apply_filters(pool, feats, use_f2=True, use_f4=True)
    if weighted:
        for t in sub:
            t["risk_weight"] = STRAT_W.get(t["strategy"], 1.0)
    return sorted(sub, key=lambda x: to_utc(x["entry_ts"]))


def per_month(sub, cfg, start_dt=None, end_dt=None):
    s = [t for t in sub
         if (start_dt is None or to_utc(t["entry_ts"]) >= start_dt)
         and (end_dt is None or to_utc(t["entry_ts"]) < end_dt)]
    if not s:
        return [], []
    start, end = to_utc(s[0]["entry_ts"]), to_utc(s[-1]["entry_ts"])
    cy, cm = start.year, start.month
    keys, rets = [], []
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        m_tr = [t for t in s if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) >= 10:
            r = production_replay(m_tr, cfg)
            if r is not None:
                keys.append((cy, cm))
                rets.append((r.final_equity - INITIAL) / INITIAL * 100)
        cm = (cm % 12) + 1
        if cm == 1:
            cy += 1
    return keys, rets


def stab(v):
    n = len(v)
    if n < 6:
        return None
    srt = sorted(v)
    ex5 = sorted(v, reverse=True)[max(1, round(n * 0.05)):]
    return {
        "n": n, "mean": sum(v) / n, "median": st.median(v),
        "std": st.stdev(v), "p10": srt[n // 10], "worst": srt[0],
        "neg": sum(1 for x in v if x < 0),
        "ex_top5": sum(ex5) / len(ex5),
    }


def fmt(label, s, dd=None):
    ddtxt = ("  contDD=%+.1f" % dd) if dd is not None else ""
    return ("  %-36s mean=%+6.2f med=%+6.2f p10=%+5.2f worst=%+6.2f "
            "neg=%d/%d exT5=%+6.2f%s") % (
        label, s["mean"], s["median"], s["p10"], s["worst"],
        s["neg"], s["n"], s["ex_top5"], ddtxt)


def main():
    base = ProductionConfig.from_yaml(str(YAML))
    results = {}

    variants = [
        ("flat  mc16 ss4", False, 16, 4),
        ("flat  mc24 ss6", False, 24, 6),
        ("flat  mc32 ss8", False, 32, 8),
        ("wght  mc16 ss4", True, 16, 4),
        ("wght  mc24 ss6", True, 24, 6),
        ("wght  mc32 ss8", True, 32, 8),
    ]
    print("TRAIN (2021-05..2024-11) — kısıt contDD>=-22, hedef stabil mean", flush=True)
    train_rows = []
    for label, weighted, mc, ss in variants:
        sub = load_sub(weighted)
        cfg = base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, conf_min=0.25,
            risk_pct=0.0062, daily_dd=0.04, weekly_dd=0.08,
            max_concurrent=mc, max_same_side_concurrent=ss,
        )
        # continuous DD (compounding, deploy gerçeği) — train penceresi
        sub_train = [t for t in sub if to_utc(t["entry_ts"]) < TRAIN_END]
        r = production_replay(sub_train, cfg)
        dd = r.max_drawdown * 100 if r else None
        # per-month istikrar — train penceresi
        cfg_pm = cfg.with_overrides(fixed_notional_sizing=True)
        _, rets = per_month(sub, cfg_pm, end_dt=TRAIN_END)
        s = stab(rets)
        if s is None:
            continue
        ok = dd is not None and dd >= -22.0
        print(fmt(label, s, dd) + ("  <= DD-OK" if ok else ""), flush=True)
        train_rows.append((label, weighted, mc, ss, s, dd, ok))
        results["train_" + label] = {**s, "cont_dd": dd}

    # Kazanan: DD-OK içinde en yüksek TRAIN mean (istikrar metrikleriyle birlikte)
    ok_rows = [x for x in train_rows if x[6]]
    pick = max(ok_rows or train_rows, key=lambda x: x[4]["mean"])
    label, weighted, mc, ss, _, _, _ = pick
    print("\nKAZANAN (train): %s — dokunulmamış OOS değerlendiriliyor" % label, flush=True)
    sub = load_sub(weighted)
    cfg = base.with_overrides(
        fee_bps_per_trade=0.0, pyramid_enabled=False,
        pyramid_triggers=(), pyramid_sizes=(),
        sl_pct_min=0.025, conf_min=0.25,
        risk_pct=0.0062, daily_dd=0.04, weekly_dd=0.08,
        max_concurrent=mc, max_same_side_concurrent=ss,
    )
    r_full = production_replay(sub, cfg)
    cfg_pm = cfg.with_overrides(fixed_notional_sizing=True)
    _, rets_full = per_month(sub, cfg_pm)
    _, rets_oos = per_month(sub, cfg_pm, start_dt=TRAIN_END)
    s_full, s_oos = stab(rets_full), stab(rets_oos)
    print(fmt("FULL " + label, s_full, r_full.max_drawdown * 100), flush=True)
    print(fmt("OOS  " + label, s_oos), flush=True)
    results["winner"] = {"label": label, "weighted": weighted, "mc": mc, "ss": ss,
                         "full": s_full, "oos": s_oos,
                         "full_cont_dd": r_full.max_drawdown * 100}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strat_weights": STRAT_W, **results,
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
