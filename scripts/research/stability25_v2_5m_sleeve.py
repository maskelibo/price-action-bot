"""İstikrarlı %25 — tur 2: ağırlık DD-incelt + 5m widestop ikinci kol.

Tur 1 bulgusu: concurrency artışı DD'yi patlatıyor (RED); strateji ağırlığı
mean'i +2.7pp artırıyor ama contDD -24.3 (limit -22 üstü).

Önceden deklare 4 varyant (train <=2024-11 seçer, OOS dokunulmaz):
  V1: wght(1.4/1.1/0.6/0.6) risk 0.58%        — DD'yi risk ile incelt
  V2: wght-mild(1.3/1.1/0.7/0.7) risk 0.62%   — DD'yi ağırlıkla incelt
  V3: flat 15m + 5m kolu (sl>=0.030, pyr'siz) — çeşitlendirme
  V4: wght 15m + 5m kolu                      — ikisi birden

5m kolu: sec53_5m_pool_v11_vm20.pkl (10 sym, ayni 4 strateji), sl_pct_min
0.030 (valide eşik), F2/F4 aynı, pyramid YOK (canlıda 5m pyramid yok),
57bps honest. Tek hesap: havuzlar birleşik replay (ortak mc16/ss4/breaker).

Kısıt: train contDD >= -22. İstikrar: mean/med/p10/worst/neg/exT5.
Reproduce: ./.venv/bin/python scripts/research/stability25_v2_5m_sleeve.py
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

from frontier_20pct_sweep import sl_pct_of, to_utc
from frontier_v2_pyr_expansion_regime import apply_filters, btc_daily_features
from price_action.backtest.lab import ProductionConfig, production_replay
import hardened_rebacktest_v14 as H
from stability25_sweep import per_month, stab, fmt

POOL15 = ROOT / "data" / "pool_19sym_20260610.pkl"
POOL5 = ROOT / "data" / "sec53_5m_pool_v11_vm20.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_v14_frontier.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_stability25_v2.json"
CLIP = datetime(2021, 5, 16, tzinfo=timezone.utc)
TRAIN_END = datetime(2024, 12, 1, tzinfo=timezone.utc)

W_FULL = {"vsa_climax_test": 1.4, "brooks_failed_breakout": 1.1,
          "anchored_vwap_reversal": 0.6, "engulfing_continuation": 0.6}
W_MILD = {"vsa_climax_test": 1.3, "brooks_failed_breakout": 1.1,
          "anchored_vwap_reversal": 0.7, "engulfing_continuation": 0.7}


def load_15m(weights=None):
    with POOL15.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP]
    H.PYR_TRIG = (1.2, 1.8)
    pool = H.build_pool_hardened(raw, H.HONEST_BPS)
    feats = btc_daily_features()
    sub, _ = apply_filters(pool, feats, use_f2=True, use_f4=True)
    if weights:
        for t in sub:
            t["risk_weight"] = weights.get(t["strategy"], 1.0)
    return sub


def load_5m():
    with POOL5.open("rb") as f:
        raw = pickle.load(f)
    raw = [t for t in raw if to_utc(t["entry_ts"]) >= CLIP]
    # 5m kolu: reblend yok, pyramid YOK, 57bps, sl>=0.030 (replay cfg'de degil
    # burada uygulanir cunku cfg.sl_pct_min 15m esigi 0.025 olarak kalacak)
    out = []
    for t in raw:
        slp = sl_pct_of(t)
        if slp < 0.030 or t["conf"] < 0.25:
            continue
        t2 = dict(t)
        extra_R = (H.HONEST_BPS / (slp * 10000.0)) if slp > 0 else 0.0
        t2["R"] = t["R"] - extra_R
        out.append(t2)
    feats = btc_daily_features()
    sub, _ = apply_filters(out, feats, use_f2=True, use_f4=True)
    return sub


def main():
    base = ProductionConfig.from_yaml(str(YAML))
    feats5 = load_5m()
    print("[5m kolu] sl>=0.030+conf+F2F4 sonrasi: %d trade" % len(feats5), flush=True)

    def mkcfg(risk):
        return base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.0,  # esikler havuz tarafinda uygulandi (15m 0.025 / 5m 0.030)
            conf_min=0.25, risk_pct=risk,
            daily_dd=0.04, weekly_dd=0.08,
            max_concurrent=16, max_same_side_concurrent=4,
        )

    def prep15(weights):
        sub = load_15m(weights)
        return [t for t in sub if sl_pct_of(t) >= 0.025]

    variants = [
        ("V1 wght r0.58", prep15(W_FULL), 0.0058),
        ("V2 wght-mild r0.62", prep15(W_MILD), 0.0062),
        ("V3 flat15+5m r0.62", sorted(prep15(None) + feats5, key=lambda x: to_utc(x["entry_ts"])), 0.0062),
        ("V4 wght15+5m r0.62", sorted(prep15(W_FULL) + feats5, key=lambda x: to_utc(x["entry_ts"])), 0.0062),
    ]
    results = {}
    print("\nTRAIN — kısıt contDD>=-22", flush=True)
    rows = []
    for label, sub, risk in variants:
        sub = sorted(sub, key=lambda x: to_utc(x["entry_ts"]))
        cfg = mkcfg(risk)
        sub_train = [t for t in sub if to_utc(t["entry_ts"]) < TRAIN_END]
        r = production_replay(sub_train, cfg)
        dd = r.max_drawdown * 100 if r else None
        cfg_pm = cfg.with_overrides(fixed_notional_sizing=True)
        _, rets = per_month(sub, cfg_pm, end_dt=TRAIN_END)
        s = stab(rets)
        if s is None:
            continue
        ok = dd is not None and dd >= -22.0
        print(fmt(label, s, dd) + ("  <= DD-OK" if ok else ""), flush=True)
        rows.append((label, sub, risk, s, dd, ok))
        results["train_" + label] = {**s, "cont_dd": dd}

    ok_rows = [x for x in rows if x[5]]
    pick = max(ok_rows or rows, key=lambda x: x[3]["mean"])
    label, sub, risk, _, _, _ = pick
    print("\nKAZANAN (train): %s — dokunulmamış OOS" % label, flush=True)
    cfg = mkcfg(risk)
    r_full = production_replay(sub, cfg)
    cfg_pm = cfg.with_overrides(fixed_notional_sizing=True)
    _, rets_full = per_month(sub, cfg_pm)
    _, rets_oos = per_month(sub, cfg_pm, start_dt=TRAIN_END)
    s_full, s_oos = stab(rets_full), stab(rets_oos)
    print(fmt("FULL " + label, s_full, r_full.max_drawdown * 100), flush=True)
    print(fmt("OOS  " + label, s_oos), flush=True)
    results["winner"] = {"label": label, "risk": risk, "full": s_full, "oos": s_oos,
                         "full_cont_dd": r_full.max_drawdown * 100}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), **results,
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
