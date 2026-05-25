"""SEC32 reconciliation — sec_s5 vs sec49 per_month metodu farkı.

Aynı pool + aynı cfg ile her iki per_month versiyonunu çalıştır,
sayıların kaynak farkını ortaya çıkar.

Hipotez: Sapma cooldown değil, "zero_months" tanımı + replay 0.0 davranışı.
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean as stat_mean, stdev

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay

POOL_R4 = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def per_month_sec49(pool, cfg):
    """sec49 / sec46 paterni: n<10 ay DROP, replay 0.0 ay sıfır sayılır."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12: me = datetime(cy+1, 1, 1, tzinfo=timezone.utc)
        else: me = datetime(cy, cm+1, 1, tzinfo=timezone.utc)
        if ms > end: break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12: cm = 1; cy += 1

    rets = []
    n_skipped = 0
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            n_skipped += 1
            continue
        r = production_replay(m_tr, cfg)
        if r is None: continue
        rets.append(r.total_return * 100)

    n = len(rets)
    mu = sum(rets)/n if n else 0
    std = (sum((x-mu)**2 for x in rets) / (n-1))**0.5 if n > 1 else 0
    cv = std/abs(mu)*100 if mu != 0 else 1e9
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge20 = sum(1 for x in rets if x >= 20)
    return {
        "method": "sec49",
        "n_months_total": len(months),
        "n_skipped": n_skipped,
        "n_in_rets": n,
        "mean_pct": mu, "cv_pct": cv,
        "zero": zero, "neg": neg, "pos": pos, "ge20": ge20,
    }


def per_month_sec_s5(pool, cfg):
    """sec_s5 paterni: n<10 ay 0.0 EKLENİR, zero_months YALNIZCA n<1 sayar."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12: me = datetime(cy+1, 1, 1, tzinfo=timezone.utc)
        else: me = datetime(cy, cm+1, 1, tzinfo=timezone.utc)
        if ms > end: break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12: cm = 1; cy += 1

    rets = []
    zero_months = 0   # SADECE n<1 sayar
    n_treated_zero_low = 0  # n<10 → 0.0 listede ama "zero" sayılmaz
    n_replay_zero = 0  # replay total_return=0.0 olan ay (mekanizmik 0)
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 1:
            zero_months += 1
            rets.append(0.0)
            continue
        if len(m_tr) < 10:
            n_treated_zero_low += 1
            rets.append(0.0)
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            rets.append(0.0); continue
        ret = r.total_return * 100
        rets.append(ret)
        if ret == 0.0:
            n_replay_zero += 1

    n = len(rets)
    mu = sum(rets)/n
    std = (sum((x-mu)**2 for x in rets) / (n-1))**0.5 if n > 1 else 0
    cv = std/abs(mu)*100 if mu != 0 else 1e9
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    ge20 = sum(1 for x in rets if x >= 20)
    return {
        "method": "sec_s5",
        "n_months_total": len(months),
        "n_in_rets": n,
        "n_treated_zero_low": n_treated_zero_low,
        "n_replay_zero": n_replay_zero,
        "mean_pct": mu, "cv_pct": cv,
        "zero_months": zero_months,
        "neg": neg, "pos": pos, "ge20": ge20,
    }


def main():
    print(f"[load] {POOL_R4.name}", flush=True)
    with POOL_R4.open("rb") as f:
        r4 = pickle.load(f)
    pool = [t for t in r4 if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  TOP-4 pool: {len(pool):,}", flush=True)

    base_cfg = ProductionConfig.from_yaml(str(YAML_R3)).with_overrides(max_concurrent=20)

    print(f"\n=== TEST MATRIX: 2 cooldown × 2 per_month metod ===", flush=True)
    print(f"{'cd':<8}{'method':<10}{'n_rets':<8}{'mean':<10}{'cv':<8}{'pos':<6}{'neg':<6}{'zero':<6}{'ge20':<6}{'extras'}", flush=True)
    print("-" * 100, flush=True)

    for cd in [0.010, 0.0]:
        cfg = base_cfg.with_overrides(same_symbol_side_cooldown_days=cd)
        r49 = per_month_sec49(pool, cfg)
        rs5 = per_month_sec_s5(pool, cfg)
        print(f"{cd:<8.3f}{'sec49':<10}{r49['n_in_rets']:<8d}{r49['mean_pct']:>+7.2f}% {r49['cv_pct']:>6.0f}% {r49['pos']:<6d}{r49['neg']:<6d}{r49['zero']:<6d}{r49['ge20']:<6d} skipped<10={r49['n_skipped']}", flush=True)
        print(f"{cd:<8.3f}{'sec_s5':<10}{rs5['n_in_rets']:<8d}{rs5['mean_pct']:>+7.2f}% {rs5['cv_pct']:>6.0f}% {rs5['pos']:<6d}{rs5['neg']:<6d}{rs5['zero_months']:<6d}{rs5['ge20']:<6d} low10={rs5['n_treated_zero_low']} replay0={rs5['n_replay_zero']}", flush=True)

    print(f"\nDONE", flush=True)


if __name__ == "__main__":
    main()
