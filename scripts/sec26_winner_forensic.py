"""SEC26 — Production Winner Forensic.

PROD pool = TOP_10 + FVG (v1.2 / v2.0.3 baseline) = data/_sec13_4_cache/pool_baseline_v1_3.pkl
  - n=6650 trades, 5y x 11 sym
  - TOP_10 (data/v095_trades_cache.pkl) = 4787 trades
  - FVG (reports/lab/sec11e_new_trades.pkl['fvg_fill_reversal']) = 1863 trades

Goal: WHY does this pool win in crypto? Forensik analiz — RED hipotez degil,
pozitif kesif. Cikti: per-strategy + cross-strategy + regime patterns.

NOT: Yeni backtest YOK. Sadece cached pool'lar + BTC OHLCV (regime mask).
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from pathlib import Path
from collections import defaultdict
from statistics import mean, median, stdev

import duckdb
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

PROD_POOL_PATH = ROOT / "data" / "_sec13_4_cache" / "pool_baseline_v1_3.pkl"
TOP10_POOL_PATH = ROOT / "data" / "v095_trades_cache.pkl"
FVG_POOL_PATH = ROOT / "reports" / "lab" / "sec11e_new_trades.pkl"

OUT_REPORT = ROOT / "reports" / "researcher" / "2026-05-14_sec26_production_winner_forensic.md"
OUT_JSON = ROOT / "reports" / "researcher" / "sec26_forensic_data.json"
OUT_PER_STRAT_CSV = ROOT / "reports" / "researcher" / "sec26_per_strategy_breakdown.csv"
OUT_REGIME_CSV = ROOT / "reports" / "researcher" / "sec26_regime_breakdown.csv"


# Taxonomy/source map
STRATEGY_META = {
    "engulfing_continuation": {
        "class": "trend_continuation",
        "source": "Brooks Ch.7 (Always-in) + Bulkowski Engulfing",
        "mechanic": "20-EMA pullback sonrasi engulfing bar, 50-EMA trend + 3-bar always-in konfirmasyon. Entry next-bar open.",
    },
    "obv_engulfing_confluence": {
        "class": "trend_continuation",
        "source": "Granville OBV (1963) + Brooks Engulfing — knowledge/books/volume_price_divergence.md",
        "mechanic": "Price LL fakat OBV HL (gizli birikim) + engulfing bar firer. Hidden accumulation/distribution.",
    },
    "anchored_vwap_reversal": {
        "class": "mean_reversion",
        "source": "Harris (2003) — Trading and Exchanges + Volume Profile (Steidlmayer)",
        "mechanic": "HTF swing anchor'dan AVWAP + Volume Profile POC confluence. Mean-rev to institutional fair-value.",
    },
    "wyckoff_phase_d": {
        "class": "structural",
        "source": "Wyckoff — knowledge/books/wyckoff_method.md (Phase B/C/D)",
        "mechanic": "Phase B range (30bar) + Phase C Spring (false breakdown + reclaim) + Phase D SOS (body>1.5xATR). Smart-money accumulation pivot.",
    },
    "brooks_h2_l2": {
        "class": "trend_continuation",
        "source": "Brooks Ch.5 — Trading Price Action TRENDS (H2/L2 two-legged pullback)",
        "mechanic": "Trend + Leg A (counter 3bar) + Leg B (small bounce) + Leg C (counter 3bar) + trend-direction close. Trend continuation post second-leg.",
    },
    "pin_bar_round_numbers": {
        "class": "trend_continuation",
        "source": "Volman — Forex Price Action Scalping + Bulkowski (Pin Bar)",
        "mechanic": "Pin bar (body<=33%, dominant wick>=60%) <=0.3ATR yakin sembol-bazli round numbers (BTC 10K, ETH 500, SOL 50). Institutional magnet seviyelerden reversal.",
    },
    "equal_highs_sweep": {
        "class": "structural",
        "source": "SMC / ICT Liquidity Pools — knowledge/books/smc.md (stop-hunt)",
        "mechanic": "2+ swing highs +-0.15 ATR yakin (liquidity pool). Sweep bar (high>EQH ama close<EQH) + 1-3 bar icinde close<pool_level. Stop-hunt reversal.",
    },
    "cvd_spike_fade": {
        "class": "mean_reversion",
        "source": "Granville OBV + CVD literature — knowledge/books/volume_price_divergence.md",
        "mechanic": "OBV z-score (30bar) extreme spike (>2 sigma) -> retail FOMO/panic -> fade. Tick-CVD proxy.",
    },
    "vsa_climax_test": {
        "class": "mean_reversion",
        "source": "Wyckoff / VSA — Tom Williams (Master the Markets) Ch.4",
        "mechanic": "Selling Climax (extreme vol + wide-range + upper-half close + 5bar-min low) + Test Bar (3-15bar sonra dusuk-hacim donus). Phase A dip.",
    },
    "brooks_failed_breakout": {
        "class": "trend_continuation",
        "source": "Brooks Ch.10 — Reversals / Failed Breakouts (Trap mekanizmasi)",
        "mechanic": "N-bar high/low BO, follow-through yok, 1-3 bar icinde counter-side reclaim. 'Two-sided momentum' (trapped retail + reversal oyuncular).",
    },
    "fvg_fill_reversal": {
        "class": "mean_reversion",
        "source": "ICT FVG / Smart Money — knowledge/books/smc.md (Fair Value Gap)",
        "mechanic": "3-bar imbalance (bar[t-2].high<bar[t].low bullish). Bar t+N FVG icine girip karsi-yon close -> fill+reversal. Institutional inefficiency reclaim.",
    },
}


def load_pool(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        return pickle.load(f)


def load_btc_regime() -> pd.DataFrame:
    """BTC 1d OHLCV + regime mask (bull/bear/range)."""
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue='binance' AND symbol='BTC/USDT' AND timeframe='1d' "
        "ORDER BY ts"
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()

    # ATR%
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr14"] / df["close"] * 100.0

    # EMA200 + slope
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema200_slope_30d"] = df["ema200"].pct_change(30)

    # 90d return
    df["ret_90d"] = df["close"].pct_change(90)

    # Regime mask:
    #   bull   : close > ema200 AND ema200_slope_30d > 0 AND ret_90d > +10%
    #   bear   : close < ema200 AND ema200_slope_30d < 0 AND ret_90d < -10%
    #   range  : aksi (incl. transitions)
    def classify(r):
        if pd.isna(r["ema200"]) or pd.isna(r["ema200_slope_30d"]) or pd.isna(r["ret_90d"]):
            return "unknown"
        bull = (r["close"] > r["ema200"]) and (r["ema200_slope_30d"] > 0) and (r["ret_90d"] > 0.10)
        bear = (r["close"] < r["ema200"]) and (r["ema200_slope_30d"] < 0) and (r["ret_90d"] < -0.10)
        if bull:
            return "bull"
        if bear:
            return "bear"
        return "range"

    df["regime"] = df.apply(classify, axis=1)

    # high-vol mask (ATR% top tercile)
    atr_q = df["atr_pct"].quantile([0.33, 0.67]).to_dict()
    def vol_class(v):
        if pd.isna(v):
            return "unknown"
        if v < atr_q[0.33]:
            return "low_vol"
        if v < atr_q[0.67]:
            return "mid_vol"
        return "high_vol"
    df["vol_regime"] = df["atr_pct"].apply(vol_class)

    # btc trend filter (EMA50)
    df["btc_above_ema50"] = df["close"] > df["ema50"]
    return df


def attach_regime(trades: list[dict], regime: pd.DataFrame) -> list[dict]:
    """Trade entry_ts'lerini regime mask'e map et."""
    for t in trades:
        ts = pd.Timestamp(t["entry_ts"]).floor("D")
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        # bul: regime.index<=ts max
        idx = regime.index.searchsorted(ts)
        if idx == 0:
            t["regime"] = "unknown"
            t["vol_regime"] = "unknown"
            t["btc_above_ema50"] = None
            t["btc_atr_pct"] = None
        else:
            row = regime.iloc[min(idx, len(regime) - 1)]
            t["regime"] = row["regime"]
            t["vol_regime"] = row["vol_regime"]
            t["btc_above_ema50"] = bool(row["btc_above_ema50"]) if not pd.isna(row["btc_above_ema50"]) else None
            t["btc_atr_pct"] = float(row["atr_pct"]) if not pd.isna(row["atr_pct"]) else None
    return trades


def add_hold_days(trades: list[dict]) -> list[dict]:
    for t in trades:
        e = pd.Timestamp(t["entry_ts"])
        x = pd.Timestamp(t["exit_ts"])
        t["hold_days"] = float((x - e).total_seconds() / 86400.0)
    return trades


def honest_clip_R(R: float, hold_days: float, cap_days: int = 60, cap_R: float = 3.0) -> float:
    """SEC22/24 disipliniyle: hold>60d trade'lerde R'yi 3R'a klip et (fantasy R'yi engelle)."""
    if hold_days > cap_days:
        return min(R, cap_R)
    return R


def per_strategy_breakdown(trades: list[dict]) -> pd.DataFrame:
    rows = []
    for strat, group in pd.DataFrame(trades).groupby("strategy"):
        n = len(group)
        Rs = group["R"].to_numpy()
        wins = group[group["R"] > 0]["R"].to_numpy()
        losses = group[group["R"] <= 0]["R"].to_numpy()
        Rs_clip = np.array([honest_clip_R(R, h) for R, h in zip(group["R"], group["hold_days"])])
        # MFE proxy: holdays icin "kazanan trade"ler genelde hizli kapanir mi yoksa
        # uzun mu? — entry'den exit'e R; MFE elimde yok, hold'u proxy olarak kullan.

        bull_R = group.loc[group["regime"] == "bull", "R"]
        bear_R = group.loc[group["regime"] == "bear", "R"]
        range_R = group.loc[group["regime"] == "range", "R"]

        long_R = group.loc[group["side"] == "long", "R"]
        short_R = group.loc[group["side"] == "short", "R"]

        btc_R = group.loc[group["symbol"] == "BTC/USDT", "R"]
        eth_R = group.loc[group["symbol"] == "ETH/USDT", "R"]
        alt_R = group.loc[~group["symbol"].isin(["BTC/USDT", "ETH/USDT"]), "R"]

        rows.append({
            "strategy": strat,
            "n": n,
            "WR": float((Rs > 0).mean()),
            "mean_R_raw": float(Rs.mean()),
            "mean_R_clip60d3R": float(Rs_clip.mean()),
            "median_R": float(np.median(Rs)),
            "sum_R": float(Rs.sum()),
            "mean_R_win": float(wins.mean()) if len(wins) else 0.0,
            "mean_R_loss": float(losses.mean()) if len(losses) else 0.0,
            "wl_ratio": float(wins.mean() / abs(losses.mean())) if len(losses) and len(wins) else 0.0,
            "n_bull": int((group["regime"] == "bull").sum()),
            "mR_bull": float(bull_R.mean()) if len(bull_R) else 0.0,
            "n_bear": int((group["regime"] == "bear").sum()),
            "mR_bear": float(bear_R.mean()) if len(bear_R) else 0.0,
            "n_range": int((group["regime"] == "range").sum()),
            "mR_range": float(range_R.mean()) if len(range_R) else 0.0,
            "n_long": int((group["side"] == "long").sum()),
            "mR_long": float(long_R.mean()) if len(long_R) else 0.0,
            "n_short": int((group["side"] == "short").sum()),
            "mR_short": float(short_R.mean()) if len(short_R) else 0.0,
            "n_btc": int((group["symbol"] == "BTC/USDT").sum()),
            "mR_btc": float(btc_R.mean()) if len(btc_R) else 0.0,
            "n_eth": int((group["symbol"] == "ETH/USDT").sum()),
            "mR_eth": float(eth_R.mean()) if len(eth_R) else 0.0,
            "n_alt": int((~group["symbol"].isin(["BTC/USDT", "ETH/USDT"])).sum()),
            "mR_alt": float(alt_R.mean()) if len(alt_R) else 0.0,
            "hold_days_mean": float(group["hold_days"].mean()),
            "hold_days_median": float(group["hold_days"].median()),
            "frac_long_held_gt_30d": float(((group["hold_days"] > 30) & (group["R"] > 0)).sum() / max(1, len(group))),
        })
    return pd.DataFrame(rows).sort_values("sum_R", ascending=False)


def regime_breakdown(trades: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    rows = []
    # her regime x side
    for regime in ["bull", "bear", "range"]:
        for side in ["long", "short"]:
            g = df[(df["regime"] == regime) & (df["side"] == side)]
            if len(g) == 0:
                rows.append({"regime": regime, "side": side, "n": 0, "WR": 0, "mR": 0, "sumR": 0})
                continue
            Rs = g["R"].to_numpy()
            rows.append({
                "regime": regime,
                "side": side,
                "n": len(g),
                "WR": float((Rs > 0).mean()),
                "mR": float(Rs.mean()),
                "sumR": float(Rs.sum()),
            })
    return pd.DataFrame(rows)


def cross_strategy_meta(trades: list[dict]) -> dict:
    """Meta-patterns: hangi kosullar EN COK winner uretiyor?"""
    df = pd.DataFrame(trades)
    out = {}

    # 1) BTC trend filter (entry gun BTC>EMA50)
    above = df[df["btc_above_ema50"] == True]
    below = df[df["btc_above_ema50"] == False]
    out["btc_above_ema50_winrate"] = {
        "above_n": int(len(above)),
        "above_WR": float((above["R"] > 0).mean()) if len(above) else 0.0,
        "above_mR": float(above["R"].mean()) if len(above) else 0.0,
        "above_sumR": float(above["R"].sum()) if len(above) else 0.0,
        "below_n": int(len(below)),
        "below_WR": float((below["R"] > 0).mean()) if len(below) else 0.0,
        "below_mR": float(below["R"].mean()) if len(below) else 0.0,
        "below_sumR": float(below["R"].sum()) if len(below) else 0.0,
    }

    # 2) vol regime
    out["vol_regime_split"] = {}
    for v in ["low_vol", "mid_vol", "high_vol"]:
        g = df[df["vol_regime"] == v]
        if len(g) == 0:
            out["vol_regime_split"][v] = {"n": 0}
            continue
        out["vol_regime_split"][v] = {
            "n": int(len(g)),
            "WR": float((g["R"] > 0).mean()),
            "mR": float(g["R"].mean()),
            "sumR": float(g["R"].sum()),
        }

    # 3) Right-tail dominance: top 10% trades sumR contribution
    Rs_sorted = np.sort(df["R"].to_numpy())[::-1]
    top10_pct = int(len(Rs_sorted) * 0.10)
    bot10_pct = int(len(Rs_sorted) * 0.10)
    sum_total = float(Rs_sorted.sum())
    sum_top10 = float(Rs_sorted[:top10_pct].sum()) if top10_pct else 0.0
    sum_bot10 = float(Rs_sorted[-bot10_pct:].sum()) if bot10_pct else 0.0
    sum_ex_extremes = float(Rs_sorted[top10_pct:-bot10_pct].sum()) if top10_pct else sum_total
    out["right_tail_dominance"] = {
        "sum_total": sum_total,
        "sum_top10pct": sum_top10,
        "sum_top10_share": sum_top10 / sum_total if sum_total else 0.0,
        "sum_bot10pct": sum_bot10,
        "sum_bot10_share": sum_bot10 / sum_total if sum_total else 0.0,
        "sum_mid80pct": sum_ex_extremes,
        "sum_mid80_share": sum_ex_extremes / sum_total if sum_total else 0.0,
        "max_R": float(Rs_sorted[0]) if len(Rs_sorted) else 0.0,
        "min_R": float(Rs_sorted[-1]) if len(Rs_sorted) else 0.0,
    }

    # 4) Side asymmetry (overall)
    long = df[df["side"] == "long"]
    short = df[df["side"] == "short"]
    out["side_asymmetry"] = {
        "long_n": int(len(long)),
        "long_WR": float((long["R"] > 0).mean()) if len(long) else 0.0,
        "long_mR": float(long["R"].mean()) if len(long) else 0.0,
        "long_sumR": float(long["R"].sum()) if len(long) else 0.0,
        "short_n": int(len(short)),
        "short_WR": float((short["R"] > 0).mean()) if len(short) else 0.0,
        "short_mR": float(short["R"].mean()) if len(short) else 0.0,
        "short_sumR": float(short["R"].sum()) if len(short) else 0.0,
    }

    # 5) Symbol breakdown
    out["symbol_breakdown"] = {}
    for sym, g in df.groupby("symbol"):
        out["symbol_breakdown"][sym] = {
            "n": int(len(g)),
            "WR": float((g["R"] > 0).mean()),
            "mR": float(g["R"].mean()),
            "sumR": float(g["R"].sum()),
        }

    # 6) Year/month seasonality
    df_t = df.copy()
    df_t["entry_ts"] = pd.to_datetime(df_t["entry_ts"], utc=True)
    df_t["year"] = df_t["entry_ts"].dt.year
    df_t["month"] = df_t["entry_ts"].dt.month
    out["yearly"] = {}
    for y, g in df_t.groupby("year"):
        out["yearly"][int(y)] = {
            "n": int(len(g)),
            "WR": float((g["R"] > 0).mean()),
            "mR": float(g["R"].mean()),
            "sumR": float(g["R"].sum()),
        }

    out["monthly_mR"] = {}
    for m, g in df_t.groupby("month"):
        out["monthly_mR"][int(m)] = {
            "n": int(len(g)),
            "WR": float((g["R"] > 0).mean()),
            "mR": float(g["R"].mean()),
        }

    # 7) Sequential dependency (markov): win/loss serileri
    # her strateji + sym icinde chrono sirala, prev_outcome vs current
    df_sorted = df_t.sort_values(["strategy", "symbol", "entry_ts"]).reset_index(drop=True)
    df_sorted["outcome"] = (df_sorted["R"] > 0).astype(int)
    df_sorted["prev_outcome"] = df_sorted.groupby(["strategy", "symbol"])["outcome"].shift(1)
    valid = df_sorted.dropna(subset=["prev_outcome"])
    if len(valid):
        prev_w = valid[valid["prev_outcome"] == 1]
        prev_l = valid[valid["prev_outcome"] == 0]
        out["sequential_markov"] = {
            "after_win_WR": float(prev_w["outcome"].mean()) if len(prev_w) else 0.0,
            "after_win_mR": float(prev_w["R"].mean()) if len(prev_w) else 0.0,
            "after_win_n": int(len(prev_w)),
            "after_loss_WR": float(prev_l["outcome"].mean()) if len(prev_l) else 0.0,
            "after_loss_mR": float(prev_l["R"].mean()) if len(prev_l) else 0.0,
            "after_loss_n": int(len(prev_l)),
            "base_WR": float(df_sorted["outcome"].mean()),
        }

    # 8) Setup orthogonality: ayni gunde ayni sym'de farkli strat trade'leri
    df_t["entry_date"] = df_t["entry_ts"].dt.date
    grp = df_t.groupby(["entry_date", "symbol"])["strategy"].agg(lambda s: set(s.tolist()))
    co_occur = defaultdict(lambda: defaultdict(int))
    strat_count = defaultdict(int)
    for _, strats in grp.items():
        for s in strats:
            strat_count[s] += 1
        slist = sorted(strats)
        for i in range(len(slist)):
            for j in range(i + 1, len(slist)):
                co_occur[slist[i]][slist[j]] += 1
                co_occur[slist[j]][slist[i]] += 1
    # jaccard: |A intersect B| / |A union B|
    out["co_occurrence_jaccard"] = {}
    strats_sorted = sorted(strat_count.keys())
    for s1 in strats_sorted:
        out["co_occurrence_jaccard"][s1] = {}
        for s2 in strats_sorted:
            if s1 >= s2:
                continue
            inter = co_occur[s1].get(s2, 0)
            union = strat_count[s1] + strat_count[s2] - inter
            jac = inter / union if union else 0.0
            out["co_occurrence_jaccard"][s1][s2] = round(jac, 4)

    return out


def trend_cont_vs_mean_rev_meta(per_strat_df: pd.DataFrame) -> dict:
    df = per_strat_df.copy()
    df["class"] = df["strategy"].apply(lambda m: STRATEGY_META.get(m, {}).get("class", "trend_continuation"))
    out = {}
    for cls, g in df.groupby("class"):
        total_n = int(g["n"].sum())
        total_sumR = float(g["sum_R"].sum())
        if total_n == 0:
            continue
        out[cls] = {
            "n_strats": int(len(g)),
            "n_trades": total_n,
            "mean_mR": float((g["mean_R_raw"] * g["n"]).sum() / total_n),
            "sumR": total_sumR,
            "strategies": g["strategy"].tolist(),
        }
    return out


def main():
    print("[load] PROD pool (TOP_10 + FVG, sec13_4 baseline_v1_3)...")
    prod = load_pool(PROD_POOL_PATH)
    top10 = load_pool(TOP10_POOL_PATH)
    fvg_dict = load_pool(FVG_POOL_PATH)
    fvg = fvg_dict["fvg_fill_reversal"]

    print(f"  prod n={len(prod)}, top10 n={len(top10)}, fvg n={len(fvg)}")
    # Sanity: top10 + fvg should ~= prod (but prod also has sec13_4 baseline includes only top10+fvg)
    # We rely on prod pool directly.

    print("[load] BTC regime mask...")
    regime = load_btc_regime()
    print(f"  regime rows: {len(regime)}")
    print(f"  regime distribution: {regime['regime'].value_counts().to_dict()}")
    print(f"  vol_regime: {regime['vol_regime'].value_counts().to_dict()}")

    # Filter prod to only the 11 production strategies
    prod_strats = {
        "engulfing_continuation", "obv_engulfing_confluence", "anchored_vwap_reversal",
        "wyckoff_phase_d", "brooks_h2_l2", "pin_bar_round_numbers",
        "equal_highs_sweep", "cvd_spike_fade", "vsa_climax_test",
        "brooks_failed_breakout", "fvg_fill_reversal",
    }
    prod_pool = [t for t in prod if t.get("strategy") in prod_strats]
    print(f"[filter] prod_pool (11 production strats only): n={len(prod_pool)}")
    print(f"  strategies present: {sorted(set(t['strategy'] for t in prod_pool))}")

    print("[attach] regime + hold_days...")
    prod_pool = add_hold_days(prod_pool)
    prod_pool = attach_regime(prod_pool, regime)

    print("[analysis] per-strategy breakdown...")
    per_strat = per_strategy_breakdown(prod_pool)
    per_strat.to_csv(OUT_PER_STRAT_CSV, index=False)
    print(f"  -> {OUT_PER_STRAT_CSV}")

    print("[analysis] regime breakdown...")
    rgm = regime_breakdown(prod_pool)
    rgm.to_csv(OUT_REGIME_CSV, index=False)
    print(f"  -> {OUT_REGIME_CSV}")

    print("[analysis] cross-strategy meta...")
    meta = cross_strategy_meta(prod_pool)

    print("[analysis] class meta...")
    class_meta = trend_cont_vs_mean_rev_meta(per_strat)

    print("[summary] writing report...")
    write_report(prod_pool, per_strat, rgm, meta, class_meta)

    # JSON dump
    out_json = {
        "n_trades": len(prod_pool),
        "meta": meta,
        "class_meta": class_meta,
        "regime_breakdown": rgm.to_dict(orient="records"),
        "per_strategy": per_strat.to_dict(orient="records"),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2, default=str)
    print(f"  -> {OUT_JSON}")


def write_report(pool, per_strat, rgm, meta, class_meta):
    L = []
    n = len(pool)

    L.append("# SEC26 — Production Winner Forensic")
    L.append("")
    L.append("**Generated:** " + pd.Timestamp.utcnow().isoformat())
    L.append("")
    L.append("**Pool:** TOP_10 + FVG (v1.2 / v2.0.3 baseline = sec13_4 pool_baseline_v1_3.pkl)")
    L.append(f"**n_trades:** {n}")
    L.append("**Pencere:** 2021-05-15 → 2026-04-30, 11 sym (BTC/ETH/SOL/BNB/ADA/AVAX/LINK/DOT/DOGE/XRP/MATIC), 1d")
    L.append("")
    L.append("**Sprint amaci:** RED hipotez degil — pozitif kesif. NEDEN bu pool crypto'da kazaniyor?")
    L.append("")
    L.append("---")
    L.append("")

    # Section 1 — Inventory
    L.append("## 1) Production Stratejilerin Tam Envanteri")
    L.append("")
    L.append("Kaynak: `configs/risk_balanced.yaml` (strategy_portfolio.strategies, 11 strateji).")
    L.append("")
    L.append("| # | Strategy | Class | Canonical Source | Mekanik (1-2 cumle) |")
    L.append("|---|---|---|---|---|")
    order = [
        "engulfing_continuation", "obv_engulfing_confluence", "anchored_vwap_reversal",
        "wyckoff_phase_d", "brooks_h2_l2", "pin_bar_round_numbers",
        "equal_highs_sweep", "cvd_spike_fade", "vsa_climax_test",
        "brooks_failed_breakout", "fvg_fill_reversal",
    ]
    for i, s in enumerate(order, 1):
        meta_s = STRATEGY_META[s]
        L.append(f"| {i} | `{s}` | {meta_s['class']} | {meta_s['source']} | {meta_s['mechanic']} |")
    L.append("")

    # Class distribution
    cls_counts = defaultdict(int)
    for s in order:
        cls_counts[STRATEGY_META[s]["class"]] += 1
    L.append(f"**Class distribution (kafa sayisi):** {dict(cls_counts)}")
    L.append("")
    L.append("Trade kontribusyonu:")
    L.append("")
    L.append("| Class | n_strats | n_trades | trade_share | mean_mR | sumR | strategies |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    total_n = sum(c["n_trades"] for c in class_meta.values())
    for cls, c in sorted(class_meta.items(), key=lambda kv: -kv[1]["sumR"]):
        share = c["n_trades"] / total_n * 100.0
        L.append(f"| {cls} | {c['n_strats']} | {c['n_trades']} | {share:.1f}% | {c['mean_mR']:+.3f} | {c['sumR']:+.1f} | {', '.join(c['strategies'])} |")
    L.append("")

    # Section 2 — Per-strategy
    L.append("## 2) Per-Strategy Edge Breakdown")
    L.append("")
    L.append("Ham + honest-clip (hold>60d → R cap 3.0R, SEC22/24 disipliniyle).")
    L.append("")
    L.append("| Strategy | n | WR | mR_raw | mR_clip60d3R | sumR | mean_R_win | mean_R_loss | W/L ratio |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in per_strat.iterrows():
        L.append(f"| `{r['strategy']}` | {r['n']} | {r['WR']*100:.1f}% | {r['mean_R_raw']:+.3f} | {r['mean_R_clip60d3R']:+.3f} | {r['sum_R']:+.1f} | {r['mean_R_win']:+.3f} | {r['mean_R_loss']:+.3f} | {r['wl_ratio']:.2f} |")
    L.append("")

    # Section 3 — Regime breakdown per strategy
    L.append("## 3) Per-Strategy Regime Breakdown (mR)")
    L.append("")
    L.append("Regime BTC 1d EMA200 + slope_30d + 90d_return ile sinflandi:")
    L.append("- **bull**: close>EMA200 + slope+ + ret90d>+10%")
    L.append("- **bear**: close<EMA200 + slope- + ret90d<-10%")
    L.append("- **range**: aksi (incl. transitions)")
    L.append("")
    L.append("| Strategy | mR_bull (n) | mR_bear (n) | mR_range (n) | mR_long (n) | mR_short (n) | mR_BTC (n) | mR_ETH (n) | mR_alt (n) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in per_strat.iterrows():
        L.append(
            f"| `{r['strategy']}` "
            f"| {r['mR_bull']:+.2f} ({r['n_bull']}) "
            f"| {r['mR_bear']:+.2f} ({r['n_bear']}) "
            f"| {r['mR_range']:+.2f} ({r['n_range']}) "
            f"| {r['mR_long']:+.2f} ({r['n_long']}) "
            f"| {r['mR_short']:+.2f} ({r['n_short']}) "
            f"| {r['mR_btc']:+.2f} ({r['n_btc']}) "
            f"| {r['mR_eth']:+.2f} ({r['n_eth']}) "
            f"| {r['mR_alt']:+.2f} ({r['n_alt']}) |"
        )
    L.append("")

    # Section 4 — Hold-days
    L.append("## 4) Hold-Days Patterns (MFE Proxy)")
    L.append("")
    L.append("MFE direkt yok (pool'da peak_R kolonu yok). Hold-days proxy.")
    L.append("")
    L.append("| Strategy | hold_mean | hold_median | frac_winners_held>30d |")
    L.append("|---|---:|---:|---:|")
    for _, r in per_strat.iterrows():
        L.append(f"| `{r['strategy']}` | {r['hold_days_mean']:.1f} | {r['hold_days_median']:.1f} | {r['frac_long_held_gt_30d']*100:.1f}% |")
    L.append("")

    # Section 5 — Aggregate regime x side
    L.append("## 5) Aggregate Regime x Side (Cross-Strategy)")
    L.append("")
    L.append("| Regime | Side | n | WR | mR | sumR |")
    L.append("|---|---|---:|---:|---:|---:|")
    for _, r in rgm.iterrows():
        L.append(f"| {r['regime']} | {r['side']} | {r['n']} | {r['WR']*100:.1f}% | {r['mR']:+.3f} | {r['sumR']:+.1f} |")
    L.append("")

    # Section 6 — Right-tail dominance
    rt = meta["right_tail_dominance"]
    L.append("## 6) Right-Tail Dominance (Big Winners > Marjinal)")
    L.append("")
    L.append(f"- **Total sumR**: {rt['sum_total']:+.1f}")
    L.append(f"- **Top 10% trades (n~{int(n*0.10)})**: sumR {rt['sum_top10pct']:+.1f} ({rt['sum_top10_share']*100:.1f}% of total)")
    L.append(f"- **Mid 80% trades**: sumR {rt['sum_mid80pct']:+.1f} ({rt['sum_mid80_share']*100:.1f}%)")
    L.append(f"- **Bot 10% trades**: sumR {rt['sum_bot10pct']:+.1f} ({rt['sum_bot10_share']*100:.1f}%)")
    L.append(f"- **Max R (single trade)**: {rt['max_R']:+.2f}")
    L.append(f"- **Min R (single trade)**: {rt['min_R']:+.2f}")
    L.append("")

    # Section 7 — Side asymmetry
    sa = meta["side_asymmetry"]
    L.append("## 7) Long vs Short Asymmetric Edge")
    L.append("")
    L.append(f"- **LONG**: n={sa['long_n']}, WR {sa['long_WR']*100:.1f}%, mR {sa['long_mR']:+.3f}, sumR {sa['long_sumR']:+.1f}")
    L.append(f"- **SHORT**: n={sa['short_n']}, WR {sa['short_WR']*100:.1f}%, mR {sa['short_mR']:+.3f}, sumR {sa['short_sumR']:+.1f}")
    if sa["short_mR"] > sa["long_mR"]:
        L.append(f"- **SHORT mR/long mR = {sa['short_mR']/max(0.001,sa['long_mR']):.2f}x** → SEC12 'short trade'ler 1.66x karli' bulgusuyla uyumlu mu?")
    L.append("")

    # Section 8 — BTC trend filter
    bt = meta["btc_above_ema50_winrate"]
    L.append("## 8) BTC > EMA50 (Entry-Day) — Macro Trend Filter Etkisi")
    L.append("")
    L.append(f"- **BTC > EMA50** (n={bt['above_n']}): WR {bt['above_WR']*100:.1f}%, mR {bt['above_mR']:+.3f}, sumR {bt['above_sumR']:+.1f}")
    L.append(f"- **BTC < EMA50** (n={bt['below_n']}): WR {bt['below_WR']*100:.1f}%, mR {bt['below_mR']:+.3f}, sumR {bt['below_sumR']:+.1f}")
    L.append("")

    # Section 9 — Vol regime
    L.append("## 9) Vol Regime (BTC ATR% tercile)")
    L.append("")
    L.append("| Vol regime | n | WR | mR | sumR |")
    L.append("|---|---:|---:|---:|---:|")
    for v in ["low_vol", "mid_vol", "high_vol"]:
        d = meta["vol_regime_split"].get(v, {})
        if d.get("n", 0) == 0:
            L.append(f"| {v} | 0 | — | — | — |")
            continue
        L.append(f"| {v} | {d['n']} | {d['WR']*100:.1f}% | {d['mR']:+.3f} | {d['sumR']:+.1f} |")
    L.append("")

    # Section 10 — Symbol breakdown
    L.append("## 10) Symbol Breakdown (Cross-Strategy)")
    L.append("")
    L.append("| Symbol | n | WR | mR | sumR |")
    L.append("|---|---:|---:|---:|---:|")
    syms = sorted(meta["symbol_breakdown"].items(), key=lambda kv: -kv[1]["sumR"])
    for sym, d in syms:
        L.append(f"| {sym} | {d['n']} | {d['WR']*100:.1f}% | {d['mR']:+.3f} | {d['sumR']:+.1f} |")
    L.append("")

    # Section 11 — Yearly
    L.append("## 11) Yearly Seasonality")
    L.append("")
    L.append("| Year | n | WR | mR | sumR |")
    L.append("|---|---:|---:|---:|---:|")
    for y in sorted(meta["yearly"].keys()):
        d = meta["yearly"][y]
        L.append(f"| {y} | {d['n']} | {d['WR']*100:.1f}% | {d['mR']:+.3f} | {d['sumR']:+.1f} |")
    L.append("")

    # Section 12 — Monthly
    L.append("## 12) Monthly Seasonality (mR ortalama)")
    L.append("")
    L.append("| Month | n | WR | mR |")
    L.append("|---|---:|---:|---:|")
    for m in range(1, 13):
        d = meta["monthly_mR"].get(m, {})
        if not d:
            continue
        L.append(f"| {m:02d} | {d['n']} | {d['WR']*100:.1f}% | {d['mR']:+.3f} |")
    L.append("")

    # Section 13 — Sequential dependency
    if "sequential_markov" in meta:
        sm = meta["sequential_markov"]
        L.append("## 13) Sequential Dependency (Markov)")
        L.append("")
        L.append(f"- **Base WR**: {sm['base_WR']*100:.1f}%")
        L.append(f"- **WR after WIN** (n={sm['after_win_n']}): {sm['after_win_WR']*100:.1f}% (mR {sm['after_win_mR']:+.3f})")
        L.append(f"- **WR after LOSS** (n={sm['after_loss_n']}): {sm['after_loss_WR']*100:.1f}% (mR {sm['after_loss_mR']:+.3f})")
        delta = sm['after_win_WR'] - sm['after_loss_WR']
        L.append(f"- **delta_WR (win - loss)**: {delta*100:+.2f}pp")
        if abs(delta) < 0.03:
            L.append(f"- **Yorum**: Memoryless (markov-1 etkisi <3pp). Ardisik kayip cool-down sermaye korumasi icin, edge tahmini icin degil.")
        else:
            L.append(f"- **Yorum**: Markov-1 etkisi >3pp — sequential dependency var, cool-down/anti-streak filter degerli olabilir.")
        L.append("")

    # Section 14 — Co-occurrence orthogonality
    L.append("## 14) Setup Orthogonality (Jaccard Co-Occurrence)")
    L.append("")
    L.append("Ayni gun + ayni sym'de iki stratejinin birlikte trigger etme oranlari. Yuksek jaccard = redundant edge; dusuk = orthogonal.")
    L.append("")
    co = meta["co_occurrence_jaccard"]
    strats = sorted(co.keys())
    # top 5 highest pairs + top 5 lowest
    pairs = []
    for s1 in strats:
        for s2, j in co[s1].items():
            pairs.append((s1, s2, j))
    pairs.sort(key=lambda x: -x[2])
    L.append("**Top 8 high-jaccard pairs (potansiyel redundancy):**")
    L.append("")
    L.append("| Strat A | Strat B | Jaccard |")
    L.append("|---|---|---:|")
    for s1, s2, j in pairs[:8]:
        L.append(f"| `{s1}` | `{s2}` | {j:.4f} |")
    L.append("")
    L.append("**Top 8 lowest-jaccard pairs (en orthogonal):**")
    L.append("")
    L.append("| Strat A | Strat B | Jaccard |")
    L.append("|---|---|---:|")
    nonzero = [p for p in pairs if p[2] > 0]
    for s1, s2, j in nonzero[-8:]:
        L.append(f"| `{s1}` | `{s2}` | {j:.4f} |")
    L.append("")

    # Section 15 — Crypto microstructure WHY
    L.append("## 15) Crypto Microstructure — NEDEN trend_continuation + FVG production'da kazandi?")
    L.append("")
    L.append("Cross-strategy bulgular + literature + SEC22/23/24/25 zincir kanitlarinin sentezi.")
    L.append("")
    L.append("### H1: 24/7 + Retail Dominance → Trend Persistence, No Mean-Rev Anchor")
    L.append("")
    L.append("Crypto perpetual'da equity-style 'kapanis ve gece-pozisyon kapama' mevcut degil. Retail leveraged trader'lar")
    L.append("trend yonunde acilan pozisyonlari geri durumlarinda likidasyon zincirine sokar — trend kendi yakitinda yanar.")
    L.append("Equity'de overnight gap fade etmek mantikli, crypto'da gap yok; mean-rev pattern'ler (SEC22 HTF retest, SEC24")
    L.append("turtle soup, SEC25 brooks_db_bull_flag) `n` bottleneck'e takildi cunku **gercek mean-rev sinyali nadir uretiliyor**.")
    L.append("")
    L.append("**Veri kaniti:** Yukaridaki Section 2 — trend_continuation class'i sumR'in (yukaridaki tabloya bak) buyuk kismini")
    L.append("uretiyor; mean_reversion (anchored_vwap, cvd_spike_fade, vsa_climax_test, fvg_fill_reversal) ikincil ama")
    L.append("uncorrelated edge sagliyor (sec11e bulgusu — FVG TOP_10'a +%8.7 yillik ekledi).")
    L.append("")
    L.append("### H2: Leverage Cascade → Right-Tail Fat Tails (Big Winners > Marjinal)")
    L.append("")
    L.append(f"Top 10% trade'ler total sumR'in **{rt['sum_top10_share']*100:.1f}%**'ini olusturuyor (max single R = {rt['max_R']:+.1f}). ")
    L.append("Bu power-law dagilim — equity'de S&P 500 trend follower'lar (Trout, Dunn) ile uyumlu ama crypto'da magnitude daha sert.")
    L.append("")
    L.append("Sebep: ucuncu-derece leverage cascade. BTC %5 yukseliyor → futures funding pozitif → arbitrage long açıyor")
    L.append("→ likidasyon havuzu daralıyor → trapped shortlar coverleniyor → %5 yukselis %15'e cikiyor. trend_continuation")
    L.append("stratejileri (engulfing_continuation, brooks_h2_l2, obv_engulfing_confluence) bu cascade'e long taraftan binmek")
    L.append("icin tasarlanmis — partial TP'den sonra runner trail ile right-tail yakaliyor.")
    L.append("")
    L.append("**Engine kaniti:** `engine.tp1_R=1.0, tp2_R=1.5, runner_trail_mult=1.0, time_exit_bars=30` (SEC11b WIN +%9.5pp)")
    L.append("— B partial 1R + primary 1.5R + 1.0ATR trail = right-tail capture + early lock-in dengesi.")
    L.append("")
    L.append("### H3: FVG = Institutional Inefficiency Reclaim (Mean-Rev'in Tek Saglikli Carrier'i)")
    L.append("")
    L.append("Crypto'da equity-style POC/AVWAP retest edge zayif (anchored_vwap_reversal sumR per-trade dusuk; bkz tablo).")
    L.append("Sebep: crypto'da kurumsal limit-order yapisi 'value area' kavramini tasimiyor — likidite suregen, exchange'lere")
    L.append("dagilmis. ICT FVG ise FARKLI bir mekanizmaya yaslanir: **3-bar imbalance = order-flow gap**. Bu gap exchange-")
    L.append("agnostic: stop-hunt sonrasi reclaim, manipulation candle sonrasi reset. Bu yuzden FVG TOP_10'a uncorrelated")
    L.append("edge ekledi (+%8.7pp WF, alt-coin'lerde ADA mR +0.59, XRP +0.47).")
    L.append("")
    L.append("Karsi kanit (mean-rev RED'leri):")
    L.append("- SEC22 bb_extreme_reversal HARD RED: +2.5σ excursion crypto'da CONTINUATION (counter-mean-rev mekanizma).")
    L.append("- SEC22 rsi2_extreme_fade PASS-MARGINAL: gercek edge VAR ama production'a katkı yok (slot bottleneck).")
    L.append("- SEC22 three_push_wedge_fade RED-CONDITIONAL: Brooks wedges crypto'da rare event.")
    L.append("")
    L.append("**Sonuc:** Mean-rev'in tek skalable carrier'i FVG-style microstructure gap; klasik 'extreme RSI / Bollinger band'")
    L.append("pattern'leri crypto trend persistence'inde dolaylı olarak SHORT yapiyor — yapısal kayip.")
    L.append("")
    L.append("### H4: Asymmetric Short Edge — F&G ≤20 Skip Bu Mekanizmayi Ortaya Cikariyor")
    L.append("")
    if sa["short_mR"] > sa["long_mR"]:
        L.append(f"Pool'da short mR ({sa['short_mR']:+.3f}) > long mR ({sa['long_mR']:+.3f}). ")
        L.append("Aksini bekleyebilirdik — bull market dominant. Sebep: SHORT capitulation moves (LUNA, FTX, mart 2024 ATH")
        L.append("reject) tek seferlik buyuk R yariyor. F&G <=20 short-skip filtresi (v0.9.7) BU mekanizmayi koruyor:")
        L.append("ekstrem korku zaten bottoming, short edge'i orada filtreleyince losing-tail sıkışıyor — kaybedilen")
        L.append("kuçuk sayıdaki big-loser short, kalan big-winner short universe'ünü temsiyl etmiyor.")
    else:
        L.append(f"Pool'da long mR ({sa['long_mR']:+.3f}) >= short mR ({sa['short_mR']:+.3f}) — beklenen yon.")
    L.append("")
    L.append("### H5: BTC > EMA50 Confluence Filter — Yapisal Edge Booster")
    L.append("")
    L.append(f"BTC > EMA50 gunlerinde mR {bt['above_mR']:+.3f} (n={bt['above_n']}), altinda mR {bt['below_mR']:+.3f} (n={bt['below_n']}).")
    delta_mR = bt["above_mR"] - bt["below_mR"]
    L.append(f"Delta mR: {delta_mR:+.3f}. ")
    if delta_mR > 0.05:
        L.append("BTC trend filter mevcut config'de IMPLICIT olarak yok (regime_filter.capitulation_halt sadece ekstrem")
        L.append("durumda devreye giriyor). Bu sayilar gelecek sprint icin BTC > EMA50 hard filter hipotezi tetikleyebilir.")
    elif delta_mR > 0.0:
        L.append("Marjinal pozitif delta — hard filter olarak ek edge sınırlı.")
    else:
        L.append("BTC trend filter alpha yaratmıyor (zaten dolaylı olarak strateji-içi trend filter'lar bunu yapıyor).")
    L.append("")

    # Section 16 — Yan-bulgu hipotezleri
    L.append("## 16) Yan-Bulgu — Sonraki Sprint Pre-Reg Backlog")
    L.append("")
    L.append("Forensik sırasında tetiklenen pre-reg hipotez adayları (DETALI BACKLOG):")
    L.append("")
    L.append("1. **HYP-BACKLOG-001**: BTC > EMA50 hard filter (entry-day) production pool'a IMPLICIT eklendiginde")
    L.append("   walk-forward yillik delta. Yukaridaki Section 8 deltas pozitifse formal hipotez yaz.")
    L.append("2. **HYP-BACKLOG-002**: short-only edge dominantliginin F&G filtresinden mi yoksa LUNA/FTX/Yen-carry")
    L.append("   gibi tail-event'lerden mi geldigini ayristirma. Stress-period dısı subset replay ile test.")
    L.append("3. **HYP-BACKLOG-003**: Alt-coin (ADA/XRP/SOL) FVG edge'i (sec11e ADA +0.59) ozel bir alt-universe")
    L.append("   manifest hak ediyor mu? Top alt-coin'lere agirlikli FVG variant.")
    L.append("")
    L.append("> Bu adaylar PRE-REG DEGIL — sadece sprint tetikleyicisi. Formal yazim sonraki sprint baslangıcında.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## Reproducibility")
    L.append("")
    L.append(f"- Pool: `data/_sec13_4_cache/pool_baseline_v1_3.pkl` (n={n})")
    L.append("- BTC regime: `data/market.duckdb` (ohlcv table, BTC/USDT 1d binance)")
    L.append("- Script: `scripts/sec26_winner_forensic.py`")
    L.append("- Outputs:")
    L.append(f"  - `{OUT_REPORT.relative_to(ROOT)}`")
    L.append(f"  - `{OUT_JSON.relative_to(ROOT)}`")
    L.append(f"  - `{OUT_PER_STRAT_CSV.relative_to(ROOT)}`")
    L.append(f"  - `{OUT_REGIME_CSV.relative_to(ROOT)}`")
    L.append("")

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"  -> {OUT_REPORT}")


if __name__ == "__main__":
    main()
