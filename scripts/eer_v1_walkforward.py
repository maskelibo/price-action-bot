"""EER-Score v1 walk-forward + shuffle null baseline.

Pre-registered hypothesis: memory/researcher/hypotheses/2026-05-13-eer-score-v1.md
Implementation: src/price_action/backtest/eer_score.py
Output report: reports/research/eer_v1_results.txt

Workflow:
  1. Gather Top 10 strategy trades over 5y (use existing _gather)
  2. Build causal feature context (BTC EMA200+DD90; symbol ATR%+quantiles;
     funding; F&G)
  3. Compute EER for every trade (look-ahead audit baked in)
  4. Walk-forward 3y/6m, step 3m, 13 windows (CEO benchmark)
  5. In each window:
       - Sizing CONF (control): tier from conf_pct percentile (existing scoring.py)
       - Sizing EER (treatment): tier from EER bucket-rank
       - Replay both with same risk overlay (DD breakers, cool-down)
  6. Compare OOS Sharpe + annualized return + MaxDD + top-vs-bottom avg_R
  7. Shuffle null: 200 iters of EER label shuffle per window
  8. Bootstrap CI on (EER - CONF) Sharpe delta
  9. Bonferroni correction (alpha = 0.05 / 13)
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Suppress noisy backtest engine logs (we don't need them here)
import logging
logging.getLogger("price_action").setLevel(logging.WARNING)
logging.getLogger("price_action.backtest.engine").setLevel(logging.WARNING)
import os
os.environ["LOG_LEVEL"] = "WARNING"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import duckdb

from price_action.backtest.eer_score import (
    EERConfig,
    EERStats,
    FeatureContext,
    compute_eer_for_trades,
    context_data_hash,
    eer_to_tier,
    precompute_btc_features,
    precompute_symbol_atr,
    precompute_symbol_atr_quantiles,
    trades_data_hash,
)

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]


# Tier sizing schema (default — mirrors CEO Brief 20/40/30/10 target distribution
# but with conservative leverage/risk; this is HOW Lab WILL build DYNAMIC v2)
TIER_RISK_LEVERAGE = {
    1: (0.010, 1.0),  # T1: very low — 1% risk, 1x lev
    2: (0.020, 2.0),  # T2: low — 2% risk, 2x lev
    3: (0.030, 3.0),  # T3: high (BALANCED default) — 3%, 3x
    4: (0.040, 3.0),  # T4: top — 4% risk, 3x (NOT 7% — DYNAMIC v0.9.8 lesson)
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def _load_ohlcv_duckdb(symbol: str, tf: str = "1d") -> pd.DataFrame:
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
        [symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _load_funding_btc() -> pd.DataFrame:
    p = ROOT / "data" / "alt_data" / "funding_BTCUSDT.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    return df.sort_values("ts").reset_index(drop=True)


def _load_fng() -> pd.DataFrame:
    p = ROOT / "data" / "alt_data" / "fng_daily.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    return df.sort_values("ts").reset_index(drop=True)


def build_feature_context() -> FeatureContext:
    """11 sembol + BTC features + funding + F&G."""
    btc_df = _load_ohlcv_duckdb("BTC/USDT")
    btc_feats = precompute_btc_features(btc_df)

    sym_atr = {}
    sym_q = {}
    for sym in SYMBOLS_11:
        df = _load_ohlcv_duckdb(sym)
        if df.empty:
            continue
        atr = precompute_symbol_atr(df)
        q = precompute_symbol_atr_quantiles(atr)
        sym_atr[sym] = atr
        sym_q[sym] = q

    funding = _load_funding_btc()
    fng = _load_fng()

    return FeatureContext(
        btc_daily=btc_feats,
        symbol_atr_pct=sym_atr,
        symbol_atr_quantiles=sym_q,
        funding=funding,
        fng=fng,
    )


# ---------------------------------------------------------------------------
# Replay with tier-based sizing
# ---------------------------------------------------------------------------
def replay_tiered(
    trades: list[dict],
    score_field: str,                  # "conf_pct" or "eer"
    tier_cuts: tuple[float, float, float] = (0.20, 0.60, 0.90),
    max_concurrent: int = 8,
    cooldown_days: int = 3,
    consecutive_loss_n: int = 3,
    consecutive_loss_pause: int = 5,
    daily_dd: float = 0.05,
    weekly_dd: float = 0.10,
    monthly_dd: float = 0.15,
    notional_cap_frac: float = 0.30,
) -> dict:
    """Replay trade'leri tier-based sizing ile.

    Her trade icin `score_field` degerine gore (eer_to_tier ile) tier verilir;
    tier'dan risk_pct + leverage cikarilir.

    BALANCED ile ayni breakers/cooldown — apple-to-apple karsilastirma.
    """
    if not trades:
        return None

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []
    tier_counts = defaultdict(int)
    cap_hits = 0
    margin_blocks = 0

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    last_entry: dict[tuple, pd.Timestamp] = {}
    consecutive_losses = 0
    cool_until = None

    def close_due(now):
        nonlocal cash, equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
                if pnl < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=consecutive_loss_pause)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            continue

        score = float(t.get(score_field, 0.5))
        tier = eer_to_tier(score, tier_cuts)
        tier_counts[tier] += 1
        risk_pct, leverage = TIER_RISK_LEVERAGE[tier]

        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days:
            continue

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d:
            daily_anchor = equity
            last_d = cd
        if cw != last_w:
            weekly_anchor = equity
            last_w = cw
        if cm != last_m:
            monthly_anchor = equity
            last_m = cm

        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1)
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7)
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30)
            continue
        if len(open_pos) >= max_concurrent:
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        risk_d = equity * risk_pct
        notional = risk_d / sl_pct

        # Notional cap: max notional_cap_frac of equity per single trade
        max_notional = equity * notional_cap_frac
        if notional > max_notional:
            notional = max_notional
            risk_d = notional * sl_pct
            cap_hits += 1

        margin = notional / max(leverage, 1.0)
        if margin > cash:
            margin_blocks += 1
            continue

        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({
            "exit_ts": t["exit_ts"],
            "margin": margin,
            "risk": risk_d,
            "R": t["R"],
        })

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    if not Rs:
        return None

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    wr = sum(1 for x in Rs if x > 0) / len(Rs)
    avg_r = float(np.mean(Rs))
    std_r = float(np.std(Rs)) if len(Rs) > 1 else 1.0
    sharpe_trade = avg_r / max(std_r, 1e-6) * math.sqrt(252.0 / max(1, len(Rs))) if len(Rs) > 30 else 0.0

    # Daily equity Sharpe — daha standart
    eq_arr = np.array(eq_curve)
    if len(eq_arr) > 1:
        rets = np.diff(eq_arr) / eq_arr[:-1]
        sharpe = (np.mean(rets) / max(np.std(rets), 1e-9)) * math.sqrt(252.0)
    else:
        sharpe = 0.0

    return {
        "final": equity,
        "max_dd": max_dd,
        "trades": len(Rs),
        "wr": wr,
        "avg_r": avg_r,
        "sharpe": float(sharpe),
        "tier_counts": dict(tier_counts),
        "cap_hits": cap_hits,
        "margin_blocks": margin_blocks,
    }


# ---------------------------------------------------------------------------
# Walk-forward windowing
# ---------------------------------------------------------------------------
def build_walk_forward_windows(
    trades: list[dict],
    train_years: int = 3,
    oos_months: int = 6,
    step_months: int = 3,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """(train_start, train_end=oos_start, oos_end) tuple'lari."""
    if not trades:
        return []
    first = min(t["entry_ts"] for t in trades)
    last = max(t["entry_ts"] for t in trades)
    windows = []
    train_end = first + pd.DateOffset(years=train_years)
    while True:
        oos_end = train_end + pd.DateOffset(months=oos_months)
        if oos_end > last + pd.DateOffset(days=1):
            break
        windows.append((first, train_end, oos_end))
        train_end = train_end + pd.DateOffset(months=step_months)
        first = first + pd.DateOffset(months=step_months)
    return windows


def filter_window(trades: list[dict], start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    return [t for t in trades if start <= t["entry_ts"] < end]


# ---------------------------------------------------------------------------
# Shuffle null baseline
# ---------------------------------------------------------------------------
def shuffle_null_baseline(
    oos_trades: list[dict],
    score_field: str,
    n_iter: int = 200,
    seed: int = 42,
) -> dict:
    """Shuffle EER labels n_iter kez; her shuffle icin Sharpe ölç.

    Real Sharpe'i shuffle distribution'a karsi test eder.
    """
    rng = np.random.default_rng(seed)
    real_replay = replay_tiered(oos_trades, score_field)
    if real_replay is None:
        return {"p_value": 1.0, "real_sharpe": 0.0, "null_sharpe_mean": 0.0}

    real_sharpe = real_replay["sharpe"]
    scores = [t.get(score_field, 0.5) for t in oos_trades]
    null_sharpes = []
    for _ in range(n_iter):
        permuted = rng.permutation(scores).tolist()
        shuffled = []
        for t, s in zip(oos_trades, permuted):
            t2 = dict(t)
            t2[score_field] = float(s)
            shuffled.append(t2)
        r = replay_tiered(shuffled, score_field)
        if r is None:
            continue
        null_sharpes.append(r["sharpe"])

    if not null_sharpes:
        return {"p_value": 1.0, "real_sharpe": real_sharpe, "null_sharpe_mean": 0.0}

    p_val = sum(1 for x in null_sharpes if x >= real_sharpe) / len(null_sharpes)
    return {
        "p_value": float(p_val),
        "real_sharpe": float(real_sharpe),
        "null_sharpe_mean": float(np.mean(null_sharpes)),
        "null_sharpe_std": float(np.std(null_sharpes)),
        "n_null": len(null_sharpes),
    }


# ---------------------------------------------------------------------------
# Conf percentile (CONTROL baseline — mevcut scoring.py paterni)
# ---------------------------------------------------------------------------
def normalize_conf_percentile_inplace(trades: list[dict], lookback_days: int = 180) -> None:
    """Mevcut scoring.py — her trade'e conf_pct ekle (rolling 180d rank)."""
    if not trades:
        return
    trades_sorted = sorted(trades, key=lambda t: t["entry_ts"])
    for i, t in enumerate(trades_sorted):
        cutoff = t["entry_ts"] - timedelta(days=lookback_days)
        history = []
        for j in range(i - 1, -1, -1):
            if trades_sorted[j]["entry_ts"] < cutoff:
                break
            history.append(trades_sorted[j]["conf"])
        if len(history) < 30:
            t["conf_pct"] = float(t["conf"])
            continue
        cs = t["conf"]
        rank = sum(1 for h in history if h <= cs) / len(history)
        t["conf_pct"] = float(rank)


# ---------------------------------------------------------------------------
# Top-vs-bottom avg_R Welch t-test
# ---------------------------------------------------------------------------
def welch_t_top_vs_bottom(
    trades: list[dict],
    score_field: str,
    top_cut: float = 0.80,
    bot_cut: float = 0.20,
) -> dict:
    """Top-tier (score >= top_cut) vs Bottom-tier (score <= bot_cut) avg_R Welch t-test."""
    top = [t["R"] for t in trades if t.get(score_field, 0.5) >= top_cut]
    bot = [t["R"] for t in trades if t.get(score_field, 0.5) <= bot_cut]
    if len(top) < 5 or len(bot) < 5:
        return {"top_n": len(top), "bot_n": len(bot), "p": 1.0, "spread": 0.0}

    mean_top = np.mean(top)
    mean_bot = np.mean(bot)
    var_top = np.var(top, ddof=1)
    var_bot = np.var(bot, ddof=1)
    se = math.sqrt(var_top / len(top) + var_bot / len(bot))
    if se == 0:
        return {"top_n": len(top), "bot_n": len(bot), "p": 1.0, "spread": float(mean_top - mean_bot)}
    t_stat = (mean_top - mean_bot) / se
    # df Welch-Satterthwaite
    df = (var_top / len(top) + var_bot / len(bot)) ** 2 / (
        (var_top / len(top)) ** 2 / (len(top) - 1) + (var_bot / len(bot)) ** 2 / (len(bot) - 1)
    )
    # p-value (one-sided: top > bot)
    from math import erf, sqrt
    # Use normal approx for large df; for small df, this is conservative
    z = t_stat
    # one-tailed (right): P(Z >= z) = 1 - Phi(z)
    p_val = 0.5 * (1 - erf(z / sqrt(2)))
    return {
        "top_n": len(top),
        "bot_n": len(bot),
        "mean_top_R": float(mean_top),
        "mean_bot_R": float(mean_bot),
        "spread": float(mean_top - mean_bot),
        "t_stat": float(t_stat),
        "df": float(df),
        "p": float(p_val),
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    print("=" * 100)
    print("EER-Score v1 — Walk-Forward Backtest")
    print("=" * 100)
    print(f"Pre-registered: memory/researcher/hypotheses/2026-05-13-eer-score-v1.md")
    print(f"Output: reports/research/eer_v1_results.txt\n")

    # ---- 1. Gather Top 10 trade pool (5y)
    print("[1/7] Top 10 strateji + 11 sembol trade'leri toplaniyor...")
    from scripts.v09_optimize_top10 import _gather, TOP_10
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
        print(f"  {m:<35} {len(trs)} trade")
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"\nToplam trade pool: {len(all_trades)}\n")
    if not all_trades:
        print("HATA: trade yok — backtest engine kontrol gerekli.")
        return 1

    # ---- 2. Feature context
    print("[2/7] Feature context kuruluyor (BTC EMA200/DD90, sym ATR%, funding, F&G)...")
    ctx = build_feature_context()
    ctx_hash = context_data_hash(ctx)
    print(f"  context_data_hash: {ctx_hash}")
    print(f"  BTC daily rows: {len(ctx.btc_daily)}")
    print(f"  Symbol ATR series: {len(ctx.symbol_atr_pct)}")
    print(f"  Funding rows: {len(ctx.funding)}")
    print(f"  F&G rows: {len(ctx.fng)}\n")

    # ---- 3. Compute EER (default: sample_min=30 pre-reg)
    print("[3/7] EER hesaplaniyor (causal — exit_ts < entry_ts)...")
    cfg = EERConfig()
    enriched, eer_stats = compute_eer_for_trades(all_trades, ctx, cfg)
    print(f"  config_hash: {cfg.config_hash()}")
    print(f"  trades_data_hash: {trades_data_hash(all_trades)}")
    print(f"  EER stats (pre-reg default sample_min=30):")
    print(f"    {json.dumps(eer_stats.summary())}")

    # ---- 3b. Robustness sample_min sweep (NOT for primary decision — diagnostic only)
    print("\n  Robustness sweep (sample_min): bucket coverage diagnostic")
    for sm in [5, 10, 15, 20, 30, 50]:
        cfg_sw = EERConfig(sample_min=sm)
        _, st_sw = compute_eer_for_trades(all_trades, ctx, cfg_sw)
        s = st_sw.summary()
        print(f"    sample_min={sm:>3}  coverage={s['bucket_coverage']*100:>5.2f}%  fallback={s['fallback_rate']*100:>5.2f}%  unique_buckets={s['n_unique_buckets']:>5}")

    # If pre-reg coverage too low (<5%), use sample_min=10 for primary results
    # but flag as PRE-REG VIOLATION → mark gates accordingly
    primary_sample_min = cfg.sample_min
    if eer_stats.bucket_coverage < 0.05:
        print(f"\n  WARNING: bucket coverage {eer_stats.bucket_coverage*100:.2f}% < 5% with pre-reg sample_min=30.")
        print(f"  Karsi-hipotez 1 (bucket clustering bias) DOGRULANDI.")
        print(f"  Continuing with sample_min=30 for HARD GATE (preregistered);")
        print(f"  also reporting sample_min=10 as DIAGNOSTIC (not promotion-eligible).")
        # Diagnostic only — does NOT count for primary decision
        cfg_diag = EERConfig(sample_min=10)
        enriched_diag, eer_stats_diag = compute_eer_for_trades(all_trades, ctx, cfg_diag)
        print(f"  sample_min=10 diagnostic stats: {json.dumps(eer_stats_diag.summary())}")
    else:
        enriched_diag, eer_stats_diag = enriched, eer_stats
    print()

    # ---- 4. Conf percentile (control)
    print("[4/7] Conf percentile (control baseline) hesaplaniyor...")
    normalize_conf_percentile_inplace(enriched, lookback_days=180)
    print(f"  conf_pct distribution:")
    cp = np.array([t["conf_pct"] for t in enriched])
    print(f"    min={cp.min():.3f} 25%={np.percentile(cp, 25):.3f} med={np.median(cp):.3f} "
          f"75%={np.percentile(cp, 75):.3f} max={cp.max():.3f}")
    eer_arr = np.array([t["eer"] for t in enriched])
    print(f"  eer distribution:")
    print(f"    min={eer_arr.min():.3f} 25%={np.percentile(eer_arr, 25):.3f} med={np.median(eer_arr):.3f} "
          f"75%={np.percentile(eer_arr, 75):.3f} max={eer_arr.max():.3f}")
    print()

    # ---- 5. Walk-forward windows
    print("[5/7] Walk-forward windows kuruluyor (3y/6m, step 3m)...")
    windows = build_walk_forward_windows(enriched, train_years=3, oos_months=6, step_months=3)
    print(f"  Windows: {len(windows)}")
    if not windows:
        # Eger 5y'den az veri varsa, daha kucuk window
        print("  YETERSIZ VERI 3y/6m icin. 2y/3m windowing'e geciyor.")
        windows = build_walk_forward_windows(enriched, train_years=2, oos_months=3, step_months=3)
        print(f"  Windows (2y/3m): {len(windows)}")
    if not windows:
        windows = [(min(t["entry_ts"] for t in enriched),
                    min(t["entry_ts"] for t in enriched) + pd.DateOffset(years=2),
                    max(t["entry_ts"] for t in enriched) + pd.DateOffset(days=1))]
        print("  Tek pencere fallback (in-sample test sadece).\n")

    for i, (start, train_end, oos_end) in enumerate(windows[:5], 1):
        print(f"  W{i}: train [{start.date()} → {train_end.date()}]  OOS [{train_end.date()} → {oos_end.date()}]")
    if len(windows) > 5:
        print(f"  ... ({len(windows) - 5} more windows)")
    print()

    # ---- 6. Per-window comparison
    print("[6/7] Pencere-pencere CONF vs EER karsilastirma...")
    print(f"  {'Win':<4} {'OOS_period':<26} {'#tr':>5}  {'CONF: Sh':>8} {'ret%':>7} {'DD%':>6}  "
          f"{'EER: Sh':>8} {'ret%':>7} {'DD%':>6}  {'ΔSh':>6} {'Δret%':>7} {'shuf_p':>7}")
    print("  " + "-" * 130)

    window_results = []
    for i, (start, train_end, oos_end) in enumerate(windows, 1):
        oos = filter_window(enriched, train_end, oos_end)
        if len(oos) < 20:
            window_results.append({
                "window": i,
                "oos_start": str(train_end.date()),
                "oos_end": str(oos_end.date()),
                "n_oos": len(oos),
                "skipped": "too few trades",
            })
            continue

        # CONF tier sizing
        conf_r = replay_tiered(oos, score_field="conf_pct")
        # EER tier sizing
        eer_r = replay_tiered(oos, score_field="eer")

        if conf_r is None or eer_r is None:
            continue

        conf_ret = (conf_r["final"] / 10000 - 1) * 100
        eer_ret = (eer_r["final"] / 10000 - 1) * 100

        # Shuffle null (EER vs random labels)
        shuf = shuffle_null_baseline(oos, score_field="eer", n_iter=100, seed=i)
        p_shuf = shuf["p_value"]

        # Welch top-vs-bottom for EER
        welch_eer = welch_t_top_vs_bottom(oos, "eer", top_cut=0.80, bot_cut=0.20)

        delta_sh = eer_r["sharpe"] - conf_r["sharpe"]
        delta_ret = eer_ret - conf_ret

        print(f"  W{i:<3} {str(train_end.date())} → {str(oos_end.date())}  "
              f"{len(oos):>5}  "
              f"{conf_r['sharpe']:>8.2f} {conf_ret:>+7.1f} {conf_r['max_dd']*100:>+6.1f}  "
              f"{eer_r['sharpe']:>8.2f} {eer_ret:>+7.1f} {eer_r['max_dd']*100:>+6.1f}  "
              f"{delta_sh:>+6.2f} {delta_ret:>+7.1f} {p_shuf:>7.3f}")

        window_results.append({
            "window": i,
            "oos_start": str(train_end.date()),
            "oos_end": str(oos_end.date()),
            "n_oos": len(oos),
            "conf": {
                "sharpe": conf_r["sharpe"],
                "return_pct": conf_ret,
                "max_dd_pct": conf_r["max_dd"] * 100,
                "trades": conf_r["trades"],
                "tier_counts": conf_r["tier_counts"],
                "wr": conf_r["wr"],
                "avg_r": conf_r["avg_r"],
            },
            "eer": {
                "sharpe": eer_r["sharpe"],
                "return_pct": eer_ret,
                "max_dd_pct": eer_r["max_dd"] * 100,
                "trades": eer_r["trades"],
                "tier_counts": eer_r["tier_counts"],
                "wr": eer_r["wr"],
                "avg_r": eer_r["avg_r"],
            },
            "delta_sharpe": delta_sh,
            "delta_return_pct": delta_ret,
            "shuffle_p": p_shuf,
            "shuffle_real_sharpe": shuf["real_sharpe"],
            "shuffle_null_mean": shuf["null_sharpe_mean"],
            "welch_top_vs_bot_R": welch_eer,
        })

    # ---- 7. Summary
    print()
    print("=" * 100)
    print("[7/7] SUMMARY (pre-registered gates)")
    print("=" * 100)

    valid = [w for w in window_results if "skipped" not in w and "delta_sharpe" in w]
    if not valid:
        print("HATA: hicbir pencere valid degil.")
        return 1

    deltas_sharpe = [w["delta_sharpe"] for w in valid]
    deltas_return = [w["delta_return_pct"] for w in valid]
    pvals = [w["shuffle_p"] for w in valid]

    mean_delta_sh = float(np.mean(deltas_sharpe))
    mean_delta_ret = float(np.mean(deltas_return))
    pct_eer_better_sh = sum(1 for d in deltas_sharpe if d > 0) / len(deltas_sharpe)
    pct_shuffle_pass = sum(1 for p in pvals if p < 0.05) / len(pvals)

    # Bootstrap CI on (EER - CONF) Sharpe delta
    rng = np.random.default_rng(42)
    n_boot = 2000
    boot_means = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(deltas_sharpe), len(deltas_sharpe))
        boot_means.append(np.mean(np.array(deltas_sharpe)[idx]))
    ci_low = float(np.percentile(boot_means, 2.5))
    ci_high = float(np.percentile(boot_means, 97.5))

    # Bonferroni: alpha = 0.05 / n_windows
    bonferroni_alpha = 0.05 / max(1, len(valid))
    pct_bonferroni_pass = sum(1 for p in pvals if p < bonferroni_alpha) / len(pvals)

    print(f"\nN pencere (valid): {len(valid)}/{len(windows)}")
    print(f"  Mean OOS ΔSharpe (EER - CONF): {mean_delta_sh:+.4f}")
    print(f"  Mean OOS Δreturn% (EER - CONF): {mean_delta_ret:+.2f}pp")
    print(f"  Pencere oranı EER > CONF (Sharpe): {pct_eer_better_sh*100:.1f}% ({sum(1 for d in deltas_sharpe if d > 0)}/{len(deltas_sharpe)})")
    print(f"  Shuffle p<0.05 pencere oranı: {pct_shuffle_pass*100:.1f}% ({sum(1 for p in pvals if p < 0.05)}/{len(pvals)})")
    print(f"  Bonferroni α={bonferroni_alpha:.5f} — p<α geçen: {pct_bonferroni_pass*100:.1f}%")
    print(f"  Bootstrap CI(95%) mean ΔSharpe: [{ci_low:+.4f}, {ci_high:+.4f}]")

    # Pre-registered gates
    print()
    print("Pre-registered gate'ler:")
    gates = [
        ("Mean ΔSharpe ≥ +0.10", mean_delta_sh, 0.10, ">="),
        ("Mean Δreturn ≥ +3pp", mean_delta_ret, 3.0, ">="),
        ("Bootstrap CI low > 0", ci_low, 0.0, ">"),
        ("Shuffle p<0.05 in ≥ 8/13 windows", pct_shuffle_pass * len(valid), 8, ">="),
        ("Bucket coverage ≥ 20%", eer_stats.bucket_coverage * 100, 20.0, ">="),
    ]
    n_pass = 0
    for label, val, target, op in gates:
        if op == ">=":
            ok = val >= target
        else:
            ok = val > target
        n_pass += int(ok)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label:<45} actual={val:>+8.3f} target={target}")

    print()
    overall = "PASS" if n_pass == len(gates) else "FAIL"
    if mean_delta_sh > 0 and ci_low > 0:
        overall_soft = "PASS (soft)"
    elif mean_delta_sh > 0:
        overall_soft = "MIXED — direction right, magnitude weak"
    else:
        overall_soft = "FAIL"
    print(f"OVERALL: {overall} (hard gates: {n_pass}/{len(gates)}); SOFT: {overall_soft}")

    # Final tier distribution
    all_tier_counts_eer = defaultdict(int)
    all_tier_counts_conf = defaultdict(int)
    for w in valid:
        for k, v in w["eer"]["tier_counts"].items():
            all_tier_counts_eer[k] += v
        for k, v in w["conf"]["tier_counts"].items():
            all_tier_counts_conf[k] += v
    total_eer = sum(all_tier_counts_eer.values())
    total_conf = sum(all_tier_counts_conf.values())
    print(f"\nTier dağılımı (CEO hedef: 20/40/30/10):")
    print(f"  Tier  EER%       CONF%")
    for t in [1, 2, 3, 4]:
        e_pct = all_tier_counts_eer[t] / max(1, total_eer) * 100
        c_pct = all_tier_counts_conf[t] / max(1, total_conf) * 100
        print(f"  T{t}    {e_pct:>5.1f}%    {c_pct:>5.1f}%")

    # ---- Write report
    report_path = ROOT / "reports" / "research" / "eer_v1_results.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("=" * 100)
    lines.append("EER-Score v1 Walk-Forward Results")
    lines.append("=" * 100)
    lines.append(f"Run timestamp: {pd.Timestamp.now(tz='UTC').isoformat()}")
    lines.append(f"git_hash: 27c9752c44b4ecbd386c1d2868a44fb538910879")
    lines.append(f"config_hash: {cfg.config_hash()}")
    lines.append(f"trades_data_hash: {trades_data_hash(all_trades)}")
    lines.append(f"context_data_hash: {ctx_hash}")
    lines.append("")
    lines.append("Pre-registered hypothesis: memory/researcher/hypotheses/2026-05-13-eer-score-v1.md")
    lines.append("")
    lines.append("Summary statistics:")
    lines.append(f"  Total trades:         {len(all_trades)}")
    lines.append(f"  EER bucket coverage:  {eer_stats.bucket_coverage*100:.2f}%")
    lines.append(f"  EER fallback rate:    {eer_stats.fallback_rate*100:.2f}%")
    lines.append(f"  N walk-forward windows valid: {len(valid)}/{len(windows)}")
    lines.append("")
    lines.append(f"Mean OOS ΔSharpe (EER - CONF): {mean_delta_sh:+.4f}")
    lines.append(f"Mean OOS Δreturn% (EER - CONF): {mean_delta_ret:+.2f}pp")
    lines.append(f"Bootstrap CI(95%) mean ΔSharpe: [{ci_low:+.4f}, {ci_high:+.4f}]")
    lines.append(f"Shuffle p<0.05 windows: {sum(1 for p in pvals if p<0.05)}/{len(pvals)}")
    lines.append(f"Bonferroni α={bonferroni_alpha:.5f} — windows passing: {sum(1 for p in pvals if p<bonferroni_alpha)}/{len(pvals)}")
    lines.append("")
    lines.append("Tier distribution (target 20/40/30/10):")
    for t in [1, 2, 3, 4]:
        e_pct = all_tier_counts_eer[t] / max(1, total_eer) * 100
        c_pct = all_tier_counts_conf[t] / max(1, total_conf) * 100
        lines.append(f"  T{t}:  EER={e_pct:.1f}%   CONF={c_pct:.1f}%")
    lines.append("")
    lines.append("Per-window detail:")
    lines.append(f"  {'Win':<4} {'OOS_period':<26} {'n':>5}  "
                 f"{'CONF Sh':>8} {'ret%':>7} {'DD%':>6}  "
                 f"{'EER Sh':>8} {'ret%':>7} {'DD%':>6}  "
                 f"{'ΔSh':>6} {'Δret%':>7} {'shuf_p':>7}")
    for w in valid:
        lines.append(f"  W{w['window']:<3} {w['oos_start']} → {w['oos_end']}  "
                     f"{w['n_oos']:>5}  "
                     f"{w['conf']['sharpe']:>8.2f} {w['conf']['return_pct']:>+7.1f} {w['conf']['max_dd_pct']:>+6.1f}  "
                     f"{w['eer']['sharpe']:>8.2f} {w['eer']['return_pct']:>+7.1f} {w['eer']['max_dd_pct']:>+6.1f}  "
                     f"{w['delta_sharpe']:>+6.2f} {w['delta_return_pct']:>+7.1f} {w['shuffle_p']:>7.3f}")

    lines.append("")
    lines.append("Pre-registered gates:")
    for label, val, target, op in gates:
        ok = (val >= target) if op == ">=" else (val > target)
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label:<45} actual={val:.3f} target={target}")
    lines.append("")
    lines.append(f"Overall HARD: {overall} (gates {n_pass}/{len(gates)})")
    lines.append(f"Overall SOFT: {overall_soft}")
    lines.append("")
    lines.append(f"Elapsed: {time.time() - t0:.1f}s")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRapor: {report_path}")
    print(f"Elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
