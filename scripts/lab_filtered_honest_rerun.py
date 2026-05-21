"""Lab Scientist — FILTERED HONEST re-run (Phoenix 15m C2+V5).

GOREV (C): Honest re-baseline (pool-R -31.775 R) F1-F4 regime filter +
correlation gate UYGULANMADAN olculmustu. Bu script o iki filtreyi ekler ve
15m phoenix C2+V5'in 3 noktada karsilastirmasini yapar:

  (1) IDEALIZED        — fee=0, close 30/30/40, no filter (hafiza referansi)
  (2) HONEST no-filter — +55bps maliyet + close 25/25/50, no filter (re-baseline)
  (3) HONEST + FILTRELER — (2) uzerine F1-F4 regime filter + correlation gate

YONTEM: pool R-bazli honest replay (lab_honest_cost_rebaseline.py ile birebir
maliyet semantigi) + sec54_6d_regime_filter_replay.py F1-F4 filter mantigi +
correlation gate modeli (asagida belgelendi).

market.duckdb'ye DOKUNULMAZ — pool pkl R-bazli replay. lab.py + production YAML
DOKUNULMAZ. Daemon YENIDEN BASLATILMAZ.

Reproduce: python scripts/lab_filtered_honest_rerun.py
"""
from __future__ import annotations
import hashlib
import io
import math
import os
import pickle
import sys
from datetime import datetime, timedelta, timezone
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

import pandas as pd
import numpy as np

from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
OHLCV = ROOT / "data" / "v095_ohlcv_cache.pkl"
FNG = ROOT / "data" / "alt_data" / "fng_daily.csv"

# --- Maliyet parametreleri (lab_honest_cost_rebaseline.py ile BIREBIR) ---
EXTRA_BPS = 55.0          # round-trip ek maliyet (fee +15 + slippage +40)
SLIP_PYR = 0.06           # pyramid leg slippage erozyon katsayisi

PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R = 1.0
TP2_R = 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)

# --- Correlation gate (c2v5 YAML correlation_gate block) ---
CORR_THRESHOLD = 0.70     # max_pairwise_corr
CORR_REDUCTION = 0.50     # reduction_factor — 0.5x size if corr>0.7
CORR_HARD_BLOCK = 0.90    # hard_block_at — full skip if corr>0.9
CORR_WINDOW_DAYS = 30     # rolling correlation window (daily-return proxy)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]

TOP4_NAMES = {
    "vsa_climax_test", "brooks_failed_breakout",
    "anchored_vwap_reversal", "engulfing_continuation",
}


# ============================================================================
# Helpers
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, new_close):
    """Pool R'si engine close 30/30/40 blendi. 25/25/50'ye gecis (re-baseline §4.1
    ile birebir — underdetermined MFE trade'leri pool R'sinde birak)."""
    R = t["R"]
    pk = t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        return c1n * TP1_R + (1.0 - c1n) * R_rest
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        return R  # underdetermined — neutral
    return c1n * TP1_R + c2n * TP2_R + crn * R_run


# ============================================================================
# F1-F4 regime filter (sec54_6d_regime_filter_replay.py ile BIREBIR)
# ============================================================================
def build_btc_regime_table(ohlcv_cache, fng_df):
    btc = ohlcv_cache["BTC/USDT"].copy()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
    btc["date"] = btc["ts"].dt.normalize()
    btc = btc.sort_values("date").reset_index(drop=True)
    btc["daily_ret"] = btc["close"].pct_change()
    btc["vol_7d"] = btc["daily_ret"].rolling(7).std()
    btc["vol_7d_ann"] = btc["vol_7d"] * math.sqrt(365) * 100
    fng = fng_df.copy()
    fng["date"] = pd.to_datetime(fng["date"], utc=True).dt.normalize()
    fng = fng[["date", "value"]].rename(columns={"value": "fng_value"})
    btc = btc.merge(fng, on="date", how="left")
    btc["fng_value"] = btc["fng_value"].ffill()
    out = btc[["date", "atr_pct", "ret_30", "above_ema200", "fng_value",
               "vol_7d_ann"]].copy()
    return out.set_index("date").sort_index()


def get_t1_regime(regime_tbl, entry_ts):
    entry_date = entry_ts.normalize() - pd.Timedelta(days=1)
    if entry_date not in regime_tbl.index:
        prior = regime_tbl.index[regime_tbl.index <= entry_date]
        if len(prior) == 0:
            return None
        entry_date = prior[-1]
    row = regime_tbl.loc[entry_date]
    return {
        "atr_pct": float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
        "ret_30": float(row["ret_30"]) if pd.notna(row["ret_30"]) else None,
        "above_ema200": bool(row["above_ema200"]) if pd.notna(row["above_ema200"]) else None,
        "fng_value": float(row["fng_value"]) if pd.notna(row["fng_value"]) else None,
        "vol_7d_ann": float(row["vol_7d_ann"]) if pd.notna(row["vol_7d_ann"]) else None,
    }


def f1_avwap_range(t, rg):
    if t.get("strategy") != "anchored_vwap_reversal":
        return False
    if rg is None or rg["atr_pct"] is None or rg["ret_30"] is None:
        return False
    return rg["atr_pct"] < 3.0 and abs(rg["ret_30"]) < 3.0


def f2_brooks_bull_short(t, rg):
    if t.get("strategy") != "brooks_failed_breakout" or t.get("side") != "short":
        return False
    if rg is None or rg["above_ema200"] is None or rg["ret_30"] is None:
        return False
    return rg["above_ema200"] and rg["ret_30"] > 5.0


def f3_vsa_bear_long(t, rg):
    if t.get("strategy") != "vsa_climax_test" or t.get("side") != "long":
        return False
    if rg is None or rg["fng_value"] is None or rg["ret_30"] is None:
        return False
    return rg["fng_value"] < 15 and rg["ret_30"] < -10.0


def f4_engulfing_high_vol(t, rg):
    if t.get("strategy") != "engulfing_continuation":
        return False
    if rg is None or rg["vol_7d_ann"] is None:
        return False
    return rg["vol_7d_ann"] > 100.0


FILTERS = [f1_avwap_range, f2_brooks_bull_short, f3_vsa_bear_long, f4_engulfing_high_vol]
FILTER_NAMES = ["F1", "F2", "F3", "F4"]


def apply_regime_filters(pool, regime_tbl):
    """F1-F4 uygula. SKIP edilen trade'i pool'dan cikar. (filtered_pool, stats)."""
    out = []
    skip_counts = {n: 0 for n in FILTER_NAMES}
    skipped_trades = []
    for t in pool:
        try:
            ets = pd.Timestamp(t["entry_ts"])
            if ets.tzinfo is None:
                ets = ets.tz_localize("UTC")
        except Exception:
            out.append(t)
            continue
        rg = get_t1_regime(regime_tbl, ets)
        skip = False
        for fn, name in zip(FILTERS, FILTER_NAMES):
            if fn(t, rg):
                skip_counts[name] += 1
                skipped_trades.append(t)
                skip = True
                break
        if not skip:
            out.append(t)
    return out, {"skip_counts": skip_counts, "n_in": len(pool), "n_out": len(out),
                 "skipped": skipped_trades}


# ============================================================================
# Correlation gate model
# ============================================================================
# c2v5 YAML: correlation_gate {enabled: true, max_pairwise_corr: 0.7,
#   reduction_factor: 0.5, hard_block_at: 0.9}.
# lab.py satir 350: cg config OKUNUYOR ama ProductionConfig'e GECMIYOR ->
#   backtest correlation gate UYGULAMIYOR (G17 dogru).
#
# MODEL: Sabit-risk R-bazli replay'de "notional %50 kucult" = "o trade'in R
# katkisini %50 kucult" (R = realized PnL / risk; risk yariya inerse PnL de
# yariya iner, R sabit ama equity'ye katki yarisi -> equivalent: R'yi 0.5x).
#
# Gate karari: bir trade ACILIRKEN, ayni anda ACIK olan diger pozisyonlarla
# sembol-bazli rolling-30g korelasyonu kontrol et. Eger ACIK pozisyonlardan
# herhangi biriyle corr > 0.7 -> bu trade 0.5x. corr > 0.9 -> hard block (skip).
#
# YON NOTU: YAML "pairwise return 15m bar bazli" diyor; bu model GUNLUK getiri
# rolling-30g proxy kullanir. Gunluk korelasyon 15m korelasyondan tipik olarak
# HAFIF YUKSEKtir (intraday gurultu daha az) -> bu model gate'i biraz FAZLA
# tetikler. Yani correlation gate'in honest tabloya etkisi bu modelde UST-SINIR
# (gercek 15m-bar gate biraz daha az tetikler). Crypto majors zaten yuksek
# korelasyonlu (45 ciftin %42'si full-period rho>0.7) -> gate cok sik aktif.
def build_corr_lookup(ohlcv_cache, window=CORR_WINDOW_DAYS):
    """Rolling-30g sembol korelasyon matrislerini PRE-COMPUTE et (causal).

    Donen: (corr_by_date, sym_idx)
      corr_by_date: dict[pd.Timestamp(normalized) -> np.ndarray NxN corr]
      sym_idx: dict[symbol -> int]

    Performans: O(n_dates) tek gecis, her tarihte 1 corr matrix. Sonra
    corr_at() sadece dict + array lookup -> O(1).
    """
    rets = {}
    for s in SYMBOLS:
        df = ohlcv_cache[s].copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.normalize()
        df = df.sort_values("ts").drop_duplicates("ts", keep="last")
        rets[s] = df.set_index("ts")["close"].pct_change()
    R = pd.DataFrame(rets).sort_index()
    sym_idx = {s: i for i, s in enumerate(SYMBOLS)}
    corr_by_date = {}
    dates = list(R.index)
    arr = R[SYMBOLS].values  # n_dates x n_syms
    for i, d in enumerate(dates):
        lo = max(0, i - window + 1)
        win = arr[lo:i + 1]
        if win.shape[0] < 10:
            corr_by_date[d] = None
            continue
        # nan-aware corr
        cm = pd.DataFrame(win, columns=SYMBOLS).corr().values
        corr_by_date[d] = cm
    sorted_dates = np.array([d.value for d in dates])  # int64 ns for searchsorted
    return {"corr_by_date": corr_by_date, "sym_idx": sym_idx,
            "dates": dates, "sorted_dates": sorted_dates}


def corr_at(clook, date, sym_a, sym_b):
    """sym_a vs sym_b rolling-window korelasyon, date'e kadar (causal). O(1)."""
    if sym_a == sym_b:
        return 1.0
    si = clook["sym_idx"]
    if sym_a not in si or sym_b not in si:
        return 0.0
    # find most recent date <= query date
    dval = pd.Timestamp(date).value
    sd = clook["sorted_dates"]
    pos = int(np.searchsorted(sd, dval, side="right")) - 1
    if pos < 0:
        return 0.0
    d = clook["dates"][pos]
    cm = clook["corr_by_date"].get(d)
    if cm is None:
        return 0.0
    c = cm[si[sym_a], si[sym_b]]
    return float(c) if not (c != c) else 0.0  # nan check


def apply_correlation_gate(pool, R_daily, mode="reduce_only"):
    """Correlation gate modeli.

    mode:
      'full'        — corr>0.9 hard-block + corr>0.7 0.5x reduce.
      'reduce_only' — corr>0.7 0.5x reduce, hard-block KAPALI.

    ARTEFAKT UYARISI: ilk koşum 'full' modunda %87.5 trade hard-block etti
    (293785/336000). Sebep: crypto majors rolling-30g pairwise korelasyon
    medyani 0.774, %11 cift >0.9 (olcum kaniti). Bu modelde "acik pozisyon
    listesi" buyudukce yeni trade'in en az biriyle >0.9 bulma olasiligi
    patliyor -> gate fiilen "ilk pozisyon haric hepsini blokla" oluyor. Bu
    CANLI gate davranisi DEGIL — canli gate max_concurrent (16) ile sinirli,
    ve dominant mekanizma reduction_factor (0.5x), hard_block (0.9) nadir.
    -> 'reduce_only' DURUST varsayilan. 'full' duyarlilik bandi olarak ayrica
    raporlanir (UST-SINIR artefakt).

    pool R'leri ZATEN honest+filter sonrasi. Bu fonksiyon R'yi corr-scale eder.

    Sabit-risk R-bazli model: gate "notional %50 kucult" der; R-bazlida
    o trade'in equity'ye katki agirligini %50'ye indirmek = R'yi 0.5x.
    """
    evs = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    out = []
    n_reduced = 0
    n_blocked = 0
    n_clear = 0
    open_positions = []  # (exit_ts, symbol)
    for t in evs:
        ets = to_utc(t["entry_ts"])
        xts = to_utc(t["exit_ts"])
        date = ets.normalize()
        open_positions = [(ox, os_) for (ox, os_) in open_positions if ox > ets]
        max_corr = 0.0
        for (ox, osym) in open_positions:
            c = corr_at(R_daily, date, t["symbol"], osym)
            if c > max_corr:
                max_corr = c
        t2 = dict(t)
        if mode == "full" and max_corr > CORR_HARD_BLOCK:
            n_blocked += 1
            continue
        elif max_corr > CORR_THRESHOLD:
            t2["R"] = t2["R"] * CORR_REDUCTION
            n_reduced += 1
        else:
            n_clear += 1
        out.append(t2)
        open_positions.append((xts, t["symbol"]))
    return out, {"n_reduced": n_reduced, "n_blocked": n_blocked,
                 "n_clear": n_clear, "n_in": len(pool), "n_out": len(out)}


# ============================================================================
# Pool builders
# ============================================================================
def apply_cost_and_pyramid(pool, mode):
    """mode 'idealized' or 'honest'. R'yi maliyet + pyramid IDEAL ile adjust et."""
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
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
                if mode == "honest":
                    radj -= extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


# ============================================================================
# Metrics
# ============================================================================
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
    annual = (comp ** (12.0 / n) - 1) * 100
    worst_dd = min(dds) if dds else 0
    rets_sorted = sorted(rets)
    median = rets_sorted[n // 2] if n % 2 else (rets_sorted[n // 2 - 1] + rets_sorted[n // 2]) / 2
    # top-5 ay haric compound
    rest = sorted(rets, reverse=True)[5:]
    comp_rest = 1.0
    for x in rest:
        comp_rest *= (1 + x / 100)
    annual_rest = (comp_rest ** (12.0 / len(rest)) - 1) * 100 if rest else 0
    return {
        "n": n, "mean": mu, "median": median, "annual": annual,
        "annual_ex_top5": annual_rest,
        "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "max_gain": max(rets),
        "worst_month_dd": worst_dd, "rets": rets,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
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


# ============================================================================
# Main
# ============================================================================
def main():
    print("=" * 92, flush=True)
    print("LAB — FILTERED HONEST RE-RUN  (Phoenix 15m C2+V5)", flush=True)
    print("=" * 92, flush=True)

    # --- Load ---
    print("[load] pool: %s" % POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool_raw = pickle.load(f)
    h = hashlib.sha256()
    with POOL.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    print("  pool sha256: %s  trades: %d" % (h.hexdigest()[:16], len(pool_raw)), flush=True)

    pool_top4 = [t for t in pool_raw if t.get("strategy") in TOP4_NAMES]
    print("  TOP-4 filtered: %d trade  date %s -> %s" % (
        len(pool_top4), pool_top4[0]["entry_ts"], pool_top4[-1]["entry_ts"]), flush=True)
    # NOTE: pool_raw==pool_top4 ise hepsi TOP-4. honest re-baseline FULL pool
    # kullandi (373675). Filter karsilastirma adil olsun diye 3 senaryo da
    # AYNI base'i kullanir. Re-baseline FULL pool oldugundan FULL base seriz.
    base_pool = pool_raw
    print("  base pool (3 senaryo ortak): %d trade" % len(base_pool), flush=True)
    n_non_top4 = len([t for t in pool_raw if t.get("strategy") not in TOP4_NAMES])
    print("  non-TOP4 strateji trade: %d (F1-F4 bunlara dokunmaz)" % n_non_top4, flush=True)

    print("[load] OHLCV cache + F&G", flush=True)
    with OHLCV.open("rb") as f:
        ohlcv = pickle.load(f)
    fng_df = pd.read_csv(FNG)
    regime_tbl = build_btc_regime_table(ohlcv, fng_df)
    R_daily = build_corr_lookup(ohlcv)
    print("  regime table: %d rows  corr matrices pre-computed: %d dates" % (
        len(regime_tbl), len(R_daily["corr_by_date"])), flush=True)

    # --- Config ---
    base_cfg = ProductionConfig.from_yaml(str(YAML))
    cfg = base_cfg.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0,
    )

    # ========================================================================
    # SENARYO 1: IDEALIZED
    # ========================================================================
    print("\n[scenario 1] IDEALIZED — fee=0, close 30/30/40, no filter", flush=True)
    p_ideal = apply_cost_and_pyramid(base_pool, "idealized")
    r_ideal = per_month(p_ideal, cfg)
    wf_ideal = walk_forward(p_ideal, cfg)
    r_ideal["sumR"] = pool_sumR(p_ideal)

    # ========================================================================
    # SENARYO 2: HONEST no-filter
    # ========================================================================
    print("[scenario 2] HONEST no-filter — +55bps, close 25/25/50, no filter", flush=True)
    p_honest = apply_cost_and_pyramid(base_pool, "honest")
    r_honest = per_month(p_honest, cfg)
    wf_honest = walk_forward(p_honest, cfg)
    r_honest["sumR"] = pool_sumR(p_honest)

    # ========================================================================
    # SENARYO 3: HONEST + FILTRELER
    # ========================================================================
    print("[scenario 3] HONEST + F1-F4 regime filter + correlation gate", flush=True)
    # Adim 1: F1-F4 regime filter (RAW pool uzerinde — strateji+side+rejim)
    pool_f, fstats = apply_regime_filters(base_pool, regime_tbl)
    print("  F1-F4 skip: %s  total %d -> %d (%.2f%% skip)" % (
        fstats["skip_counts"], fstats["n_in"], fstats["n_out"],
        (fstats["n_in"] - fstats["n_out"]) / fstats["n_in"] * 100), flush=True)
    # skipped trade'lerin honest-R'si — kotuluk teshisi
    skipped_honest = apply_cost_and_pyramid(fstats["skipped"], "honest")
    kept_honest_pre = apply_cost_and_pyramid(pool_f, "honest")
    if skipped_honest:
        sk_sumR = pool_sumR(skipped_honest)
        sk_meanR = sk_sumR / len(skipped_honest)
        print("  skip edilen %d trade honest-sumR: %+.1f R  meanR %+.4f R" % (
            len(skipped_honest), sk_sumR, sk_meanR), flush=True)
    kept_meanR = pool_sumR(kept_honest_pre) / max(len(kept_honest_pre), 1)
    print("  kalan %d trade honest-meanR: %+.4f R" % (
        len(kept_honest_pre), kept_meanR), flush=True)

    # Adim 2: honest maliyet + pyramid (filtered pool uzerinde)
    p_filt_honest = apply_cost_and_pyramid(pool_f, "honest")

    # Adim 3: correlation gate — DURUST varsayilan reduce_only (hard-block KAPALI)
    p_filt_gated, gstats = apply_correlation_gate(p_filt_honest, R_daily,
                                                   mode="reduce_only")
    print("  corr gate [reduce_only]: clear %d  reduced(0.5x) %d  -> %d trade" % (
        gstats["n_clear"], gstats["n_reduced"], gstats["n_out"]), flush=True)

    r_filt = per_month(p_filt_gated, cfg)
    wf_filt = walk_forward(p_filt_gated, cfg)
    r_filt["sumR"] = pool_sumR(p_filt_gated)

    # Duyarlilik: 'full' mode (hard-block ON) — ARTEFAKT UST-SINIR
    p_filt_full, gstats_full = apply_correlation_gate(p_filt_honest, R_daily,
                                                       mode="full")
    print("  corr gate [full/ARTEFAKT]: clear %d  reduced %d  hard-block %d  -> %d" % (
        gstats_full["n_clear"], gstats_full["n_reduced"], gstats_full["n_blocked"],
        gstats_full["n_out"]), flush=True)
    r_filt_full = per_month(p_filt_full, cfg)
    sumR_filt_full = pool_sumR(p_filt_full)

    # --- Ara nokta: sadece F1-F4 (correlation gate yok) ---
    r_filt_only = per_month(p_filt_honest, cfg)
    sumR_filt_only = pool_sumR(p_filt_honest)

    # ========================================================================
    # SONUC TABLOSU
    # ========================================================================
    print("\n" + "=" * 100, flush=True)
    print("3-NOKTA KARSILASTIRMA  (Phoenix 15m C2+V5)", flush=True)
    print("=" * 100, flush=True)
    hdr = "%-26s%11s%10s%9s%9s%11s%9s%7s%13s" % (
        "senaryo", "yillik", "mean", "median", "neg", "maxloss", "r-adj",
        "CV", "pool-sumR")
    print(hdr, flush=True)
    print("-" * 100, flush=True)
    rows = [
        ("1. IDEALIZED (referans)", r_ideal),
        ("2. HONEST no-filter", r_honest),
        ("3. HONEST + FILTRELER", r_filt),
    ]
    for label, r in rows:
        print("%-26s%+10.1f%%%+9.2f%%%+8.2f%%%5d/%d%+10.2f%%%9.2f%6.0f%%%+13.0f" % (
            label, r["annual"], r["mean"], r["median"], r["neg"], r["n"],
            r["max_loss"], r["r_adj"], r["cv"], r["sumR"]), flush=True)

    print("\n  --- ara nokta: HONEST + F1-F4 only (correlation gate YOK) ---", flush=True)
    print("  yillik %+.1f%%  mean %+.2f%%  neg %d/%d  pool-sumR %+.0f R" % (
        r_filt_only["annual"], r_filt_only["mean"], r_filt_only["neg"],
        r_filt_only["n"], sumR_filt_only), flush=True)
    print("  --- duyarlilik: HONEST + F1-F4 + corr gate [full/ARTEFAKT %d hard-block] ---" % (
        gstats_full["n_blocked"]), flush=True)
    print("  yillik %+.1f%%  mean %+.2f%%  median %+.2f%%  neg %d/%d  pool-sumR %+.0f R" % (
        r_filt_full["annual"], r_filt_full["mean"], r_filt_full["median"],
        r_filt_full["neg"], r_filt_full["n"], sumR_filt_full), flush=True)
    print("  -> bu varyant %d/%d trade hard-block ediyor — modelleme artefakti, GUVENILMEZ" % (
        gstats_full["n_blocked"], gstats_full["n_in"]), flush=True)

    print("\n  --- ek metrikler ---", flush=True)
    for label, r in rows:
        print("  %-26s top-5 ay haric yillik %+8.1f%%  max_gain %+.2f%%  wmDD %+.1f%%" % (
            label, r["annual_ex_top5"], r["max_gain"], r["worst_month_dd"]), flush=True)

    # --- Walk-forward ---
    print("\n" + "=" * 78, flush=True)
    print("WALK-FORWARD (2y train / 90d OOS / 30d step) — OOS robustness", flush=True)
    print("=" * 78, flush=True)
    print("%-26s%13s%11s%9s%9s" % (
        "senaryo", "mean_ann", "mean_dd", "r-adj", "neg/win"), flush=True)
    print("-" * 70, flush=True)
    for label, wf in [("1. IDEALIZED", wf_ideal), ("2. HONEST no-filter", wf_honest),
                       ("3. HONEST + FILTRELER", wf_filt)]:
        if wf is None:
            print("%-26s  (no windows)" % label, flush=True)
            continue
        print("%-26s%+12.1f%%%+10.1f%%%9.2f%6d/%d" % (
            label, wf["mean_annual"], wf["mean_dd"], wf["r_adj"],
            wf["neg"], wf["windows"]), flush=True)

    # --- Decomposition: filtre etkisi ---
    print("\n" + "=" * 78, flush=True)
    print("FILTRE ETKI DEKOMPOZISYON (HONEST baz)", flush=True)
    print("=" * 78, flush=True)
    print("  %-40s yillik %+9.1f%%  neg %2d  sumR %+9.0f R" % (
        "HONEST no-filter", r_honest["annual"], r_honest["neg"], r_honest["sumR"]),
        flush=True)
    print("  %-40s yillik %+9.1f%%  neg %2d  sumR %+9.0f R" % (
        "+ F1-F4 regime filter", r_filt_only["annual"], r_filt_only["neg"],
        sumR_filt_only), flush=True)
    print("  %-40s yillik %+9.1f%%  neg %2d  sumR %+9.0f R" % (
        "+ correlation gate (HONEST+FILTRELER)", r_filt["annual"], r_filt["neg"],
        r_filt["sumR"]), flush=True)
    print("\n  F1-F4 tek-basina pool-sumR etkisi:    %+.1f R" % (
        sumR_filt_only - r_honest["sumR"]), flush=True)
    print("  correlation gate ek pool-sumR etkisi:  %+.1f R" % (
        r_filt["sumR"] - sumR_filt_only), flush=True)
    print("  toplam (HONEST -> HONEST+FILTRELER):   %+.1f R" % (
        r_filt["sumR"] - r_honest["sumR"]), flush=True)

    # --- VERDICT ---
    print("\n" + "=" * 92, flush=True)
    print("NET HUKUM", flush=True)
    print("=" * 92, flush=True)
    pos_pool = r_filt["sumR"] > 0
    print("  HONEST+FILTRELER pool-sumR: %+.1f R  -> %s" % (
        r_filt["sumR"], "POZITIF" if pos_pool else "NEGATIF"), flush=True)
    print("  HONEST+FILTRELER medyan ay: %+.2f%%" % r_filt["median"], flush=True)
    print("  HONEST+FILTRELER yillik:    %+.1f%%  (top-5 ay haric %+.1f%%)" % (
        r_filt["annual"], r_filt["annual_ex_top5"]), flush=True)
    print("  HONEST+FILTRELER neg ay:    %d/%d" % (r_filt["neg"], r_filt["n"]), flush=True)
    if pos_pool and r_filt["annual_ex_top5"] > 10 and r_filt["neg"] <= r_filt["n"] * 0.35:
        verdict = "EVET — 15m phoenix C2+V5 F1-F4 + correlation gate ile KURTARILABILIR"
    else:
        verdict = "HAYIR — F1-F4 + correlation gate yetmiyor. 15m TF yapisal fee-mezar."
    print("\n  VERDICT: %s" % verdict, flush=True)
    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
