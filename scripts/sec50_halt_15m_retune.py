"""SEC50 — Capitulation halt re-tune for 15m TF (Yol C).

Sec49 per-ay sonuçlarında 20/61 ay sıfır-trade (33%). Hipotez: regime_filter
(btc_capitulation_halt) 1d champion için kalibre edildi (ATR%=6, streak=10,
DD=-25); 15m TF'sinde aynı eşikler kullanılınca halt günleri çoğu trade'i
reddediyor. User mandate aylık %20-25 ise 20 sıfır ay matematiksel olarak
imkansız hale getiriyor.

Bu script:
  Step 1) Mevcut halt mantığı analizi (regime.py oku, doğrula).
  Step 2) Sıfır-ay tanılaması: 20 sıfır-trade ayı için halt-day sayısı + rule
          breakdown (ATR / EMA200 streak / DD).
  Step 3) Threshold sweep: 27 kombinasyon (ATR% × DD × EMA200_streak).
  Step 4) Best parametre seç (objective: min(zero+neg) maximize mean).
  Step 5) Replay parity:
            - 1d Phoenix v2.0.4 champion (default threshold → +%136.37/-%42.2
              byte-identical olmalı, çünkü 1d için kalibre)
            - 5m TOP-2 (default threshold, regression check)
          + halt OFF baseline kıyas.

OUTPUT:
  - reports/engineering/2026-05-17_halt_15m_diagnostic.md
  - reports/engineering/2026-05-17_halt_15m_retune.md
  - reports/engineering/2026-05-17_halt_15m_sweep_results.csv

KISITLAR:
  - 15m pool cached (data/sec31_15m_pool.pkl), 5m pool cached
    (data/sec44_5m_top2_pool.pkl)
  - 1d champion parity için _sec13_4_cache pool kullan (sec21_regression_check
    ile aynı).
  - Tüm sayılar raw — hallucinasyon yok.
"""
from __future__ import annotations

import csv
import io
import itertools
import os
import pickle
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import (
    compute_btc_capitulation_halt,
    _load_ohlcv,
)

# Outputs
REPORT_DIAG = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_diagnostic.md"
REPORT_TUNE = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_retune.md"
CSV_SWEEP = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_sweep_results.csv"

# Inputs
POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
POOL_5M = ROOT / "data" / "sec44_5m_top2_pool.pkl"
POOL_1D = ROOT / "data" / "_sec13_4_cache" / "pool_A6_mult15_t30.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
YAML_5M = ROOT / "configs" / "risk_phoenix_scalp_5m.yaml"
YAML_1D = ROOT / "configs" / "risk_balanced.yaml"

# TOP-4 (sec49 ile birebir aynı)
TOP4_STRATEGIES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}
SYMBOLS_10 = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
}

# Default (baseline = 1d champion kalibrasyonu)
DEFAULT_ATR = 6.0
DEFAULT_STREAK = 10
DEFAULT_DD = -25.0

# Sweep
ATR_GRID = [5.0, 6.0, 7.0, 8.0]            # 1d=6.0 baseline + comp +/-
DD_GRID = [-30.0, -25.0, -20.0]            # 1d=-25 baseline + comp +/-
STREAK_GRID = [10, 15, 20]                 # 1d=10 baseline (EMA200 distance proxy)


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Step 1 + Step 2: Diagnostic — compute halt-day calendar + per-month breakdown
# ---------------------------------------------------------------------------
def build_rule_diagnostic_df(
    atr_threshold: float = DEFAULT_ATR,
    ema200_streak_threshold: int = DEFAULT_STREAK,
    dd_90d_threshold: float = DEFAULT_DD,
) -> pd.DataFrame:
    """BTC 1d OHLCV'den her gün için 3 rule değerini + halt flag'ı döndürür.

    Output columns:
      date | atr_pct | below_ema200_streak | dd_90d | high_vol | bear_streak |
      deep_dd | rule_sum | halt
    """
    df = _load_ohlcv("BTC/USDT", tf="1d").copy()

    # ATR(14) Wilder
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = df["atr14"] / df["close"] * 100

    # EMA200 streak
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["below_ema200"] = (df["close"] < df["ema200"]).astype(int)
    streak = 0
    streaks = []
    for v in df["below_ema200"]:
        if v == 1:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
    df["below_ema200_streak"] = streaks

    # 90d max-DD
    rolling_max = df["close"].rolling(90, min_periods=1).max()
    df["dd_90d"] = (df["close"] / rolling_max - 1) * 100

    # Rule breakdown (causal shift = T-1 verisi)
    df["high_vol"] = (df["atr_pct"] >= atr_threshold).shift(1).fillna(False)
    df["bear_streak"] = (df["below_ema200_streak"] >= ema200_streak_threshold).shift(1).fillna(False)
    df["deep_dd"] = (df["dd_90d"] <= dd_90d_threshold).shift(1).fillna(False)
    df["rule_sum"] = (
        df["high_vol"].astype(int)
        + df["bear_streak"].astype(int)
        + df["deep_dd"].astype(int)
    )
    df["halt_candidate"] = df["rule_sum"] >= 2

    # Resume kuralı (lab.py ile aynı semantik — sticky halt)
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["above_ema50"] = (df["close"] > df["ema50"]).astype(int)
    df["resume_ok"] = (
        (df["atr_pct"] <= 4.0)
        & (df["above_ema50"].rolling(5, min_periods=5).sum() == 5)
    )
    resume_ok_lag = df["resume_ok"].shift(1).fillna(False)

    halt_flags = []
    in_halt = False
    for i in range(len(df)):
        if not in_halt and df["halt_candidate"].iloc[i]:
            in_halt = True
        elif in_halt and resume_ok_lag.iloc[i]:
            in_halt = False
        halt_flags.append(in_halt)
    df["halt"] = halt_flags
    df["date"] = pd.to_datetime(df["ts"]).dt.date

    return df[[
        "date", "atr_pct", "below_ema200_streak", "dd_90d",
        "high_vol", "bear_streak", "deep_dd", "rule_sum", "halt_candidate", "halt",
    ]].reset_index(drop=True)


def per_month_halt_breakdown(rule_df: pd.DataFrame) -> pd.DataFrame:
    """Ayın halt günleri + hangi rule dominant (causal lag dahil)."""
    df = rule_df.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["ym"] = df["dt"].dt.strftime("%Y-%m")

    g = df.groupby("ym")
    out = g.agg(
        days=("halt", "size"),
        halt_days=("halt", "sum"),
        atr_trigger_days=("high_vol", "sum"),
        streak_trigger_days=("bear_streak", "sum"),
        dd_trigger_days=("deep_dd", "sum"),
        mean_atr_pct=("atr_pct", "mean"),
        max_atr_pct=("atr_pct", "max"),
        min_dd_90d=("dd_90d", "min"),
        max_streak=("below_ema200_streak", "max"),
    ).reset_index()
    out["halt_pct"] = (out["halt_days"] / out["days"] * 100).round(1)
    return out


# ---------------------------------------------------------------------------
# Step 3: Per-month replay with custom halt calendar
# ---------------------------------------------------------------------------
def compute_per_month_replay(
    pool: list,
    cfg: ProductionConfig,
    halt_calendar: dict | None,
    label: str,
) -> tuple[list, dict]:
    """Per-ay replay. Halt calendar override edilir.

    Returns:
      results: [(yr, mo, n, mR, ret_pct, dd_pct, r_adj, wr), ...]
      summary: {mean, std, cv, pos, neg, zero, min, max, ge20, ge15}
    """
    cfg_local = replace(cfg, btc_halt_calendar=halt_calendar)

    pool.sort(key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])

    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
        m_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        if cur_month == 12:
            m_end = datetime(cur_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            m_end = datetime(cur_year, cur_month + 1, 1, tzinfo=timezone.utc)
        if m_start > end_dt:
            break
        months.append((cur_year, cur_month, m_start, m_end))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            continue
        r = production_replay(m_trades, cfg_local)
        if r is None:
            continue
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        ra = ret_pct / abs(dd_pct) if dd_pct != 0 else 0
        Rs = [t["R"] for t in m_trades]
        mR = sum(Rs) / len(Rs)
        wr = sum(1 for x in Rs if x > 0) / len(Rs) * 100
        results.append((yr, mo, len(m_trades), mR, ret_pct, dd_pct, ra, wr))

    rets = [r[4] for r in results]
    n = len(rets)
    if n == 0:
        return results, {"label": label, "n_months": 0}

    mean_ret = sum(rets) / n
    std = (sum((x - mean_ret) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0.0
    cv_pct = (std / abs(mean_ret) * 100) if mean_ret != 0 else float("inf")
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge20 = sum(1 for x in rets if x >= 20.0)
    ge15 = sum(1 for x in rets if x >= 15.0)
    min_r = min(rets)
    max_r = max(rets)

    summary = {
        "label": label,
        "n_months": n,
        "mean_pct": round(mean_ret, 3),
        "median_pct": round(sorted(rets)[n // 2], 3),
        "std_pct": round(std, 3),
        "cv_pct": round(cv_pct, 1),
        "min_pct": round(min_r, 3),
        "max_pct": round(max_r, 3),
        "pos": pos,
        "neg": neg,
        "zero": zero,
        "ge20": ge20,
        "ge15": ge15,
    }
    return results, summary


# ---------------------------------------------------------------------------
# Step 5: Walk-forward replay (for parity / regression)
# ---------------------------------------------------------------------------
def walk_forward_summary(
    pool: list,
    cfg: ProductionConfig,
    halt_calendar: dict | None,
    train_years: float = 2.0,
    oos_months: int = 3,
    step_months: int = 1,
    annualize_years: float | None = None,
) -> dict:
    """3y rolling walk-forward (sec31 paterni). Çoğunlukla OOS pencerede
    annualize edilir.

    train_years + oos_months: pencere uzunluğu = train_years + oos/12
    annualize_years: replay.annualized(years) için (default = pencere uzunluğu).
    """
    cfg_local = replace(cfg, btc_halt_calendar=halt_calendar)
    pool.sort(key=lambda t: t["entry_ts"])

    win_start = pool[0]["entry_ts"]
    win_end = pool[-1]["exit_ts"]
    win_len_days = int(train_years * 365 + oos_months * 30)
    step_days = step_months * 30

    cur = win_start
    windows = []
    while cur + pd.Timedelta(days=win_len_days) <= win_end:
        windows.append((cur, cur + pd.Timedelta(days=win_len_days)))
        cur += pd.Timedelta(days=step_days)

    years = annualize_years if annualize_years is not None else (win_len_days / 365.0)

    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if len(w) < 10:
            continue
        r = production_replay(w, cfg_local)
        if r:
            anns.append(r.annualized(years) * 100)
            dds.append(r.max_drawdown * 100)

    if not anns:
        return {"n": 0, "mean_ann": 0, "mean_dd": 0, "r_adj": 0, "neg": 0}

    ma = mean(anns)
    md = mean(dds)
    return {
        "n": len(anns),
        "mean_ann": round(ma, 2),
        "mean_dd": round(md, 2),
        "r_adj": round(ma / abs(md), 3) if md != 0 else 0.0,
        "neg": sum(1 for a in anns if a < 0),
        "windows": len(windows),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("SEC50 — Capitulation halt 15m re-tune")
    print("=" * 78)

    # ------------------------------------------------------------
    # STEP 1: Mevcut halt mantığı + baseline diagnostic
    # ------------------------------------------------------------
    print("\n[STEP 1] BTC capitulation halt calendar (baseline)")
    print(f"  Params: ATR%>={DEFAULT_ATR}, EMA200_streak>={DEFAULT_STREAK}, DD_90d<={DEFAULT_DD}")
    print(f"  Rule: 2-of-3 -> halt; resume = ATR%<=4 & above_EMA50 5g")

    base_diag = build_rule_diagnostic_df(DEFAULT_ATR, DEFAULT_STREAK, DEFAULT_DD)
    total_days = len(base_diag)
    halt_days = int(base_diag["halt"].sum())
    print(f"  Total BTC days: {total_days}")
    print(f"  Halt days: {halt_days} ({halt_days/total_days*100:.1f}%)")

    per_month_base = per_month_halt_breakdown(base_diag)
    print(f"  Per-month rule firing summary (ATR/streak/DD triggered days):")
    print(f"    ATR trigger total: {int(base_diag['high_vol'].sum())}")
    print(f"    Streak trigger total: {int(base_diag['bear_streak'].sum())}")
    print(f"    DD trigger total: {int(base_diag['deep_dd'].sum())}")

    # ------------------------------------------------------------
    # STEP 2: Sıfır-ay tanılaması (CSV'den)
    # ------------------------------------------------------------
    print("\n[STEP 2] Sec49 sıfır-ay analizi")
    sec49_csv = ROOT / "reports" / "lab" / "sec49_per_month.csv"
    df_sec49 = pd.read_csv(sec49_csv)
    zero_months = df_sec49[df_sec49["monthly_pct"] == 0.0].copy()
    zero_months["ym"] = zero_months.apply(lambda r: f"{int(r['year'])}-{int(r['month']):02d}", axis=1)
    print(f"  Sıfır-trade ayı sayısı: {len(zero_months)}/{len(df_sec49)}")

    zero_with_halt = zero_months.merge(per_month_base[[
        "ym", "halt_days", "atr_trigger_days", "streak_trigger_days",
        "dd_trigger_days", "halt_pct", "max_atr_pct", "min_dd_90d", "max_streak",
    ]], on="ym", how="left")

    print("\n  Zero-ay detay (halt_days = capitulation-halt aktif gün sayısı):")
    print(f"  {'YYY-MM':>8} {'n_trd':>6} {'halt_d':>7} {'atr_d':>6} {'strk_d':>7} {'dd_d':>5} "
          f"{'max_atr%':>9} {'min_dd%':>8} {'max_strk':>9}")
    for _, row in zero_with_halt.iterrows():
        print(f"  {row['ym']:>8} {int(row['n_trade']):>6} "
              f"{int(row['halt_days']) if pd.notna(row['halt_days']) else 0:>7} "
              f"{int(row['atr_trigger_days']) if pd.notna(row['atr_trigger_days']) else 0:>6} "
              f"{int(row['streak_trigger_days']) if pd.notna(row['streak_trigger_days']) else 0:>7} "
              f"{int(row['dd_trigger_days']) if pd.notna(row['dd_trigger_days']) else 0:>5} "
              f"{float(row['max_atr_pct']) if pd.notna(row['max_atr_pct']) else 0:>9.2f} "
              f"{float(row['min_dd_90d']) if pd.notna(row['min_dd_90d']) else 0:>8.2f} "
              f"{int(row['max_streak']) if pd.notna(row['max_streak']) else 0:>9}")

    # Write diagnostic report
    REPORT_DIAG.parent.mkdir(parents=True, exist_ok=True)
    diag_lines = []
    diag_lines.append("# SEC50 — Capitulation Halt 15m Diagnostic\n\n")
    diag_lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
    diag_lines.append(f"**Baseline params (1d champion kalibrasyonu):** ATR%>={DEFAULT_ATR}, "
                     f"EMA200_streak>={DEFAULT_STREAK} gün, DD_90d<={DEFAULT_DD}%\n\n")
    diag_lines.append(f"**Halt günleri:** {halt_days}/{total_days} ({halt_days/total_days*100:.1f}%)\n\n")
    diag_lines.append(f"**Rule total triggers (T-1 causal):**\n")
    diag_lines.append(f"- ATR% >= {DEFAULT_ATR}: {int(base_diag['high_vol'].sum())} gün\n")
    diag_lines.append(f"- EMA200_streak >= {DEFAULT_STREAK}: {int(base_diag['bear_streak'].sum())} gün\n")
    diag_lines.append(f"- DD_90d <= {DEFAULT_DD}%: {int(base_diag['deep_dd'].sum())} gün\n\n")
    diag_lines.append(f"## Sec49 Sıfır-Trade Ayları (n={len(zero_months)}/{len(df_sec49)})\n\n")
    diag_lines.append("| YYYY-MM | n trade (raw pool) | halt_days | atr_d | strk_d | dd_d | "
                     "max ATR% | min DD% | max streak |\n")
    diag_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for _, row in zero_with_halt.iterrows():
        diag_lines.append(
            f"| {row['ym']} | {int(row['n_trade']):,} | "
            f"{int(row['halt_days']) if pd.notna(row['halt_days']) else 0} | "
            f"{int(row['atr_trigger_days']) if pd.notna(row['atr_trigger_days']) else 0} | "
            f"{int(row['streak_trigger_days']) if pd.notna(row['streak_trigger_days']) else 0} | "
            f"{int(row['dd_trigger_days']) if pd.notna(row['dd_trigger_days']) else 0} | "
            f"{float(row['max_atr_pct']) if pd.notna(row['max_atr_pct']) else 0:.2f} | "
            f"{float(row['min_dd_90d']) if pd.notna(row['min_dd_90d']) else 0:.2f} | "
            f"{int(row['max_streak']) if pd.notna(row['max_streak']) else 0} |\n"
        )

    # Add per-month baseline overview (all 61 months for context)
    diag_lines.append("\n## Tüm 61 Ay Halt-Day Overview\n\n")
    diag_lines.append("| YYYY-MM | halt_days | dominant trigger |\n")
    diag_lines.append("|---|---:|---|\n")
    for _, row in per_month_base.iterrows():
        ym = row["ym"]
        if not (ym.startswith("202") and ym[5:7].isdigit()):
            continue
        # Filter to sec49 range (2021-05 .. 2026-05)
        if ym < "2021-05" or ym > "2026-05":
            continue
        hd = int(row["halt_days"])
        if hd == 0:
            dominant = "—"
        else:
            triggers = [
                ("ATR", int(row["atr_trigger_days"])),
                ("STRK", int(row["streak_trigger_days"])),
                ("DD", int(row["dd_trigger_days"])),
            ]
            triggers.sort(key=lambda x: -x[1])
            dominant = ", ".join(f"{n}({v})" for n, v in triggers if v > 0)
        diag_lines.append(f"| {ym} | {hd} | {dominant} |\n")

    REPORT_DIAG.write_text("".join(diag_lines), encoding="utf-8")
    print(f"\n  [WRITE] {REPORT_DIAG}")

    # ------------------------------------------------------------
    # STEP 3: Threshold sweep — 15m R4 retest
    # ------------------------------------------------------------
    print("\n[STEP 3] Threshold sweep — 15m R4 TOP-4 retest")
    if not POOL_15M.exists():
        print(f"  FATAL: 15m pool eksik: {POOL_15M}")
        return

    with POOL_15M.open("rb") as fh:
        pool_15m_raw = pickle.load(fh)
    pool_15m = [
        t for t in pool_15m_raw
        if t.get("strategy") in TOP4_STRATEGIES
        and t.get("symbol") in SYMBOLS_10
    ]
    print(f"  15m pool (TOP-4 + 10sym): {len(pool_15m):,} trade")

    # CRITICAL: cfg should mirror sec49 (R4 override + cooldown=0)
    cfg_15m = ProductionConfig.from_yaml(str(YAML_15M))
    cfg_15m = cfg_15m.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"  cfg: pyr_en={cfg_15m.pyramid_enabled} trig={cfg_15m.pyramid_triggers} "
          f"sizes={cfg_15m.pyramid_sizes} mc={cfg_15m.max_concurrent}")

    # Sweep combinations
    combos = list(itertools.product(ATR_GRID, STREAK_GRID, DD_GRID))
    print(f"\n  Sweep: {len(combos)} kombinasyon ({len(ATR_GRID)}x{len(STREAK_GRID)}x{len(DD_GRID)})")
    print(f"  + halt OFF baseline = {len(combos)+1} run")

    sweep_results = []

    # Baseline run: halt OFF (no calendar)
    print(f"\n  [{0:>2}/{len(combos)+1}] HALT OFF (regime_filter.enabled=False)")
    res_off, summary_off = compute_per_month_replay(pool_15m, cfg_15m, None, "halt_OFF")
    halt_days_total = 0
    print(f"      mean={summary_off['mean_pct']:+.2f}% cv={summary_off['cv_pct']:.0f}% "
          f"neg={summary_off['neg']} zero={summary_off['zero']} ge20={summary_off['ge20']}")
    sweep_results.append({
        "atr": None,
        "streak": None,
        "dd": None,
        "halt_days": 0,
        **summary_off,
    })

    # Baseline (default 1d params) — confirm sec49 reproduction
    print(f"\n  [{1:>2}/{len(combos)+1}] BASELINE ATR={DEFAULT_ATR} STRK={DEFAULT_STREAK} DD={DEFAULT_DD}")
    cal_base = compute_btc_capitulation_halt(DEFAULT_ATR, DEFAULT_STREAK, DEFAULT_DD)
    hd = sum(1 for v in cal_base.values() if v)
    res_base, summary_base = compute_per_month_replay(
        pool_15m, cfg_15m, cal_base, f"ATR={DEFAULT_ATR}_STRK={DEFAULT_STREAK}_DD={DEFAULT_DD}",
    )
    print(f"      halt_days={hd} mean={summary_base['mean_pct']:+.2f}% cv={summary_base['cv_pct']:.0f}% "
          f"neg={summary_base['neg']} zero={summary_base['zero']} ge20={summary_base['ge20']}")
    sweep_results.append({
        "atr": DEFAULT_ATR,
        "streak": DEFAULT_STREAK,
        "dd": DEFAULT_DD,
        "halt_days": hd,
        **summary_base,
    })

    # Full sweep
    for i, (atr, strk, dd) in enumerate(combos, start=2):
        # Skip baseline (already done)
        if atr == DEFAULT_ATR and strk == DEFAULT_STREAK and dd == DEFAULT_DD:
            continue
        cal = compute_btc_capitulation_halt(atr, strk, dd)
        hd = sum(1 for v in cal.values() if v)
        res, summary = compute_per_month_replay(
            pool_15m, cfg_15m, cal, f"ATR={atr}_STRK={strk}_DD={dd}",
        )
        print(f"  [{i:>2}/{len(combos)+1}] ATR={atr} STRK={strk} DD={dd} → "
              f"halt={hd} mean={summary['mean_pct']:+.2f}% cv={summary['cv_pct']:.0f}% "
              f"neg={summary['neg']} zero={summary['zero']} ge20={summary['ge20']}")
        sweep_results.append({
            "atr": atr,
            "streak": strk,
            "dd": dd,
            "halt_days": hd,
            **summary,
        })

    # CSV
    CSV_SWEEP.parent.mkdir(parents=True, exist_ok=True)
    with CSV_SWEEP.open("w", newline="", encoding="utf-8") as fh:
        keys = ["atr", "streak", "dd", "halt_days", "label", "n_months",
                "mean_pct", "median_pct", "std_pct", "cv_pct",
                "min_pct", "max_pct", "pos", "neg", "zero", "ge20", "ge15"]
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in sweep_results:
            w.writerow({k: row.get(k, "") for k in keys})
    print(f"\n  [WRITE] {CSV_SWEEP}")

    # ------------------------------------------------------------
    # STEP 4: Best params (objective: minimize (zero+neg), maximize mean,
    #                       subject to walk-forward delta >= -10pp)
    # ------------------------------------------------------------
    print("\n[STEP 4] Best parametre seçimi")

    def composite_score(row):
        # Lower is better — penalize zero+neg, reward mean
        if row["n_months"] == 0:
            return 1e9
        unproductive = (row["zero"] + row["neg"])
        score = unproductive * 10 - row["mean_pct"] * 0.5
        return score

    sorted_sweep = sorted(sweep_results, key=composite_score)
    print(f"\n  Top-5 (sort: composite = zero+neg)*10 - mean*0.5):")
    print(f"  {'ATR':>5} {'STRK':>5} {'DD':>5} {'halt':>5} {'mean%':>8} {'cv%':>5} "
          f"{'neg':>3} {'zero':>4} {'ge20':>4}")
    for row in sorted_sweep[:5]:
        atr = row['atr'] if row['atr'] is not None else "OFF"
        strk = row['streak'] if row['streak'] is not None else "-"
        dd = row['dd'] if row['dd'] is not None else "-"
        print(f"  {str(atr):>5} {str(strk):>5} {str(dd):>5} {row['halt_days']:>5} "
              f"{row['mean_pct']:>+8.2f} {row['cv_pct']:>5.0f} "
              f"{row['neg']:>3} {row['zero']:>4} {row['ge20']:>4}")

    best = sorted_sweep[0]
    print(f"\n  BEST: ATR={best['atr']} STRK={best['streak']} DD={best['dd']} "
          f"(mean {best['mean_pct']:+.2f}%, zero+neg={best['zero']+best['neg']})")

    # ------------------------------------------------------------
    # STEP 4b: Walk-forward for best, baseline, halt OFF
    # ------------------------------------------------------------
    print("\n[STEP 4b] Walk-forward (15m R4) — 2y train + 3mo OOS + 1mo step")

    # Baseline default
    wf_base = walk_forward_summary(
        pool_15m, cfg_15m, compute_btc_capitulation_halt(DEFAULT_ATR, DEFAULT_STREAK, DEFAULT_DD),
        train_years=2.0, oos_months=3, step_months=1,
    )
    print(f"  Baseline: ann={wf_base['mean_ann']:+.2f}% dd={wf_base['mean_dd']:.2f}% "
          f"r-adj={wf_base['r_adj']} n={wf_base['n']}/{wf_base['windows']}")

    # Best
    if best["atr"] is None:
        cal_best = None
    else:
        cal_best = compute_btc_capitulation_halt(best["atr"], best["streak"], best["dd"])
    wf_best = walk_forward_summary(
        pool_15m, cfg_15m, cal_best,
        train_years=2.0, oos_months=3, step_months=1,
    )
    print(f"  BEST:     ann={wf_best['mean_ann']:+.2f}% dd={wf_best['mean_dd']:.2f}% "
          f"r-adj={wf_best['r_adj']} n={wf_best['n']}/{wf_best['windows']}")

    # Halt OFF
    wf_off = walk_forward_summary(
        pool_15m, cfg_15m, None,
        train_years=2.0, oos_months=3, step_months=1,
    )
    print(f"  HALT OFF: ann={wf_off['mean_ann']:+.2f}% dd={wf_off['mean_dd']:.2f}% "
          f"r-adj={wf_off['r_adj']} n={wf_off['n']}/{wf_off['windows']}")

    # ------------------------------------------------------------
    # STEP 5: Replay parity
    # ------------------------------------------------------------
    print("\n[STEP 5] Replay parity")

    # 1d Phoenix v2.0.4 champion (sec21 baseline pattern)
    print("\n  5.1 — 1d Phoenix champion (default halt — kalibrasyon korunmuş olmalı)")
    if POOL_1D.exists():
        try:
            with POOL_1D.open("rb") as f:
                pool_1d = pickle.load(f)
            pool_1d.sort(key=lambda t: t["entry_ts"])

            base_1d = ProductionConfig.from_yaml(str(YAML_1D))
            # sec21 pattern: explicit F&G + halt overlay
            try:
                from scripts.v097_balanced_optimization import build_fng_short_skip
                fng = build_fng_short_skip(20)
            except Exception:
                fng = None
            halt_default = compute_btc_capitulation_halt(DEFAULT_ATR, DEFAULT_STREAK, DEFAULT_DD)
            cfg_1d = replace(base_1d, alt_data_skip_long=None,
                             alt_data_skip_short=fng, btc_halt_calendar=halt_default)

            wf_1d = walk_forward_summary(
                pool_1d, cfg_1d, halt_default,
                train_years=3.0, oos_months=0, step_months=2,  # sec21 = pure 3y rolling
                annualize_years=3.0,
            )
            print(f"  1d default: ann={wf_1d['mean_ann']:+.2f}% dd={wf_1d['mean_dd']:.2f}% "
                  f"r-adj={wf_1d['r_adj']} n={wf_1d['n']}")
            print(f"  Reference (memory): +%136.37 / DD -%42.2 / r-adj 3.229")
            ann_delta = abs(wf_1d['mean_ann'] - 136.37)
            parity_1d = "PASS-ABSOLUT" if ann_delta < 1.0 else ("PASS-NEAR" if ann_delta < 5.0 else "WARN")
            print(f"  Parity: {parity_1d} (Δ = {ann_delta:.2f}pp)")
        except Exception as exc:
            print(f"  WARN: 1d pool skipped — {exc}")
            wf_1d = None
            parity_1d = "SKIP"
    else:
        print(f"  WARN: 1d pool missing — {POOL_1D}")
        wf_1d = None
        parity_1d = "SKIP"

    # 5m TOP-2 (default halt — regression test)
    print("\n  5.2 — 5m TOP-2 (default halt — etkisi olmamalı)")
    if POOL_5M.exists():
        try:
            with POOL_5M.open("rb") as fh:
                pool_5m = pickle.load(fh)
            cfg_5m = ProductionConfig.from_yaml(str(YAML_5M))
            wf_5m = walk_forward_summary(
                pool_5m, cfg_5m,
                compute_btc_capitulation_halt(DEFAULT_ATR, DEFAULT_STREAK, DEFAULT_DD),
                train_years=2.0, oos_months=3, step_months=1,
            )
            print(f"  5m default: ann={wf_5m['mean_ann']:+.2f}% dd={wf_5m['mean_dd']:.2f}% "
                  f"r-adj={wf_5m['r_adj']} n={wf_5m['n']}")
        except Exception as exc:
            print(f"  WARN: 5m pool skipped — {exc}")
            wf_5m = None
    else:
        wf_5m = None

    # ------------------------------------------------------------
    # STEP 6: Verdict
    # ------------------------------------------------------------
    print("\n[STEP 6] Verdict")
    sec49_baseline_ann = 735.73  # from p0_fix_15m_r4_retest
    wf_delta = wf_best['mean_ann'] - wf_base['mean_ann']
    print(f"  Mean ann delta (best vs baseline): {wf_delta:+.2f}pp")
    constraint_ok = wf_best['mean_ann'] >= sec49_baseline_ann * 0.90
    print(f"  WF constraint (>= 90% of baseline {sec49_baseline_ann}%): "
          f"{'PASS' if constraint_ok else 'FAIL'}")

    zero_after = best["zero"]
    neg_after = best["neg"]
    mean_after = best["mean_pct"]
    if zero_after <= 8 and (mean_after - 17.33) >= -1.0:
        verdict = "PASS"
    elif zero_after <= 12:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    print(f"\n  ZERO ay: 20 (sec49) -> {zero_after} (best)")
    print(f"  NEG ay: 9 (sec49) -> {neg_after} (best)")
    print(f"  MEAN: +17.33% (sec49) -> {mean_after:+.2f}% (best)")
    print(f"\n  === VERDICT: {verdict} ===")

    # ------------------------------------------------------------
    # Write retune report
    # ------------------------------------------------------------
    REPORT_TUNE.parent.mkdir(parents=True, exist_ok=True)
    rt = []
    rt.append("# SEC50 — Capitulation Halt 15m Re-tune\n\n")
    rt.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
    rt.append("## TL;DR\n\n")
    rt.append(f"| Metrik | Sec49 (baseline ATR=6/STRK=10/DD=-25) | Best (ATR={best['atr']}/STRK={best['streak']}/DD={best['dd']}) | Halt OFF |\n")
    rt.append(f"|---|---:|---:|---:|\n")
    rt.append(f"| Per-ay mean | +17.33% | {best['mean_pct']:+.2f}% | {sweep_results[0]['mean_pct']:+.2f}% |\n")
    rt.append(f"| Per-ay CV | 223% | {best['cv_pct']:.0f}% | {sweep_results[0]['cv_pct']:.0f}% |\n")
    rt.append(f"| Zero ay | 20/61 | {best['zero']}/61 | {sweep_results[0]['zero']}/61 |\n")
    rt.append(f"| Neg ay | 9/61 | {best['neg']}/61 | {sweep_results[0]['neg']}/61 |\n")
    rt.append(f"| Aylar >=+20% | 15/61 | {best['ge20']}/61 | {sweep_results[0]['ge20']}/61 |\n")
    rt.append(f"| WF mean_ann | {wf_base['mean_ann']:+.2f}% | {wf_best['mean_ann']:+.2f}% | {wf_off['mean_ann']:+.2f}% |\n")
    rt.append(f"| WF DD | {wf_base['mean_dd']:.2f}% | {wf_best['mean_dd']:.2f}% | {wf_off['mean_dd']:.2f}% |\n")
    rt.append(f"| WF r-adj | {wf_base['r_adj']} | {wf_best['r_adj']} | {wf_off['r_adj']} |\n")
    rt.append(f"\n**Verdict: {verdict}**\n\n")

    rt.append("## 1. Diagnostic (Step 1+2)\n\n")
    rt.append(f"- Mevcut halt days: **{halt_days}/{total_days}** ({halt_days/total_days*100:.1f}%)\n")
    rt.append(f"- 1d champion için kalibre (ATR=6/STRK=10/DD=-25)\n")
    rt.append(f"- Sec49 sıfır-trade ayları: 20/61\n")
    rt.append(f"- Detay: `reports/engineering/2026-05-17_halt_15m_diagnostic.md`\n\n")

    rt.append("## 2. Sweep (Step 3)\n\n")
    rt.append(f"Sweep: ATR {ATR_GRID} × STRK {STREAK_GRID} × DD {DD_GRID} = {len(combos)} kombinasyon\n")
    rt.append(f"+ halt OFF + baseline = {len(sweep_results)} total run.\n\n")
    rt.append("**Sweep tablosu (sort: composite score = (zero+neg)*10 - mean*0.5)**\n\n")
    rt.append("| ATR | STRK | DD | halt_days | mean% | CV% | neg | zero | ge20 | score |\n")
    rt.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for row in sorted_sweep[:15]:
        atr = row['atr'] if row['atr'] is not None else "OFF"
        strk = row['streak'] if row['streak'] is not None else "-"
        dd = row['dd'] if row['dd'] is not None else "-"
        score = (row['zero'] + row['neg']) * 10 - row['mean_pct'] * 0.5
        rt.append(f"| {atr} | {strk} | {dd} | {row['halt_days']} | "
                  f"{row['mean_pct']:+.2f} | {row['cv_pct']:.0f} | {row['neg']} | "
                  f"{row['zero']} | {row['ge20']} | {score:.2f} |\n")

    rt.append("\n**Tüm sweep (raw):** `reports/engineering/2026-05-17_halt_15m_sweep_results.csv`\n\n")

    rt.append("## 3. Walk-forward (Step 4b) — 2y train + 3mo OOS + 1mo step\n\n")
    rt.append("| Config | n | mean_ann% | mean_dd% | r-adj | neg |\n")
    rt.append("|---|---:|---:|---:|---:|---:|\n")
    rt.append(f"| Baseline (default) | {wf_base['n']} | {wf_base['mean_ann']:+.2f} | "
              f"{wf_base['mean_dd']:.2f} | {wf_base['r_adj']} | {wf_base['neg']} |\n")
    rt.append(f"| **BEST** (ATR={best['atr']}/STRK={best['streak']}/DD={best['dd']}) | {wf_best['n']} | "
              f"{wf_best['mean_ann']:+.2f} | {wf_best['mean_dd']:.2f} | {wf_best['r_adj']} | "
              f"{wf_best['neg']} |\n")
    rt.append(f"| Halt OFF | {wf_off['n']} | {wf_off['mean_ann']:+.2f} | {wf_off['mean_dd']:.2f} | "
              f"{wf_off['r_adj']} | {wf_off['neg']} |\n\n")

    rt.append("## 4. Replay Parity (Step 5)\n\n")
    if wf_1d is not None:
        rt.append(f"### 4.1 — 1d Phoenix v2.0.4 champion (DEFAULT halt — 1d için kalibre)\n\n")
        rt.append(f"- Measured: ann={wf_1d['mean_ann']:+.2f}% dd={wf_1d['mean_dd']:.2f}% "
                  f"r-adj={wf_1d['r_adj']} n={wf_1d['n']}\n")
        rt.append(f"- Reference (memory): +%136.37 / DD -%42.2 / r-adj 3.229\n")
        rt.append(f"- Parity: **{parity_1d}** (Δ={abs(wf_1d['mean_ann']-136.37):.2f}pp)\n\n")
    else:
        rt.append(f"### 4.1 — 1d Phoenix parity: SKIP (pool missing)\n\n")

    if wf_5m is not None:
        rt.append(f"### 4.2 — 5m TOP-2 (DEFAULT halt)\n\n")
        rt.append(f"- Measured: ann={wf_5m['mean_ann']:+.2f}% dd={wf_5m['mean_dd']:.2f}% "
                  f"r-adj={wf_5m['r_adj']} n={wf_5m['n']}\n\n")
    else:
        rt.append(f"### 4.2 — 5m TOP-2 parity: SKIP\n\n")

    rt.append("## 5. Per-Ay Karşılaştırma (Before vs After) — Best Param\n\n")
    rt.append("| YYYY-MM | n_trade | Sec49% | BEST% | Δ |\n")
    rt.append("|---|---:|---:|---:|---:|\n")
    sec49_dict = {f"{int(r['year'])}-{int(r['month']):02d}": r["monthly_pct"] for _, r in df_sec49.iterrows()}
    for r in res_best if (res_best := compute_per_month_replay(
        pool_15m, cfg_15m, cal_best, "BEST")[0]) else []:
        ym = f"{r[0]}-{r[1]:02d}"
        sec_pct = sec49_dict.get(ym, 0.0)
        delta = r[4] - sec_pct
        rt.append(f"| {ym} | {r[2]:,} | {sec_pct:+.2f}% | {r[4]:+.2f}% | {delta:+.2f}pp |\n")

    rt.append("\n## 6. Önerilen YAML Patch (TF-aware)\n\n")
    rt.append("**Backward compat strategy:** 1d default threshold KORUNUR. 15m ve 5m YAML'larında\n")
    rt.append("explicit TF-spesifik threshold tanımlanır. Halt OFF opsiyonu da YAML key ile mevcut.\n\n")
    rt.append("```yaml\n")
    rt.append("# configs/risk_phoenix_scalp_15m_pyramid_r3.yaml\n")
    rt.append("regime_filter:\n")
    rt.append(f"  btc_capitulation_halt_enabled: true\n")
    rt.append(f"  atr_pct_threshold: {best['atr']}      # 1d default 6.0 — 15m'de ölçeklendi\n")
    rt.append(f"  ema200_streak_days: {best['streak']}  # 1d default 10\n")
    rt.append(f"  dd_90d_threshold_pct: {best['dd']}    # 1d default -25.0\n")
    rt.append(f"  # Reasoning: 15m TF vol profili farklı; default 1d threshold over-active.\n")
    rt.append("```\n\n")

    rt.append("## 7. Verdict Detay\n\n")
    rt.append(f"**Gate kriterleri:**\n")
    rt.append(f"- Zero ay <= 8 (20'den düşürmeli)\n")
    rt.append(f"- Mean değişim >= -1.0pp (+17.33% baseline koruması)\n")
    rt.append(f"- WF ann >= baseline {sec49_baseline_ann}% * 0.90 = {sec49_baseline_ann*0.9:.0f}%\n\n")
    rt.append(f"**Sonuç:**\n")
    rt.append(f"- Zero ay: 20 → **{best['zero']}** {'PASS' if best['zero'] <= 8 else 'FAIL'}\n")
    rt.append(f"- Mean: +17.33% → **{best['mean_pct']:+.2f}%** "
              f"{'PASS' if (best['mean_pct'] - 17.33) >= -1.0 else 'FAIL'}\n")
    rt.append(f"- WF ann: {wf_best['mean_ann']:+.2f}% "
              f"{'PASS' if wf_best['mean_ann'] >= sec49_baseline_ann * 0.9 else 'FAIL'}\n\n")
    rt.append(f"**VERDICT: {verdict}**\n")

    REPORT_TUNE.write_text("".join(rt), encoding="utf-8")
    print(f"\n[WRITE] {REPORT_TUNE}")
    print(f"[DONE]")


if __name__ == "__main__":
    main()
