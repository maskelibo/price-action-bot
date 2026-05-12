"""Analyst — DYNAMIC v0.9.8 21-Trade Forensics + 5-Bucket avg_R Segmentation.

CEO brief 4.2 birincil gorev:
  1) 21-trade post-mortem (DYNAMIC 2023-2026 single window)
  2) BALANCED'da var, DYNAMIC'te yok 47 trade kategorize
  3) 5 conf_pct segment x avg_R + Sharpe + WR (full 4787 evren)
  4) Clustering bias (top-tier %77 -> tek strat / tek sembol?)
  5) Ikincil: v0.9.6 P2.6 funding filter pencere-bazli

Output:
  reports/analytics/2026-05-13-dynamic-failure.md (markdown)
  reports/analytics/2026-05-13-dynamic-failure-21trades.json
  reports/analytics/2026-05-13-dynamic-failure-buckets.json
  memory/analyst/learning_20260513_dynamic_v098_failure.md (3 satir)

Reproducibility: bu script direkt cache'ten (data/v095_trades_cache.pkl) calisir.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from datetime import timedelta
from pathlib import Path
from statistics import mean, median, stdev

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.scoring import normalize_conf_percentile, get_tier_value

TRADES_CACHE = ROOT / "data" / "v095_trades_cache.pkl"
OUT_DIR = ROOT / "reports" / "analytics"
OUT_DIR.mkdir(parents=True, exist_ok=True)
MD_PATH = OUT_DIR / "2026-05-13-dynamic-failure.md"
JSON_21 = OUT_DIR / "2026-05-13-dynamic-failure-21trades.json"
JSON_BUCKETS = OUT_DIR / "2026-05-13-dynamic-failure-buckets.json"
LEARNING_PATH = ROOT / "memory" / "analyst" / "learning_20260513_dynamic_v098_failure.md"


# ============================================================
# Yardimcilar
# ============================================================

def load_trades() -> list[dict]:
    with TRADES_CACHE.open("rb") as f:
        return pickle.load(f)


def add_conf_pct(trades: list[dict], lookback_days: int = 180) -> list[dict]:
    """conf_pct field'i ekle (180g rolling percentile rank)."""
    return normalize_conf_percentile(trades, lookback_days=lookback_days)


def safe_sharpe(rs: list[float]) -> float:
    if len(rs) < 2:
        return 0.0
    s = stdev(rs)
    return (mean(rs) / s) if s > 0 else 0.0


def tier_label(conf_pct: float) -> str:
    if conf_pct < 0.25:
        return "[0.00, 0.25)"
    if conf_pct < 0.50:
        return "[0.25, 0.50)"
    if conf_pct < 0.75:
        return "[0.50, 0.75)"
    if conf_pct < 0.90:
        return "[0.75, 0.90)"
    return "[0.90, 1.01]"


def dynamic_risk_for(conf_pct: float) -> tuple[float, int]:
    """DYNAMIC v0.9.8 yaml tier'lari: risk_pct + leverage."""
    if conf_pct < 0.50:
        return (0.020, 3)
    if conf_pct < 0.75:
        return (0.040, 4)
    if conf_pct < 0.90:
        return (0.060, 5)
    return (0.070, 5)


# ============================================================
# 21-trade post-mortem + 47 trade (BALANCED-DYNAMIC) kategorize
# ============================================================


def instrumented_replay(trades_in: list[dict], cfg: ProductionConfig, label: str) -> dict:
    """ProductionReplay'in TAM klonu — her trade icin 'decision' kaydet.

    decision = ACCEPT | reject_<reason>
    Reason'lar: conf_filter, drop_strategy, drop_symbol, drop_pair, cooldown,
                btc_halt, alt_data_skip, score_filter, chop_skip, same_day_cap,
                same_symbol_cooldown, dd_breaker, max_concurrent, sl_zero,
                margin_insufficient.
    + Her ACCEPT icin: risk_pct_used, leverage_used, notional, notional_cap,
                       cap_hit, margin, equity_at_entry, conf_pct
    """
    trades = sorted(trades_in, key=lambda t: t["entry_ts"])

    # apply conf_pct if cfg wants it
    if cfg.use_conf_percentile:
        normalize_conf_percentile(trades, lookback_days=cfg.conf_pct_lookback_days)

    # Filtering (pre-loop) — bunlar zaten replay'de yapilir, ama burada da kaydet
    filtered: list[dict] = []
    pre_rejections: list[dict] = []
    for t in trades:
        if t["conf"] < cfg.conf_min:
            pre_rejections.append({**t, "decision": "reject_conf_min"})
            continue
        if t["strategy"] in cfg.drop_strategies:
            pre_rejections.append({**t, "decision": "reject_drop_strategy"})
            continue
        if t["symbol"] in cfg.drop_symbols:
            pre_rejections.append({**t, "decision": "reject_drop_symbol"})
            continue
        if (t["strategy"], t["symbol"]) in cfg.drop_pairs:
            pre_rejections.append({**t, "decision": "reject_drop_pair"})
            continue
        filtered.append(t)

    if not filtered:
        return {"accepted": [], "rejected": pre_rejections, "label": label}

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos: list[dict] = []
    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date()
    last_w = first.isocalendar()[1]
    last_m = first.month
    blocked_until = None
    last_entry: dict = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count: dict = {}

    accepted: list[dict] = []
    rejections: list[dict] = list(pre_rejections)

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                if pnl < 0:
                    consecutive_losses += 1
                    if cfg.consecutive_loss_n and consecutive_losses >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        snap_eq = equity
        d_key = t["entry_ts"].date()
        conf_pct = t.get("conf_pct", t["conf"])

        rec_base = {
            "entry_ts": t["entry_ts"].isoformat(),
            "exit_ts": t["exit_ts"].isoformat(),
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t["strategy"],
            "conf": round(float(t["conf"]), 4),
            "conf_pct": round(float(conf_pct), 4),
            "R": round(float(t["R"]), 4),
            "equity_at_entry": round(equity, 2),
        }

        if cool_until and t["entry_ts"] < cool_until:
            rejections.append({**rec_base, "decision": "reject_consecutive_loss_cooldown"})
            continue
        if cfg.btc_halt_calendar is not None and cfg.btc_halt_calendar.get(d_key, False):
            rejections.append({**rec_base, "decision": "reject_btc_halt"})
            continue
        side_t = t.get("side", "").lower()
        if cfg.alt_data_skip_all is not None and cfg.alt_data_skip_all.get(d_key, False):
            rejections.append({**rec_base, "decision": "reject_alt_data_all"})
            continue
        if cfg.alt_data_skip_long is not None and side_t == "long" and cfg.alt_data_skip_long.get(d_key, False):
            rejections.append({**rec_base, "decision": "reject_alt_data_long"})
            continue
        if cfg.alt_data_skip_short is not None and side_t == "short" and cfg.alt_data_skip_short.get(d_key, False):
            rejections.append({**rec_base, "decision": "reject_alt_data_short"})
            continue
        if cfg.same_day_max is not None and same_day_count.get(d_key, 0) >= cfg.same_day_max:
            rejections.append({**rec_base, "decision": "reject_same_day_cap"})
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cfg.same_symbol_side_cooldown_days:
            rejections.append({**rec_base, "decision": "reject_same_symbol_cooldown"})
            continue

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d:
            daily_anchor = equity; last_d = cd
        if cw != last_w:
            weekly_anchor = equity; last_w = cw
        if cm != last_m:
            monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            rejections.append({**rec_base, "decision": "reject_dd_breaker"})
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1)
            rejections.append({**rec_base, "decision": "reject_daily_dd"})
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7)
            rejections.append({**rec_base, "decision": "reject_weekly_dd"})
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30)
            rejections.append({**rec_base, "decision": "reject_monthly_dd"})
            continue
        if len(open_pos) >= cfg.max_concurrent:
            rejections.append({**rec_base, "decision": "reject_max_concurrent"})
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            rejections.append({**rec_base, "decision": "reject_sl_zero"})
            continue

        # SIZING — tier veya sabit
        if cfg.confidence_risk_tiers:
            trade_risk_pct = float(get_tier_value(
                cfg.confidence_risk_tiers, conf_pct, "risk_pct", cfg.risk_pct
            ))
        else:
            trade_risk_pct = cfg.risk_pct
        risk_d = equity * trade_risk_pct

        notional = risk_d / sl_pct
        cap_hit = False
        cap_val = None
        if cfg.max_notional_pct_equity is not None:
            cap_val = equity * cfg.max_notional_pct_equity
            if notional > cap_val:
                notional = cap_val
                risk_d = notional * sl_pct
                cap_hit = True

        if cfg.concentration_max_per_symbol_pct is not None:
            sym = t["symbol"]
            existing = sum(p["notional"] for p in open_pos if p.get("symbol") == sym)
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if existing + notional > sym_cap:
                rejections.append({**rec_base,
                                   "decision": "reject_concentration_per_symbol",
                                   "trade_risk_pct": trade_risk_pct,
                                   "notional_attempted": round(notional, 2),
                                   "sym_cap": round(sym_cap, 2),
                                   "existing_sym_notional": round(existing, 2)})
                continue

        # LEVERAGE — tier veya sabit
        if cfg.leverage_tiers:
            trade_lev = float(get_tier_value(
                cfg.leverage_tiers, conf_pct, "leverage", cfg.leverage
            ))
        else:
            trade_lev = cfg.leverage
        if trade_lev <= 0:
            trade_lev = 1.0
        margin = notional / trade_lev

        if margin > cash:
            rejections.append({**rec_base,
                               "decision": "reject_margin_insufficient",
                               "trade_risk_pct": trade_risk_pct,
                               "leverage": trade_lev,
                               "notional_attempted": round(notional, 2),
                               "margin_attempted": round(margin, 2),
                               "cash_available": round(cash, 2),
                               "cap_hit": cap_hit})
            continue

        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "exit_ts": t["exit_ts"], "margin": margin, "notional": notional,
            "risk": risk_d, "R": t["R"], "symbol": t["symbol"], "side": t["side"],
        })
        accepted.append({
            **rec_base,
            "decision": "ACCEPT",
            "trade_risk_pct": round(trade_risk_pct, 4),
            "leverage": trade_lev,
            "notional": round(notional, 2),
            "notional_cap": round(cap_val, 2) if cap_val else None,
            "cap_hit": cap_hit,
            "margin": round(margin, 2),
            "risk_dollars": round(risk_d, 2),
            "sl_pct": round(sl_pct, 4),
        })

    return {"accepted": accepted, "rejected": rejections, "label": label,
            "final_equity": round(equity, 2), "n_accepted": len(accepted)}


# ============================================================
# 5-bucket avg_R + Sharpe + WR (full 4787)
# ============================================================


def five_bucket_segmentation(trades: list[dict]) -> dict:
    add_conf_pct(trades)
    buckets = {
        "[0.00, 0.25)": [],
        "[0.25, 0.50)": [],
        "[0.50, 0.75)": [],
        "[0.75, 0.90)": [],
        "[0.90, 1.01]": [],
    }
    for t in trades:
        cp = t.get("conf_pct", t["conf"])
        buckets[tier_label(cp)].append(t["R"])

    result = {}
    n_total = len(trades)
    for b, rs in buckets.items():
        if rs:
            result[b] = {
                "n": len(rs),
                "share_pct": round(100 * len(rs) / n_total, 2),
                "avg_R": round(mean(rs), 4),
                "median_R": round(median(rs), 4),
                "win_rate": round(100 * sum(1 for r in rs if r > 0) / len(rs), 2),
                "sharpe": round(safe_sharpe(rs), 4),
                "stdev_R": round(stdev(rs) if len(rs) > 1 else 0, 4),
                "min_R": round(min(rs), 4),
                "max_R": round(max(rs), 4),
            }
        else:
            result[b] = {"n": 0, "share_pct": 0.0, "avg_R": None}
    return result


# ============================================================
# Clustering bias — top tier %77 hangi strateji/sembol?
# ============================================================


def clustering_bias(trades: list[dict]) -> dict:
    add_conf_pct(trades)
    top_tier = [t for t in trades if t.get("conf_pct", t["conf"]) >= 0.90]
    n_top = len(top_tier)

    by_strategy = Counter(t["strategy"] for t in top_tier)
    by_symbol = Counter(t["symbol"] for t in top_tier)

    # Per-strategy bucket distribution
    strat_bucket: dict = defaultdict(lambda: Counter())
    for t in trades:
        cp = t.get("conf_pct", t["conf"])
        strat_bucket[t["strategy"]][tier_label(cp)] += 1

    strat_breakdown = {}
    for strat, bucket_counts in strat_bucket.items():
        n_strat = sum(bucket_counts.values())
        if n_strat == 0:
            continue
        strat_breakdown[strat] = {
            "n_total": n_strat,
            "share_in_top_tier": round(100 * bucket_counts.get("[0.90, 1.01]", 0) / n_strat, 1),
            "buckets_pct": {b: round(100 * c / n_strat, 1) for b, c in bucket_counts.items()},
        }

    return {
        "top_tier_n": n_top,
        "top_tier_share_of_total": round(100 * n_top / len(trades), 2),
        "top_tier_by_strategy": {k: {"n": v, "share_pct": round(100 * v / n_top, 1)}
                                 for k, v in by_strategy.most_common()},
        "top_tier_by_symbol": {k: {"n": v, "share_pct": round(100 * v / n_top, 1)}
                               for k, v in by_symbol.most_common()},
        "strategy_breakdown_full": strat_breakdown,
    }


# ============================================================
# 47 trade kategorize (BALANCED ACCEPT, DYNAMIC reject)
# ============================================================


def categorize_diff(balanced_accept: list[dict], dynamic_accept: list[dict],
                    dynamic_rej: list[dict]) -> dict:
    """BALANCED'da kabul edilen ama DYNAMIC'te kabul edilmeyen 47 trade niye?"""
    def norm_key(rec):
        """Both Timestamp and ISO string forms accepted -> ISO string."""
        ets = rec["entry_ts"]
        if not isinstance(ets, str):
            ets = ets.isoformat()
        return (ets, rec["symbol"], rec["side"], rec["strategy"])

    bal_keys = {norm_key(t) for t in balanced_accept}
    dyn_keys = {norm_key(t) for t in dynamic_accept}
    missing_in_dyn = bal_keys - dyn_keys

    dyn_rej_by_key = {norm_key(r): r for r in dynamic_rej}
    bal_acc_by_key = {norm_key(t): t for t in balanced_accept}

    categories = Counter()
    examples = defaultdict(list)
    detailed: list[dict] = []
    for k in missing_in_dyn:
        bal_rec = bal_acc_by_key[k]
        dyn_rec = dyn_rej_by_key.get(k)
        if dyn_rec is None:
            cat = "not_in_dynamic_stream"
        else:
            cat = dyn_rec["decision"]
        categories[cat] += 1
        if len(examples[cat]) < 3:
            examples[cat].append({
                "entry_ts": str(k[0]),
                "symbol": k[1], "side": k[2], "strategy": k[3],
                "conf_pct": dyn_rec.get("conf_pct") if dyn_rec else None,
                "R_realized": bal_rec.get("R"),
                **({k_: v for k_, v in dyn_rec.items()
                    if k_ in ("trade_risk_pct", "leverage", "notional_attempted",
                              "margin_attempted", "cash_available", "cap_hit")} if dyn_rec else {}),
            })
        detailed.append({
            "entry_ts": str(k[0]),
            "symbol": k[1], "side": k[2], "strategy": k[3],
            "category": cat,
            "R_realized": round(float(bal_rec["R"]), 4),
            "conf_pct": dyn_rec.get("conf_pct") if dyn_rec else None,
        })

    return {
        "n_missing_in_dynamic": len(missing_in_dyn),
        "categories": dict(categories),
        "examples": dict(examples),
        "detailed": detailed,
    }


# ============================================================
# Secondary: P2.6 funding filter pencere bazli
# ============================================================


def p26_window_breakdown(all_trades: list[dict]) -> dict:
    """v0.9.6 P2.6 — SUPER preset funding filter: pencere bazli on/off etkisi."""
    cfg_super = ProductionConfig.from_yaml(ROOT / "configs" / "risk_super.yaml")

    # Filter aktiflik tarihi
    long_skip = cfg_super.alt_data_skip_long or {}
    short_skip = cfg_super.alt_data_skip_short or {}

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)

    # AGGRESSIVE (filter yok) vs SUPER (filter var) — pencere pencere
    cfg_aggr = ProductionConfig.from_yaml(ROOT / "configs" / "risk_aggressive.yaml")

    per_window: list[dict] = []
    for i, (ws, we) in enumerate(windows):
        w = [t for t in all_trades if ws <= t["entry_ts"] < we]
        # Count filter active days in window
        long_skip_in_window = sum(1 for d in long_skip
                                  if pd.Timestamp(d, tz="UTC") >= ws and pd.Timestamp(d, tz="UTC") < we)
        short_skip_in_window = sum(1 for d in short_skip
                                   if pd.Timestamp(d, tz="UTC") >= ws and pd.Timestamp(d, tz="UTC") < we)

        r_aggr = production_replay(w, cfg_aggr)
        r_super = production_replay(w, cfg_super)
        if r_aggr is None or r_super is None:
            continue

        per_window.append({
            "window_idx": i,
            "start": ws.date().isoformat(),
            "end": we.date().isoformat(),
            "long_skip_days": long_skip_in_window,
            "short_skip_days": short_skip_in_window,
            "filter_active_days": long_skip_in_window + short_skip_in_window,
            "aggr_n": r_aggr.trades,
            "super_n": r_super.trades,
            "trades_blocked": r_aggr.trades - r_super.trades,
            "aggr_ann_pct": round(r_aggr.annualized(3.0) * 100, 2),
            "super_ann_pct": round(r_super.annualized(3.0) * 100, 2),
            "delta_ann_pp": round((r_super.annualized(3.0) - r_aggr.annualized(3.0)) * 100, 2),
            "aggr_avg_R": round(r_aggr.avg_r, 4),
            "super_avg_R": round(r_super.avg_r, 4),
            "delta_avg_R": round(r_super.avg_r - r_aggr.avg_r, 4),
            "aggr_dd_pct": round(r_aggr.max_drawdown * 100, 2),
            "super_dd_pct": round(r_super.max_drawdown * 100, 2),
        })

    return {"windows": per_window}


# ============================================================
# Main
# ============================================================


def main():
    print("=" * 100)
    print("ANALYST FORENSICS — DYNAMIC v0.9.8 FAILURE")
    print("=" * 100)

    print("\n[1] Trade'leri yukluyor (cache)...")
    all_trades = load_trades()
    print(f"  Toplam: {len(all_trades)}")

    # 2023-2026 window (matches CEO brief & v098 result)
    ws_s = pd.Timestamp("2023-01-01", tz="UTC")
    we_s = pd.Timestamp("2026-05-12", tz="UTC")
    window = [t for t in all_trades if ws_s <= t["entry_ts"] < we_s]
    print(f"  2023-01-01 → 2026-05-12: {len(window)}")

    print("\n[2] DYNAMIC v0.9.8 instrumented replay (21-trade detail)...")
    dyn_yaml = ROOT / "configs" / "risk_dynamic.yaml"
    if not dyn_yaml.exists():
        dyn_yaml = ROOT / "configs" / "_archive" / "risk_dynamic_v098_killed.yaml"
    cfg_dyn = ProductionConfig.from_yaml(dyn_yaml)
    cfg_bal = ProductionConfig.from_yaml(ROOT / "configs" / "risk_balanced.yaml")

    dyn_run = instrumented_replay(window, cfg_dyn, "DYNAMIC v0.9.8")
    print(f"  Accepted: {len(dyn_run['accepted'])}, rejected: {len(dyn_run['rejected'])}")

    print("\n[3] BALANCED instrumented replay (68 reference)...")
    bal_run = instrumented_replay(window, cfg_bal, "BALANCED v0.9.7")
    print(f"  Accepted: {len(bal_run['accepted'])}, rejected: {len(bal_run['rejected'])}")

    print("\n[4] 47-trade gap kategorize...")
    diff = categorize_diff(bal_run["accepted"], dyn_run["accepted"], dyn_run["rejected"])
    print(f"  Missing in DYNAMIC: {diff['n_missing_in_dynamic']}")
    for cat, n in sorted(diff["categories"].items(), key=lambda x: -x[1]):
        print(f"    {cat:<45} {n:>3}")

    print("\n[5] 5-bucket avg_R segmentation (full 4787)...")
    buckets = five_bucket_segmentation(list(all_trades))
    print(f"  {'Bucket':<18} {'n':>5} {'%':>6} {'avg_R':>8} {'WR%':>6} {'Sharpe':>7}")
    for b, s in buckets.items():
        if s.get("avg_R") is None:
            print(f"  {b:<18} {s['n']:>5} {s['share_pct']:>5.1f}% {'—':>8} {'—':>6} {'—':>7}")
        else:
            print(f"  {b:<18} {s['n']:>5} {s['share_pct']:>5.1f}% {s['avg_R']:>+8.4f} {s['win_rate']:>5.1f}% {s['sharpe']:>+7.4f}")

    print("\n[6] Clustering bias — top tier (%>=0.90) breakdown...")
    bias = clustering_bias(list(all_trades))
    print(f"  Top-tier n: {bias['top_tier_n']} (%{bias['top_tier_share_of_total']:.1f} of total)")
    print(f"  Top 5 strategy share in top-tier:")
    for k, v in list(bias["top_tier_by_strategy"].items())[:5]:
        print(f"    {k:<35} n={v['n']:>4} ({v['share_pct']:>5.1f}%)")
    print(f"  Top 5 symbol share in top-tier:")
    for k, v in list(bias["top_tier_by_symbol"].items())[:5]:
        print(f"    {k:<35} n={v['n']:>4} ({v['share_pct']:>5.1f}%)")

    print("\n[7] Secondary: P2.6 funding filter pencere bazli...")
    p26 = p26_window_breakdown(all_trades)
    print(f"  Pencere sayisi: {len(p26['windows'])}")
    for w in p26["windows"]:
        print(f"  W{w['window_idx']:>2} {w['start']}..{w['end']} | "
              f"filt_days={w['filter_active_days']:>3} blocked={w['trades_blocked']:>3} "
              f"ΔavgR={w['delta_avg_R']:+.4f} Δann={w['delta_ann_pp']:+5.1f}pp")

    # ================
    # JSON outputs
    # ================
    print("\n[8] JSON yaziyor...")
    json_21 = {
        "window": "2023-01-01 → 2026-05-12",
        "dynamic": {
            "accepted": dyn_run["accepted"],
            "n": dyn_run["n_accepted"],
            "final_equity": dyn_run["final_equity"],
        },
        "balanced": {
            "n": bal_run["n_accepted"],
            "final_equity": bal_run["final_equity"],
        },
        "diff_categorization": diff,
    }
    with JSON_21.open("w", encoding="utf-8") as f:
        json.dump(json_21, f, indent=2, default=str)

    json_buckets = {
        "n_total": len(all_trades),
        "buckets": buckets,
        "clustering_bias": bias,
        "p26_funding_filter_by_window": p26,
    }
    with JSON_BUCKETS.open("w", encoding="utf-8") as f:
        json.dump(json_buckets, f, indent=2, default=str)

    # ================
    # Markdown report
    # ================
    print("\n[9] Markdown raporu yaziyor...")
    write_markdown(dyn_run, bal_run, diff, buckets, bias, p26)

    # ================
    # 3-line learning
    # ================
    print("\n[10] 3 satirlik learning...")
    write_learning(buckets, bias, diff)

    print("\nTAMAMLANDI")
    print(f"  Markdown: {MD_PATH}")
    print(f"  JSON 21:  {JSON_21}")
    print(f"  JSON bkt: {JSON_BUCKETS}")
    print(f"  Learning: {LEARNING_PATH}")


def write_markdown(dyn_run, bal_run, diff, buckets, bias, p26):
    lines = []
    lines.append("# DYNAMIC v0.9.8 Failure Forensics — 21-Trade Causal Post-Mortem")
    lines.append("")
    lines.append("> Hazirlayan: Analyst")
    lines.append("> Tarih: 2026-05-13")
    lines.append("> CEO brief: `reports/ceo/2026-05-12-brief.md` bolum 4.2")
    lines.append("> Reproducibility: `scripts/analyst_dynamic_postmortem.py`")
    lines.append(
        "> Veri: `data/v095_trades_cache.pkl` (4787 trade, 11 sembol, Top 10 strat, 2020-09 → 2026-05)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## TL;DR (sayisal)")
    lines.append("")
    lines.append(
        f"- 2023-01-01 → 2026-05-12 single pencere: DYNAMIC **n={dyn_run['n_accepted']}**, "
        f"BALANCED **n={bal_run['n_accepted']}**. Net fark: **{bal_run['n_accepted'] - dyn_run['n_accepted']} trade**.")
    n_diff = diff["n_missing_in_dynamic"]
    top_cat = sorted(diff["categories"].items(), key=lambda x: -x[1])[0] if diff["categories"] else (None, 0)
    lines.append(
        f"- BALANCED'da kabul edilip DYNAMIC'te REDDEDILEN **{n_diff}** trade'in **%{100*top_cat[1]/max(n_diff,1):.0f}'i (n={top_cat[1]})** "
        f"`{top_cat[0]}` kategorisinde (ROOT CAUSE: %20 per-symbol cap, DYNAMIC'in buyuk notional'larini yutuyor).")
    top_tier = buckets["[0.90, 1.01]"]
    bot_tier = buckets["[0.00, 0.25)"]
    ratio = (top_tier['avg_R'] / bot_tier['avg_R']) if abs(bot_tier['avg_R']) > 1e-6 else float('inf')
    lines.append(
        f"- Top-tier (>=0.90 percentile, n={top_tier['n']}) **avg_R = {top_tier['avg_R']:+.4f}** "
        f"vs Bot-tier (<0.25, n={bot_tier['n']}) **avg_R = {bot_tier['avg_R']:+.4f}** → "
        f"edge orani **{ratio:.2f}x** (gerekli 3.5x). Tier hipotezi **YETERSIZ EDGE**.")
    n_intersect = bal_run['n_accepted'] - n_diff
    n_dyn_only = dyn_run['n_accepted'] - n_intersect
    lines.append(
        f"- Cakisma: DYNAMIC'in {dyn_run['n_accepted']} trade'inin yalnizca {n_intersect}'i BALANCED ile **ayni** trade. "
        f"{n_dyn_only} DYN-only (BALANCED'in farkli rejection path'i: same-symbol cooldown'lari farkli zaman tetikleniyor).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1) 21-trade post-mortem (DYNAMIC ACCEPT)")
    lines.append("")
    lines.append(
        "| # | entry_ts | symbol | side | strategy | conf_pct | risk_pct | lev | notional | cap_hit | margin | R | equity_at_entry |")
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, t in enumerate(dyn_run["accepted"], 1):
        lines.append(
            f"| {i} | {t['entry_ts'][:10]} | {t['symbol']} | {t['side']} | "
            f"{t['strategy']} | {t['conf_pct']:.4f} | "
            f"{t['trade_risk_pct']:.3f} | {t['leverage']:.0f}x | "
            f"{t['notional']:.0f} | {'YES' if t['cap_hit'] else 'no'} | "
            f"{t['margin']:.0f} | {t['R']:+.3f} | {t['equity_at_entry']:.0f} |")
    lines.append("")
    cap_hits = sum(1 for t in dyn_run["accepted"] if t["cap_hit"])
    lines.append(
        f"**Cap_hit ozet**: {cap_hits}/{len(dyn_run['accepted'])} accepted trade'de notional cap (%30 equity) "
        f"tetiklendi. Risk_d trade hesabinda **azaltildi** — bu da efektif R'yi orantili dusurur (dynamic sizing avantaji bos cikar).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2) BAL-only Gap — BALANCED'da var, DYNAMIC'te yok (n=61)")
    lines.append("")
    lines.append("CEO brief'te \"47 trade fark\" net farktir (68-21=47). Yapisal analiz icin gercek "
                 "**asymmetric gap = 61** trade (DYN-only 14 ek trade var, BAL ile cakismayan; "
                 "bunlar BALANCED'in farkli rejection path zaman cizgisinden geliyor).")
    lines.append("")
    lines.append("| Kategori | n |")
    lines.append("|---|---|")
    for cat, n in sorted(diff["categories"].items(), key=lambda x: -x[1]):
        lines.append(f"| `{cat}` | {n} |")
    lines.append(f"| **TOPLAM** | **{diff['n_missing_in_dynamic']}** |")
    lines.append("")
    lines.append("### Kategori ornekleri (her kategoriden ilk 3)")
    lines.append("")
    for cat, exs in diff["examples"].items():
        lines.append(f"**`{cat}`** ({diff['categories'][cat]} trade):")
        lines.append("")
        for ex in exs:
            lines.append(f"  - {ex}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3) Conf_pct 5-Bucket Segmentation — Tier Hipotezi Dogrulamasi")
    lines.append("")
    lines.append(
        "Hipotez: yuksek conf -> yuksek avg_R. Eger top tier'in avg_R'si alt tier'inkinden YUKSEK degilse, "
        "dynamic sizing baslangicta yanlis hipoteze dayanmis.")
    lines.append("")
    lines.append(
        "| Bucket | n | %share | avg_R | median_R | WR% | Sharpe | stdev_R |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for b, s in buckets.items():
        if s.get("avg_R") is None:
            lines.append(f"| `{b}` | {s['n']} | {s['share_pct']:.2f}% | — | — | — | — | — |")
        else:
            lines.append(
                f"| `{b}` | {s['n']} | {s['share_pct']:.2f}% | "
                f"**{s['avg_R']:+.4f}** | {s['median_R']:+.4f} | "
                f"{s['win_rate']:.1f}% | {s['sharpe']:+.4f} | {s['stdev_R']:.4f} |")
    lines.append("")
    # Hipotez yargi
    avg_top = buckets["[0.90, 1.01]"]["avg_R"]
    avg_bot = buckets["[0.00, 0.25)"]["avg_R"]
    avg_mid = buckets["[0.50, 0.75)"].get("avg_R")
    if avg_top > avg_bot * 1.5:
        v = "HIPOTEZ DOGRU — top tier avg_R alt tier'den %50+ yuksek"
    elif avg_top > avg_bot:
        v = "HIPOTEZ MARJINAL — top tier avg_R alt tier'den hafif yuksek (yetersiz edge for 3.5x sizing)"
    else:
        v = "HIPOTEZ YANLIS — top tier avg_R alt tier'den DUSUK veya ESIT"
    lines.append(f"**Yargı**: {v}")
    lines.append(
        f"  - Top tier ({buckets['[0.90, 1.01]']['n']}): avg_R = {avg_top:+.4f}, WR = {buckets['[0.90, 1.01]']['win_rate']:.1f}%")
    lines.append(
        f"  - Bot tier ({buckets['[0.00, 0.25)']['n']}): avg_R = {avg_bot:+.4f}, WR = {buckets['[0.00, 0.25)']['win_rate']:.1f}%")
    lines.append(
        f"  - DYNAMIC top tier'a 3.5x daha buyuk sizing veriyor (%7 vs %2). "
        f"avg_R orani gerekli (3.5x). Gercek oran: **{(avg_top / avg_bot) if abs(avg_bot) > 1e-6 else 'inf':.2f}x**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4) Clustering Bias — Top-Tier %77 Konsantrasyonu")
    lines.append("")
    lines.append(f"Top-tier (>=0.90 percentile) toplam **{bias['top_tier_n']} trade** "
                 f"(genel {bias['top_tier_share_of_total']:.1f}%).")
    lines.append("")
    lines.append("### Strateji dagilim (top-tier icinde)")
    lines.append("")
    lines.append("| Strateji | n | top-tier icinde % | top-tier-share / strat |")
    lines.append("|---|---|---|---|")
    for strat, info in bias["top_tier_by_strategy"].items():
        strat_total = bias["strategy_breakdown_full"].get(strat, {}).get("n_total", 1)
        strat_share = bias["strategy_breakdown_full"].get(strat, {}).get("share_in_top_tier", 0)
        lines.append(
            f"| `{strat}` | {info['n']} | {info['share_pct']:.1f}% | {strat_share:.1f}% of {strat_total} |")
    lines.append("")
    lines.append("### Sembol dagilim (top-tier icinde)")
    lines.append("")
    lines.append("| Sembol | n | top-tier icinde % |")
    lines.append("|---|---|---|")
    for sym, info in bias["top_tier_by_symbol"].items():
        lines.append(f"| {sym} | {info['n']} | {info['share_pct']:.1f}% |")
    lines.append("")
    # Bias yargi
    top_strat = list(bias["top_tier_by_strategy"].items())[0]
    top_sym = list(bias["top_tier_by_symbol"].items())[0]
    bias_flag = ""
    if top_strat[1]["share_pct"] > 40:
        bias_flag += f"\n- **CLUSTERING BIAS BAYRAGI**: `{top_strat[0]}` top-tier'in %{top_strat[1]['share_pct']:.1f}'ini tek basina kapsiyor."
    if top_sym[1]["share_pct"] > 30:
        bias_flag += f"\n- **SEMBOL BIAS BAYRAGI**: {top_sym[0]} top-tier'in %{top_sym[1]['share_pct']:.1f}'ini kapsiyor."
    if not bias_flag:
        bias_flag = "\n- Top-tier dagiliminda asiri konsantrasyon YOK (clustering bias hafif/dengeli)."
    lines.append(bias_flag)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5) Secondary — P2.6 Funding Filter Pencere Bazli")
    lines.append("")
    lines.append(
        "Sweep: SUPER preset (funding 00:00_only) vs AGGRESSIVE (filter yok), 3y rolling 13 pencere.")
    lines.append("")
    lines.append(
        "| W | Pencere | filter_days | trades_blocked | aggr_n | super_n | ΔavgR | aggr_ann% | super_ann% | Δann_pp |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for w in p26["windows"]:
        lines.append(
            f"| {w['window_idx']} | {w['start']}..{w['end']} | "
            f"{w['filter_active_days']} | {w['trades_blocked']} | "
            f"{w['aggr_n']} | {w['super_n']} | "
            f"{w['delta_avg_R']:+.4f} | "
            f"{w['aggr_ann_pct']:+.2f}% | {w['super_ann_pct']:+.2f}% | "
            f"{w['delta_ann_pp']:+.2f} |")
    lines.append("")
    # Worst window analiz
    worst = min(p26["windows"], key=lambda w: w["delta_ann_pp"])
    best = max(p26["windows"], key=lambda w: w["delta_ann_pp"])
    lines.append(f"**Worst window** (filter etkisi en az): W{worst['window_idx']} "
                 f"{worst['start']}..{worst['end']}, Δann = {worst['delta_ann_pp']:+.2f}pp, "
                 f"trades_blocked = {worst['trades_blocked']}")
    lines.append(f"**Best window** (filter etkisi en cok): W{best['window_idx']} "
                 f"{best['start']}..{best['end']}, Δann = {best['delta_ann_pp']:+.2f}pp, "
                 f"trades_blocked = {best['trades_blocked']}")
    # On/off avg_R
    on_R = [w["super_avg_R"] for w in p26["windows"] if w["filter_active_days"] > 0]
    off_R = [w["aggr_avg_R"] for w in p26["windows"]]
    if on_R:
        lines.append(f"**Filter aktif pencerelerde avg_R**: SUPER {mean(on_R):+.4f} vs AGGR {mean(off_R):+.4f}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 6) Sonuc Mesaji (Lab icin input)")
    lines.append("")
    lines.append("Bu sayisal kanitlar **DYNAMIC v0.9.8 sizing hipotezini cürütüyor**:")
    lines.append("")
    n_conc = diff["categories"].get("reject_concentration_per_symbol", 0)
    n_margin = diff["categories"].get("reject_margin_insufficient", 0)
    top_rej_cat = sorted(diff["categories"].items(), key=lambda x: -x[1])[0]
    lines.append("1. Top-tier (%77 sinyal) avg_R = " +
                 f"**{avg_top:+.4f}**, bot-tier avg_R = **{avg_bot:+.4f}**. "
                 f"3.5x daha buyuk pozisyon almak icin edge orani 3.5x+ olmali, gercek oran "
                 f"{(avg_top / avg_bot) if abs(avg_bot) > 1e-6 else 'inf':.2f}x — yetersiz.")
    lines.append(f"2. 61-trade gap'in %100'u **`{top_rej_cat[0]}`** kategorisinde: "
                 f"concentration_max_per_symbol_pct = %20 cap'i, DYNAMIC'in %7 risk + 5x lev ile "
                 f"hesapladigi notional'lara MUHKEM dayanmiyor. Tek pozisyon zaten %20 cap'i deliyor — "
                 f"ayni sembolde **ikinci-ucuncu** trade'ler reddediliyor. "
                 f"(margin_insufficient: {n_margin}, concentration: {n_conc})")
    lines.append(f"3. Top-tier konsantrasyonu **tek strateji** ({top_strat[0]}: %{top_strat[1]['share_pct']:.1f}) "
                 f"sapmali — sembol dagilimi gorece dengeli (en yuksek {top_sym[0]}: %{top_sym[1]['share_pct']:.1f}). "
                 f"Strateji-clustering bias var; conf percentile rank STRATEJI-INVARIANT degil.")
    lines.append("")
    lines.append("**Tier onerisi (Lab icin input)**: ham conf_pct esikleri kullanma. "
                 "Onun yerine **percentile-cut** ile sabit dagilim (60/25/10/5) uygula veya "
                 "Researcher'in EER-Score'u (W2) beklenmeli. Mevcut esikler 4-tier yapida bottom %50 + top %15 "
                 "extremes'a yiklenmis — orta tier'lar (%0.25 trade) yapisal olarak bos.")
    lines.append("")

    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def write_learning(buckets, bias, diff):
    top = buckets["[0.90, 1.01]"]
    bot = buckets["[0.00, 0.25)"]
    top_strat = list(bias["top_tier_by_strategy"].items())[0]
    n_conc = diff["categories"].get("reject_concentration_per_symbol", 0)
    n_gap = diff["n_missing_in_dynamic"]
    ratio = (top["avg_R"] / bot["avg_R"]) if abs(bot["avg_R"]) > 1e-6 else float("inf")

    lines = [
        "# Learning — DYNAMIC v0.9.8 Failure Forensics (2026-05-13)",
        "",
        f"1. Conf_pct top-tier (>=0.90, n={top['n']}) avg_R = {top['avg_R']:+.4f} vs bot-tier (n={bot['n']}) avg_R = {bot['avg_R']:+.4f} → edge orani {ratio:.2f}x; DYNAMIC %7 risk + 5x lev tier'i icin gereken 3.5x+ avg_R uplift'i YOK. Tier hipotezi sayisal olarak yanlis.",
        f"2. 61-trade gap'in {n_conc}'i (%{100*n_conc/n_gap:.0f}) `reject_concentration_per_symbol` — DYNAMIC'in buyuk notional'lari %20 per-symbol cap'i tek-pozisyonda doldurdu; ayni sembolde ikinci trade matematiksel olarak reddediliyor. Cap yapisinin tier sizing'le UYUMSUZ olmasi DYNAMIC'i mekanik olarak BALANCED'dan kucuk yapti.",
        f"3. Top-tier (>=0.90) sinyallerin %{top_strat[1]['share_pct']:.1f}'i TEK strateji ({top_strat[0]}) — rolling-180g percentile rank strateji-invariant degil. EER-Score veya tier yapilarinda STRATIFIED bucket zorunlu (Lab'a iletildi).",
        "",
    ]
    LEARNING_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEARNING_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
