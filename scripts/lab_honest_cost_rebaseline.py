"""Lab Scientist — HONEST cost re-baseline (Phoenix 15m C2+V5).

GOREV: Hard review T5 kanitladi ki hafizadaki +%1253/+%1935/+%2011 yillik
backtest sayilari IDEALIZE. Bu script GERCEK canli maliyetlerle re-baseline yapar.

POOL: data/sec53_15m_pool_v11.pkl — her trade'in R'si engine ciktisidir
  (5bps slippage + 0.075% taker fee TP partial'larinda zaten gomulu,
   close_pct 30/30/40 engine default).

GERCEK CANLI MALIYET (T5 + v204 config kaniti):
  - Komisyon: ~15 bps round-trip (taker — post_only_limit_enabled=false)
  - Slippage: 45.4 bps mean (v204 satir 234), pool icindeki 5bps'in uzeri = +40bps
  - Ek round-trip maliyet = 15 + 40 = +55 bps
  - extra_cost_R per trade = 0.0055 / sl_pct  (sl_pct = stop mesafesi)
  - close_pct canli: 25/25/50 (pool 30/30/40 ile uretildi)

SENARYO:
  (1) IDEALIZED — mevcut pool, fee=0, close 30/30/40 (referans, hafiza sayisi)
  (2) HONEST    — +55bps ek maliyet + close_pct 25/25/50 modellemesi

market.duckdb'ye DOKUNULMAZ — pool pkl yeterli.
Reproduce: python scripts/lab_honest_cost_rebaseline.py
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone
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

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"

# --- Maliyet parametreleri ---
EXTRA_BPS = 55.0          # round-trip ek maliyet (fee +15 + slippage +40)
SLIP_PYR = 0.06           # pyramid leg slippage erozyon katsayisi (lab.py parity)

# pyramid (C2+V5 final config)
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)

# multi-target TP seviyeleri (engine.py sat 416-421)
TP1_R = 1.0
TP2_R = 1.5
# close_pct: pool uretim (30/30/40) vs canli (25/25/50)
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    if ep > 0:
        return abs(t["initial_sl"] - ep) / ep
    return 0.04


def reblend_close_pct(t, new_close):
    """Pool R'si engine'in close 30/30/40 blendidir. 25/25/50'ye geciste R'yi
    yeniden hesapla.

    Engine math (engine.py 606-624): blended R = qty-weighted partial R toplami.
    - stage0 (peak_R < 1.0): TP1/TP2 hic fill olmaz -> tum pozisyon tek cikis
      R = R_exit. close_pct partition'i ETKILEMEZ (q1=q2=0 fark etmez ama
      tek-leg R close-invariant). reblend = no-op, EXACT.
    - stage1 (1.0 <= peak_R < 1.5): TP1 fill (q1@1.0R) + kalan tek cikista.
      R_pool = c1_old*1.0 + (1-c1_old)*R_rest   (R_rest = TP2-fill-olmayan kalan)
      => R_rest = (R_pool - c1_old*1.0) / (1-c1_old)
      R_new   = c1_new*1.0 + (1-c1_new)*R_rest
    - stage2 (peak_R >= 1.5): TP1@1.0R + TP2@1.5R + runner.
      R_pool = c1_old*1.0 + c2_old*1.5 + c_run_old*R_run
      => R_run = (R_pool - c1_old*1.0 - c2_old*1.5) / c_run_old
      R_new   = c1_new*1.0 + c2_new*1.5 + c_run_new*R_run
      FIZIKSEL TAVAN: R_run <= peak_R (runner MFE ustune cikamaz). Scenario B
      sprintinde kanitlandi: %17 trade'de peak_R = final_R (MFE underdetermined)
      -> R_run kapsiz patlar. cap uygula.

    NOT: TP1/TP2 fill fiyatlari slippage iceriyor; bu R_pool icinde zaten gomulu.
    Yeniden-blend ayni fill fiyatlarini farkli agirlikla toplar — slippage
    invariant. close_pct degisimi taze fee/slippage EKLEMEZ (ayni fill olaylari).
    """
    R = t["R"]
    pk = t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R  # stage0 — close-invariant, EXACT
    if pk < TP2_R:
        # stage1
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        R_new = c1n * TP1_R + (1.0 - c1n) * R_rest
        return R_new
    # stage2
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        # UNDERDETERMINED: pool peak_R = final_R (gercek MFE bilinmiyor, yalniz
        # >= pk). R_run turetilemiyor. Scenario B sprint ayni duvara carpti.
        # DURUST SECIM: olculemeyen trade'i pool R'sinde birak (close_pct etkisi
        # bu trade icin BILINMEZ). cap uygulamak worst-case artefakt uretir
        # (-65k R), no-cap fantasy (+35k R) — ikisi de yanlis. neutral = honest.
        return R
    R_new = c1n * TP1_R + c2n * TP2_R + crn * R_run
    return R_new


def build_pool(pool, mode):
    """mode:
      'idealized' — pool R'si oldugu gibi (fee=0, close 30/30/40), pyramid lab.py
                    IDEAL formulu (max(0,R-trig)), D BE-protect canli wiring var.
      'honest'    — close 25/25/50 reblend + +55bps ek maliyet, pyramid IDEAL.
                    (pyramid muhasebesi D-fix sonrasi IDEAL mesru — CEO 2026-05-20
                     §6: D commit 6d4d719 BE-protect canli wiring tamam.)
    """
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        if mode == "idealized":
            R = t["R"]
            extra_R = 0.0
        elif mode == "honest":
            R = reblend_close_pct(t, LIVE_CLOSE)
            extra_R = (EXTRA_BPS / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        else:
            raise ValueError(mode)
        # pyramid IDEAL (D BE-protect canli) — lab.py 691 semantigi
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                contrib = max(0.0, R - trig)
                radj += sz * contrib - SLIP_PYR * sz
                # leg basina ek round-trip maliyet (her leg ayri emir)
                if mode == "honest":
                    radj -= extra_R * sz
        # base trade'in kendi ek maliyeti
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
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
    mu = sum(rets) / n if n else 0
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
        "max_loss": min(rets) if rets else 0,
        "worst_month_dd": worst_dd, "rets": rets,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    from datetime import timedelta
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
    return {
        "windows": len(anns), "mean_annual": ma, "mean_dd": md,
        "r_adj": ma / abs(md) if md else 0,
        "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns),
    }


def pool_sumR(pool):
    return sum(t["R"] for t in pool)


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade  date %s -> %s" % (
        len(pool), pool[0]["entry_ts"], pool[-1]["entry_ts"]), flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    # pyramid OFF cfg — R zaten build_pool'da pyramid-adjusted; replay'de tekrar
    # uygulanmasin. fee_bps=0 — ek maliyet R icine gomuldu.
    cfg = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0,
    )

    # --- close_pct reblend diagnostik ---
    print("\n" + "=" * 78, flush=True)
    print("CLOSE_PCT REBLEND DIAGNOSTIK (30/30/40 -> 25/25/50)", flush=True)
    print("=" * 78, flush=True)
    s0 = [t for t in pool if t["peak_R"] < TP1_R]
    s1 = [t for t in pool if TP1_R <= t["peak_R"] < TP2_R]
    s2 = [t for t in pool if t["peak_R"] >= TP2_R]
    print("  stage0 (pk<1.0):    %6d  %5.1f%%  — close-invariant" % (
        len(s0), len(s0) / len(pool) * 100), flush=True)
    print("  stage1 (1.0-1.5):   %6d  %5.1f%%" % (
        len(s1), len(s1) / len(pool) * 100), flush=True)
    print("  stage2 (pk>=1.5):   %6d  %5.1f%%" % (
        len(s2), len(s2) / len(pool) * 100), flush=True)
    # reblend toplam etki
    d_s1 = sum(reblend_close_pct(t, LIVE_CLOSE) - t["R"] for t in s1)
    d_s2 = sum(reblend_close_pct(t, LIVE_CLOSE) - t["R"] for t in s2)
    print("  reblend dR toplam stage1: %+.1f R   stage2: %+.1f R   net: %+.1f R" % (
        d_s1, d_s2, d_s1 + d_s2), flush=True)
    und = sum(1 for t in s2
              if (t["R"] - POOL_CLOSE[0] * TP1_R - POOL_CLOSE[1] * TP2_R) / POOL_CLOSE[2] > t["peak_R"])
    print("  stage2 UNDERDETERMINED (R_run>peak, MFE bilinmiyor): %d  %5.1f%%" % (
        und, und / max(len(s2), 1) * 100), flush=True)
    print("  -> bu trade'lerde close_pct reblend OLCULEMEZ, pool R'sinde birakildi", flush=True)

    # --- senaryo kosulari ---
    results = {}
    wf_results = {}
    for label, mode in [("IDEALIZED", "idealized"), ("HONEST", "honest")]:
        p2 = build_pool(pool, mode)
        r = per_month(p2, cfg)
        wf = walk_forward(p2, cfg)
        r["sumR"] = pool_sumR(p2)
        results[label] = r
        wf_results[label] = wf

    print("\n" + "=" * 92, flush=True)
    print("RE-BASELINE — IDEALIZED vs HONEST  (Phoenix 15m C2+V5)", flush=True)
    print("=" * 92, flush=True)
    hdr = "%-14s%12s%10s%9s%8s%11s%9s%7s%12s" % (
        "senaryo", "yillik", "mean", "r-adj", "neg", "maxloss", "wmDD", "CV", "pool-sumR")
    print(hdr, flush=True)
    print("-" * 92, flush=True)
    for label in ("IDEALIZED", "HONEST"):
        r = results[label]
        print("%-14s%+11.1f%%%+9.2f%%%9.2f%5d/%d%+10.2f%%%+8.1f%%%6.0f%%%+12.0f" % (
            label, r["annual"], r["mean"], r["r_adj"], r["neg"], r["n"],
            r["max_loss"], r["worst_month_dd"], r["cv"], r["sumR"]), flush=True)

    ri, rh = results["IDEALIZED"], results["HONEST"]
    print("\n  --- SISME (IDEALIZED -> HONEST) ---", flush=True)
    print("  yillik ROI:   %+.1f%% -> %+.1f%%   = %+.1fpp sisme" % (
        ri["annual"], rh["annual"], ri["annual"] - rh["annual"]), flush=True)
    print("  mean ay:      %+.2f%% -> %+.2f%%   = %+.2fpp" % (
        ri["mean"], rh["mean"], ri["mean"] - rh["mean"]), flush=True)
    print("  r-adj:        %.2f -> %.2f   = %+.2f" % (
        ri["r_adj"], rh["r_adj"], ri["r_adj"] - rh["r_adj"]), flush=True)
    print("  negatif ay:   %d -> %d   = %+d ay (HONEST'te gizli kayip)" % (
        ri["neg"], rh["neg"], rh["neg"] - ri["neg"]), flush=True)
    print("  max ay kayip: %+.2f%% -> %+.2f%%   = %+.2fpp tail" % (
        ri["max_loss"], rh["max_loss"], rh["max_loss"] - ri["max_loss"]), flush=True)
    print("  pool-sumR:    %+.0f -> %+.0f   = %+.0f R (%.1f%% erozyon)" % (
        ri["sumR"], rh["sumR"], rh["sumR"] - ri["sumR"],
        (rh["sumR"] - ri["sumR"]) / abs(ri["sumR"]) * 100), flush=True)

    print("\n" + "=" * 78, flush=True)
    print("WALK-FORWARD (2y train / 90d OOS / 30d step) — OOS robustness", flush=True)
    print("=" * 78, flush=True)
    hdr = "%-14s%13s%11s%9s%8s%9s" % (
        "senaryo", "mean_ann", "mean_dd", "r-adj", "neg", "windows")
    print(hdr, flush=True)
    print("-" * 64, flush=True)
    for label in ("IDEALIZED", "HONEST"):
        wf = wf_results[label]
        if wf is None:
            print("%-14s  (no windows)" % label, flush=True)
            continue
        print("%-14s%+12.1f%%%+10.1f%%%9.2f%5d/%d%9d" % (
            label, wf["mean_annual"], wf["mean_dd"], wf["r_adj"],
            wf["neg"], wf["windows"], wf["windows"]), flush=True)

    # --- ara senaryolar (sismenin hangi bileseni ne kadar) ---
    print("\n" + "=" * 78, flush=True)
    print("SISME DEKOMPOZISYON — hangi maliyet bileseni ne kadar yiyor", flush=True)
    print("=" * 78, flush=True)
    # sadece close_pct reblend (maliyet yok)
    p_close = []
    for t in pool:
        t2 = dict(t)
        R = reblend_close_pct(t, LIVE_CLOSE)
        pk = t["peak_R"]
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
        t2["R"] = radj
        p_close.append(t2)
    r_close = per_month(p_close, cfg)
    # sadece +55bps maliyet (close 30/30/40 korunur)
    p_cost = []
    for t in pool:
        t2 = dict(t)
        R = t["R"]
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        extra_R = (EXTRA_BPS / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                radj += sz * max(0.0, R - trig) - SLIP_PYR * sz - extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        p_cost.append(t2)
    r_cost = per_month(p_cost, cfg)
    print("  %-40s yillik %+10.1f%%  neg %d  r-adj %.2f" % (
        "IDEALIZED (referans)", ri["annual"], ri["neg"], ri["r_adj"]), flush=True)
    print("  %-40s yillik %+10.1f%%  neg %d  r-adj %.2f" % (
        "+ close 25/25/50 reblend (maliyet yok)", r_close["annual"], r_close["neg"],
        r_close["r_adj"]), flush=True)
    print("  %-40s yillik %+10.1f%%  neg %d  r-adj %.2f" % (
        "+ 55bps maliyet (close 30/30/40)", r_cost["annual"], r_cost["neg"],
        r_cost["r_adj"]), flush=True)
    print("  %-40s yillik %+10.1f%%  neg %d  r-adj %.2f" % (
        "HONEST (her ikisi birlikte)", rh["annual"], rh["neg"], rh["r_adj"]), flush=True)
    print("\n  close_pct reblend tek-basina etki:  %+.1fpp yillik" % (
        r_close["annual"] - ri["annual"]), flush=True)
    print("  55bps maliyet tek-basina etki:      %+.1fpp yillik" % (
        r_cost["annual"] - ri["annual"]), flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
