"""Frontier v2 — pyramid + sembol genişleme + rejim filtreleri.

v1 bulgusu (2026-06-10_frontier_20pct_sweep.json): risk büyütme işe yaramıyor
(DD patlıyor, breaker'lar kârı kesiyor). DD<=20 kısıtında tavan pyr=0 +7.1/ay,
pyr=1 +15.9/ay. %20'ye yapısal kaldıraçlarla gidilecek:

  P0: vsa2_top4 (10 sym) pyr=1                 — v1 en iyisi, referans
  P1: top4 non-VSA + _vsa_pool_15sym_fresh VSA — VSA 10->15 sembol genişleme

Rejim filtreleri (YAML regime_filter_per_strategy F1/F2/F4; replay'de hiç
uygulanmıyordu — burada pool-trade drop olarak, t-1 BTC 1d feature ile causal):
  F1: anchored_vwap_reversal BOTH drop — atr_pct_30d<3 & |ret30|<3 (range)
  F2: brooks_failed_breakout SHORT drop — above_ema200 & ret30>+5% (strong bull)
  F4: engulfing_continuation BOTH drop — realvol7d_ann>100% (extreme vol)
  (F3 atlandı: F&G tarihsel verisi yok)

Aşama A: risk 0.5% dd-champ sabit, pool x filtre matrisi -> kazanan kombo.
Aşama B: kazanan kombo, risk x dd grid -> DD<=20'de ay% maksimize.

Reproduce: ./.venv/bin/python scripts/research/frontier_v2_pyr_expansion_regime.py
"""
from __future__ import annotations
import io, json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

# stdout wrap YOK — import edilen frontier_20pct_sweep zaten sarıyor;
# çift sarma eski wrapper'ı GC'de kapatıp "I/O on closed file" veriyor.
os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import duckdb
import pandas as pd

from frontier_20pct_sweep import (  # v1 metodolojisi birebir
    HONEST_BPS, build_pool, fmt, replay_full, sl_pct_of, to_utc,
)
from price_action.backtest.lab import ProductionConfig

POOL_TOP4 = ROOT / "data" / "sec53_15m_pool_v11_vsa2_top4.pkl"
POOL_VSA15 = ROOT / "data" / "_vsa_pool_15sym_fresh.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
OUT = ROOT / "reports" / "research" / "2026-06-10_frontier_v2.json"


def btc_daily_features():
    """BTC 1d -> t-1 shift'li causal feature frame (date -> row)."""
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, high, low, close FROM ohlcv "
        "WHERE venue='binance' AND symbol='BTC/USDT' AND timeframe='1d' ORDER BY ts"
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    c = df["close"]
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift(1)).abs(),
        (df["low"] - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    feat = pd.DataFrame(index=df.index)
    feat["atr_pct_30d"] = (tr.rolling(30).mean() / c) * 100
    feat["return_30d"] = (c / c.shift(30) - 1.0) * 100
    feat["above_ema200"] = c > c.ewm(span=200, adjust=False).mean()
    feat["realvol7d_ann"] = c.pct_change().rolling(7).std() * (365 ** 0.5) * 100
    feat = feat.shift(1)  # t-1: sinyal günü t, feature t-1 kapanışından (causal)
    feat["date"] = feat.index.date
    return {row.date: row for row in feat.itertuples()}


def apply_filters(pool, feats, use_f1=False, use_f2=False, use_f4=False):
    out = []
    dropped = {"F1": 0, "F2": 0, "F4": 0}
    for t in pool:
        d = to_utc(t["entry_ts"]).date()
        f = feats.get(d)
        if f is not None and not pd.isna(f.atr_pct_30d):
            strat = t["strategy"]
            side = str(t["side"]).lower()
            if (use_f1 and strat == "anchored_vwap_reversal"
                    and f.atr_pct_30d < 3.0 and abs(f.return_30d) < 3.0):
                dropped["F1"] += 1
                continue
            if (use_f2 and strat == "brooks_failed_breakout" and side == "short"
                    and f.above_ema200 and f.return_30d > 5.0):
                dropped["F2"] += 1
                continue
            if (use_f4 and strat == "engulfing_continuation"
                    and f.realvol7d_ann > 100.0):
                dropped["F4"] += 1
                continue
        out.append(t)
    return out, dropped


def main():
    print("[load] havuzlar + BTC feature'lar", flush=True)
    with POOL_TOP4.open("rb") as f:
        top4 = pickle.load(f)
    with POOL_VSA15.open("rb") as f:
        vsa15 = pickle.load(f)
    feats = btc_daily_features()

    non_vsa = [t for t in top4 if t["strategy"] != "vsa_climax_test"]
    p0_raw = top4
    p1_raw = non_vsa + list(vsa15)
    print("  P0 (top4 10sym): %d  |  P1 (top4nonVSA+VSA15sym): %d" % (
        len(p0_raw), len(p1_raw)), flush=True)

    pools = {
        "P0": build_pool(p0_raw, HONEST_BPS, pyramid=True),
        "P1": build_pool(p1_raw, HONEST_BPS, pyramid=True),
    }
    base = ProductionConfig.from_yaml(str(YAML))

    def mkcfg(risk, daily, weekly):
        return base.with_overrides(
            fee_bps_per_trade=0.0, pyramid_enabled=False,
            pyramid_triggers=(), pyramid_sizes=(),
            sl_pct_min=0.025, risk_pct=risk,
            daily_dd=daily, weekly_dd=weekly,
        )

    # ===== ASAMA A: pool x filtre matrisi (risk 0.5%, dd-champ) =====
    print("\nASAMA A — POOL x FILTRE (risk 0.5%%, d02/w05, sl>=0.025, pyr-pool)", flush=True)
    filter_sets = [
        ("nofilt", {}),
        ("F2", dict(use_f2=True)),
        ("F2+F4", dict(use_f2=True, use_f4=True)),
        ("F1+F2+F4", dict(use_f1=True, use_f2=True, use_f4=True)),
    ]
    cfg_a = mkcfg(0.005, 0.02, 0.05)
    stage_a = []
    for pname, pool in pools.items():
        for flabel, fkw in filter_sets:
            sub, dropped = apply_filters(pool, feats, **fkw)
            res = replay_full(sub, cfg_a)
            label = "%s %s" % (pname, flabel)
            drops = " drop:" + ",".join("%s=%d" % kv for kv in dropped.items() if kv[1])
            print(fmt(label, res) + (drops if any(dropped.values()) else ""), flush=True)
            if res:
                stage_a.append((label, pname, fkw, res))

    # Kazanan: DD>=-20 icinde en yuksek ay%; yoksa en yuksek ay%/|DD| orani
    ok = [x for x in stage_a if x[3]["dd"] >= -20.0]
    pickfrom = ok if ok else stage_a
    pickfrom.sort(key=lambda x: x[3]["monthly_mean"], reverse=True)
    win_label, win_pool, win_fkw, win_res = pickfrom[0]
    print("\n  KAZANAN: %s (ay%%=%+.2f DD=%+.1f)" % (
        win_label, win_res["monthly_mean"], win_res["dd"]), flush=True)

    # ===== ASAMA B: kazanan kombo risk x dd grid =====
    print("\nASAMA B — KAZANAN KOMBO RISK x DD GRID", flush=True)
    sub, _ = apply_filters(pools[win_pool], feats, **win_fkw)
    rows = []
    for risk in (0.004, 0.005, 0.006, 0.007, 0.008):
        for dlabel, daily, weekly in (("d02/w05", 0.02, 0.05), ("d03/w06", 0.03, 0.06)):
            res = replay_full(sub, mkcfg(risk, daily, weekly))
            if res is None:
                continue
            label = "%s r%.1f%% %s" % (win_label, risk * 100, dlabel)
            rows.append((label, res))
    rows.sort(key=lambda x: x[1]["monthly_mean"], reverse=True)
    for label, res in rows:
        okf = "  <= DD-OK" if res["dd"] >= -20.0 else ""
        hit = " ***20%HEDEF***" if (res["dd"] >= -20.0 and res["monthly_mean"] >= 20.0) else ""
        print(fmt(label, res) + okf + hit, flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage_a": [{"label": l, **{k: v for k, v in r.items() if k != "rets"}}
                    for l, _, _, r in stage_a],
        "stage_b": [{"label": l, **{k: v for k, v in r.items() if k != "rets"}}
                    for l, r in rows],
    }, indent=2, default=str))
    print("\n[saved] %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
