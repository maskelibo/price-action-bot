"""SEC32 — Pyramid fix etkisini doğrula.

Aynı pool + aynı YAML + aynı cooldown, sadece pyramid_triggers ON vs OFF.
Hipotez: SEC49 raporu (mean +%17.33, 20 zero) pyramid BROKEN konfigürasyonu;
        sec_s5 retest (mean +%28.91, 2 zero) pyramid FIX sonrası.
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

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
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10: continue
        r = production_replay(m_tr, cfg)
        if r is None: continue
        rets.append(r.total_return * 100)

    n = len(rets)
    mu = sum(rets)/n
    std = (sum((x-mu)**2 for x in rets) / (n-1))**0.5 if n > 1 else 0
    cv = std/abs(mu)*100 if mu != 0 else 1e9
    return {
        "n": n,
        "mean_pct": mu, "cv_pct": cv,
        "pos": sum(1 for x in rets if x > 0),
        "neg": sum(1 for x in rets if x < 0),
        "zero": sum(1 for x in rets if x == 0),
        "ge20": sum(1 for x in rets if x >= 20),
    }


def main():
    print(f"[load] {POOL_R4.name}", flush=True)
    with POOL_R4.open("rb") as f:
        r4 = pickle.load(f)
    pool = [t for t in r4 if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  TOP-4 pool: {len(pool):,}", flush=True)

    base_cfg = ProductionConfig.from_yaml(str(YAML_R3)).with_overrides(
        max_concurrent=20, same_symbol_side_cooldown_days=0.0
    )
    print(f"\n[base cfg]", flush=True)
    print(f"  pyramid_enabled = {base_cfg.pyramid_enabled}", flush=True)
    print(f"  pyramid_triggers = {base_cfg.pyramid_triggers}", flush=True)
    print(f"  pyramid_sizes = {base_cfg.pyramid_sizes}", flush=True)
    print(f"  cooldown = {base_cfg.same_symbol_side_cooldown_days}d", flush=True)

    print(f"\n=== TEST: pyramid ON (current YAML) vs OFF (broken) ===", flush=True)
    print(f"{'scenario':<30}{'n':<5}{'mean':<10}{'cv':<8}{'pos':<5}{'neg':<5}{'zero':<6}{'ge20':<6}", flush=True)
    print("-" * 80, flush=True)

    # Run 1: current YAML (pyramid ON)
    cfg_on = base_cfg
    r_on = per_month_sec49(pool, cfg_on)
    print(f"{'pyramid ON (current YAML)':<30}{r_on['n']:<5}{r_on['mean_pct']:>+7.2f}% {r_on['cv_pct']:>6.0f}% {r_on['pos']:<5}{r_on['neg']:<5}{r_on['zero']:<6}{r_on['ge20']:<6}", flush=True)

    # Run 2: pyramid OFF (broken — empty triggers/sizes)
    cfg_off = base_cfg.with_overrides(pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=())
    r_off = per_month_sec49(pool, cfg_off)
    print(f"{'pyramid OFF (broken sim)':<30}{r_off['n']:<5}{r_off['mean_pct']:>+7.2f}% {r_off['cv_pct']:>6.0f}% {r_off['pos']:<5}{r_off['neg']:<5}{r_off['zero']:<6}{r_off['ge20']:<6}", flush=True)

    print(f"\n=== DELTA (ON - OFF) ===", flush=True)
    print(f"  mean:  {r_on['mean_pct']-r_off['mean_pct']:+.2f}pp", flush=True)
    print(f"  CV:    {r_on['cv_pct']-r_off['cv_pct']:+.0f}pp", flush=True)
    print(f"  pos:   {r_on['pos']-r_off['pos']:+d}", flush=True)
    print(f"  neg:   {r_on['neg']-r_off['neg']:+d}", flush=True)
    print(f"  zero:  {r_on['zero']-r_off['zero']:+d}", flush=True)
    print(f"  ge20:  {r_on['ge20']-r_off['ge20']:+d}", flush=True)

    print(f"\n=== SEC49 RESUME ref: mean +%17.33, CV %223, zero 20, neg 9, pos 32, ge20 15 ===", flush=True)
    print(f"=== sec_s5 retest:    mean +%28.91, CV %144, zero  2, neg 7, pos 52, ge20 26 ===", flush=True)


if __name__ == "__main__":
    main()
