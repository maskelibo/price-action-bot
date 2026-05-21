"""Lab Scientist — Scenario B EXACT analytic decomposition (engine-math-faithful).

CONTEXT: True engine re-run blocked — market.duckdb locked by LIVE daemon
(futures_daemon.py --timeframe 15m, PID 23944). Hard limit: production untouched.

EXACT DECOMPOSITION (engine.py sat 403-624 ile dogrulanmis):
  Baseline blended R:
    R_blended = (sum_partials (exit_p - entry)*q - fee) / initial_risk
  Partial set = {(TP1@1.0R, q1=0.30q), (TP2@1.5R, q2=0.30q), (runner, q_run=0.40q)}.
  Engine'de stage gecisleri close_pct'ten BAGIMSIZ — TP1/TP2 fiyat seviyesi
  asilinca stage artar (qty1/qty2 0 olsa bile). Yani:
    - runner leg'in trailing-SL/BE davranisi baseline ve B'de BIT-IDENTICAL.
    - B-mode (tp1=tp2=0) = "tum pozisyon runner" = baseline'in runner leg'i.

  R_runner cozumu (stage>=2, her iki TP fill):
    R_blended = 0.30*R_tp1 + 0.30*R_tp2 + 0.40*R_runner  (gross, fee ayri)
    => R_runner = (R_blended_gross - 0.30*R_tp1 - 0.30*R_tp2) / 0.40
  R_tp1 = +1.0R slip-adjusted, R_tp2 = +1.5R slip-adjusted (sabit fiyat fill).

  stage<1 (TP1'e hic ulasmadi): baseline pozisyonu zaten tek-parca SL/exit
    -> baseline R == B R EXACT.
  stage==1 (TP1 fill, TP2 yok): R_blended = 0.30*R_tp1 + 0.70*R_rest
    R_rest (TP2'siz qty2+runner birlikte) = B'nin tam pozisyonu.
    => R_B = (R_blended_gross - 0.30*R_tp1) / 0.70

PROBLEM: pool sadece final R + peak_R saklar, stage'i saklamaz.
  stage peak_R'den TUREVLENIR (engine: TP1 hit <=> hi/lo TP1 fiyatina degdi
  <=> MFE >= 1.0R <=> peak_R >= 1.0; TP2 <=> peak_R >= 1.5).
  Bu kesin: peak_R MFE'den hesaplanir, TP fill de MFE'nin esik gecmesi.

SLIPPAGE: engine TP fill fiyati = tp_price * (1 -/+ slip), slip=5bps.
  R_tp1_net_of_slip ~= 1.0 - 2*slip/sl_pct (entry+exit slip). Pool sl_pct'i var.
  Konservatif: slip dahil edilir (B lehine degil).

Bu CEO proxy DEGIL — engine close-aggregation matematiginin tersine cozumu.
Tek varsayim: stage <-> peak_R esik denkligi (engine kodu ile ispatli).
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from datetime import datetime, timezone, timedelta
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

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

# Engine pool-build params (sec31 _gather_peakR_single):
SLIP_BPS = 5.0
TAKER = 0.00075
TP1_R = 1.0
TP2_R = 1.5
TP1_CP = 0.30  # engine constructor default — sec53 pool
TP2_CP = 0.30
RUN_CP = 0.40


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def derive_B_R(t):
    """Baseline blended R -> B-mode R (tum pozisyon runner). Engine-math exact.

    stage <-> peak_R esik:
      peak_R < TP1_R          -> stage 0  -> R_B = R_blended (EXACT, hic harvest yok)
      TP1_R <= peak_R < TP2_R -> stage 1  -> R_B = (R_gross - TP1_CP*R_tp1) / (1-TP1_CP)
      peak_R >= TP2_R         -> stage 2  -> R_B = (R_gross - TP1_CP*R_tp1
                                                    - TP2_CP*R_tp2) / RUN_CP
    """
    R = float(t["R"])
    pk = float(t["peak_R"])
    entry = float(t["entry_price"])
    sl = float(t["initial_sl"])
    sl_pct = abs(entry - sl) / entry if entry > 0 else 0.04
    if sl_pct <= 0:
        return R, "degenerate"

    # TP fill fiyati slippage: long TP sell @ tp*(1-slip), short TP buy @ tp*(1+slip)
    # R_tp1 (slip+fee dahil, R-units): nominal 1.0R, slip entry+exit ~ slip uzakligi
    # engine: pnl_unit = (tp_price*(1-slip)) - entry  (long).
    # R-units'e cevir: bolu (initial_R_dist). initial_R_dist = sl_pct*entry.
    slip = SLIP_BPS / 10_000.0
    # TP1 net pnl_unit / initial_R_dist:
    #  long: (entry + 1.0*Rdist)*(1-slip) - entry = 1.0*Rdist - slip*(entry + Rdist)
    #  /Rdist = 1.0 - slip*(entry+Rdist)/Rdist = 1.0 - slip*(1/sl_pct + 1.0)
    # fee: (entry + tp)*taker per unit; /Rdist -> taker*(entry+tp)/Rdist
    Rdist_frac = sl_pct  # Rdist/entry
    tp1_gross_R = TP1_R - slip * (1.0 / sl_pct + TP1_R)
    tp2_gross_R = TP2_R - slip * (1.0 / sl_pct + TP2_R)
    # fee R-units per leg (entry+exit price ~ 2*entry +/- ; approx via taker)
    fee_R_tp1 = TAKER * (2.0 + TP1_R * sl_pct) / sl_pct
    fee_R_tp2 = TAKER * (2.0 + TP2_R * sl_pct) / sl_pct
    R_tp1 = tp1_gross_R - fee_R_tp1
    R_tp2 = tp2_gross_R - fee_R_tp2

    if pk < TP1_R - 1e-9:
        return R, "stage0"
    if pk < TP2_R - 1e-9:
        # stage 1: R = TP1_CP*R_tp1 + (1-TP1_CP)*R_B
        R_B = (R - TP1_CP * R_tp1) / (1.0 - TP1_CP)
        stg = "stage1"
    else:
        # stage 2
        R_B = (R - TP1_CP * R_tp1 - TP2_CP * R_tp2) / RUN_CP
        stg = "stage2"
    # PHYSICAL CEILING: runner cannot exit above MFE peak. peak_R = max(MFE, R).
    # Decomposition can over-amplify when blended R already near peak (pool stores
    # peak_R = max(MFE_peak, final_R); if final_R drove it, MFE underdetermined).
    # Cap B-R at peak_R — conservative (B lehine DEGIL, fantasy-R kesilir).
    if R_B > pk:
        R_B = pk
        stg = stg + "_capped"
    return R_B, stg


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
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
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "annual": annual,
        "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "ge20": sum(1 for x in rets if x >= 20),
        "max_loss": min(rets), "max_gain": max(rets), "worst_month_dd": worst_dd,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
    while cur + timedelta(days=train_days + oos_days) <= end:
        os_s = cur + timedelta(days=train_days)
        os_e = os_s + timedelta(days=oos_days)
        oos_tr = [t for t in pool if os_s <= to_utc(t["entry_ts"]) < os_e]
        if len(oos_tr) >= 10:
            r = production_replay(oos_tr, cfg)
            if r is not None:
                anns.append(r.annualized(oos_days / 365.0) * 100)
                dds.append(r.max_drawdown * 100)
        cur += timedelta(days=step_days)
    if not anns:
        return None
    ma = sum(anns) / len(anns)
    md = sum(dds) / len(dds)
    return {"windows": len(anns), "mean_annual": ma, "mean_dd": md,
            "r_adj": ma / abs(md) if md else 0,
            "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns)}


def R_use(t, cfg):
    R = float(t["R"])
    sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"] if t["entry_price"] > 0 else 0.04
    if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
        pk = float(t.get("peak_R", R))
        bonus = ero = 0.0
        for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
            if pk >= float(trig):
                bonus += float(sz) * max(0.0, R - float(trig))
                ero += 0.06 * float(sz)
        R = R + bonus - ero
    if cfg.fee_bps_per_trade != 0.0 and sl_pct > 0:
        base = cfg.fee_bps_per_trade / (sl_pct * 10_000.0)
        pyr = 0.0
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            pk2 = float(t.get("peak_R", t["R"]))
            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                if pk2 >= float(trig):
                    pyr += cfg.fee_bps_per_trade / (sl_pct * 10_000.0) * float(sz)
        R = R - base - pyr
    return R


def main():
    print("=" * 98, flush=True)
    print("SCENARIO B — EXACT ANALYTIC DECOMPOSITION (engine close-aggregation inverse)", flush=True)
    print("=" * 98, flush=True)
    with POOL.open("rb") as f:
        raw = pickle.load(f)
    pool = [t for t in raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"pool (sec53 v11, TOP-4 x 10 sym): {len(pool):,} trade", flush=True)

    # Build B pool
    pool_B = []
    cnt = {}
    dR_sum = 0.0
    for t in pool:
        R_B, stage = derive_B_R(t)
        cnt[stage] = cnt.get(stage, 0) + 1
        dR_sum += (R_B - float(t["R"]))
        t2 = dict(t)
        t2["R"] = R_B
        pool_B.append(t2)
    print(f"\n[STAGE BREAKDOWN] (peak_R esikten turetildi, B-R <= peak_R cap)", flush=True)
    n = len(pool)
    for k in sorted(cnt):
        print(f"  {k:<16} {cnt[k]:>8,} ({cnt[k]*100/n:.1f}%)", flush=True)
    n_capped = sum(v for k, v in cnt.items() if "capped" in k)
    print(f"  capped toplam: {n_capped:,} ({n_capped*100/n:.2f}%) — decomp fantasy-R kesildi", flush=True)
    print(f"  stage0 -> B R == baseline R (EXACT, harvest yok)", flush=True)
    print(f"  stage1/2 -> B R = runner-leg inverse (engine-math exact)", flush=True)
    print(f"  sum(R_B - R_baseline) = {dR_sum:+.1f} (pool ham R uplift)", flush=True)

    # Sanity: B-R vs baseline-R distribution
    Rb = [float(t["R"]) for t in pool]
    RB = [float(t["R"]) for t in pool_B]
    print(f"\n[RAW R] baseline meanR={sum(Rb)/n:+.4f} sumR={sum(Rb):+.0f}", flush=True)
    print(f"[RAW R] B        meanR={sum(RB)/n:+.4f} sumR={sum(RB):+.0f}", flush=True)
    # winners only — B should lift winners, losers ~unchanged
    win_b = [r for r in Rb if r > 0]
    win_B = [r for r in RB if r > 0]
    print(f"[RAW R winners] baseline mean={sum(win_b)/len(win_b):+.3f} (n={len(win_b):,})", flush=True)
    print(f"[RAW R winners] B        mean={sum(win_B)/len(win_B):+.3f} (n={len(win_B):,})", flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    print(f"\n[cfg] pyramid={base.pyramid_enabled} trig={base.pyramid_triggers} "
          f"sizes={base.pyramid_sizes} conf_min={base.conf_min} risk={base.risk_pct}", flush=True)

    for fee in (0.0, 8.0):
        print(f"\n{'='*98}", flush=True)
        print(f"FEE = {fee:+.0f} bps", flush=True)
        print(f"{'='*98}", flush=True)
        cfg = base.with_overrides(fee_bps_per_trade=fee)
        cfg_off = base.with_overrides(fee_bps_per_trade=fee, pyramid_enabled=False,
                                      pyramid_triggers=(), pyramid_sizes=())

        # Pool-R
        print(f"\n--- POOL-R SEVIYE (compound-bagimsiz) ---", flush=True)
        rows = [
            ("F  pyr OFF (base-pool)", pool, cfg_off),
            ("CURRENT pyr ON (base-pool)", pool, cfg),
            ("B  pyr ON (B-pool decomp)", pool_B, cfg),
        ]
        print(f"{'model':<32}{'useSumR':>12}{'useMeanR':>11}{'useWR':>9}", flush=True)
        print("-" * 70, flush=True)
        srt = {}
        for name, pl, cf in rows:
            rs = [R_use(t, cf) for t in pl]
            sm = sum(rs)
            srt[name] = sm
            print(f"{name:<32}{sm:>+12.0f}{sm/len(rs):>+11.4f}"
                  f"{sum(1 for r in rs if r>0)*100/len(rs):>8.1f}%", flush=True)
        cur_sr = srt["CURRENT pyr ON (base-pool)"]
        b_sr = srt["B  pyr ON (B-pool decomp)"]
        f_sr = srt["F  pyr OFF (base-pool)"]
        print(f"\n  B vs CURRENT pool-R uplift: {(b_sr/cur_sr-1)*100:+.1f}%", flush=True)
        print(f"  CURRENT vs F pool-R uplift: {(cur_sr/f_sr-1)*100:+.1f}%", flush=True)
        print(f"  B vs F pool-R uplift:       {(b_sr/f_sr-1)*100:+.1f}%", flush=True)

        # Per-month
        print(f"\n--- PER-MONTH (61 ay) ---", flush=True)
        print(f"{'senaryo':<30}{'annual':>11}{'mean':>9}{'r-adj':>8}{'neg':>6}"
              f"{'ge20':>6}{'maxloss':>10}{'wmDD':>9}{'CV':>7}", flush=True)
        print("-" * 96, flush=True)
        pm = {}
        for name, pl, cf in rows:
            r = per_month(pl, cf)
            pm[name] = r
            if r is None:
                print(f"{name:<30}  (no data)", flush=True)
                continue
            print(f"{name:<30}{r['annual']:>+10.1f}%{r['mean']:>+8.2f}%{r['r_adj']:>8.2f}"
                  f"{r['neg']:>6d}{r['ge20']:>6d}{r['max_loss']:>+9.2f}%"
                  f"{r['worst_month_dd']:>+8.1f}%{r['cv']:>6.0f}%", flush=True)

        # Walk-forward
        print(f"\n--- WALK-FORWARD (2y/90d/30d) ---", flush=True)
        print(f"{'senaryo':<30}{'mean_ann':>11}{'mean_dd':>10}{'r-adj':>8}{'neg':>6}{'wins':>7}", flush=True)
        print("-" * 96, flush=True)
        for name, pl, cf in rows:
            r = walk_forward(pl, cf)
            if r is None:
                print(f"{name:<30}  (no windows)", flush=True)
                continue
            print(f"{name:<30}{r['mean_annual']:>+10.1f}%{r['mean_dd']:>+9.1f}%"
                  f"{r['r_adj']:>8.2f}{r['neg']:>6d}{r['windows']:>7d}", flush=True)

        cur = pm.get("CURRENT pyr ON (base-pool)")
        b = pm.get("B  pyr ON (B-pool decomp)")
        if cur and b:
            print(f"\n--- DELTA B vs CURRENT ---", flush=True)
            print(f"  annual {b['annual']-cur['annual']:+.1f}pp  "
                  f"r-adj {b['r_adj']-cur['r_adj']:+.2f}  neg {b['neg']-cur['neg']:+d}  "
                  f"maxloss {b['max_loss']-cur['max_loss']:+.2f}pp  "
                  f"CV {b['cv']-cur['cv']:+.0f}pp  ge20 {b['ge20']-cur['ge20']:+d}", flush=True)


if __name__ == "__main__":
    main()
