"""v1.0.0 — Taksi filosu cozumleri test: Filoyu Buyut (1) + Priority Queue (4) + Dinamik Filo (5).

3y rolling 13 pencere + 2023-2026 single window.

Senaryolar:
  B0  Baseline (BALANCED, max_concurrent=8 sabit)
  B1  Filo 12 sabit (basit genisletme)
  B4  Priority Queue: slot doluyken yeni sinyal conf'u en zayif acik pozisyonu yenerse SWAP
  B5  Dinamik Filo: ATR% bazli max_concurrent (4-12 arasi)
  B6  4+5 birlikte: priority + dinamik
  B7  1+4+5 birlikte: dinamik (max 15 cap) + priority

Replay loop yeniden yazildi — main lab.py'a dokunulmadi (test isolated).
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10


# ---------------------------------------------------------------------------
# BTC ATR% Calendar (cached) — dinamik filo icin
# ---------------------------------------------------------------------------


def build_btc_atr_pct() -> dict:
    """BTC 14-gun ATR% gunluk calendar."""
    sys.path.insert(0, str(ROOT))
    from scripts.run_real_backtest import _load_symbol_ohlcv
    df = _load_symbol_ohlcv("BTC/USDT", tf="1d")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1/14, adjust=False).mean()
    atr_pct = atr14 / df["close"] * 100
    return {df["ts"].iloc[i].date(): float(atr_pct.iloc[i]) for i in range(len(df))}


def dynamic_slot_count(atr_pct: float, cap_max: int = 12) -> int:
    """ATR% -> slot sayisi."""
    if atr_pct < 3.0:
        return min(cap_max, 12)
    elif atr_pct < 5.0:
        return 8
    elif atr_pct < 7.0:
        return 6
    else:
        return 4


# ---------------------------------------------------------------------------
# Custom replay — priority queue + dinamik slot destegi
# ---------------------------------------------------------------------------


def replay_with_options(
    trades: list[dict],
    cfg: ProductionConfig,
    *,
    priority_queue: bool = False,
    dynamic_slot: bool = False,
    slot_cap_max: int = 12,
    swap_margin: float = 0.05,  # yeni sinyal conf en zayifin conf'undan +0.05 ustun olmali
    atr_cal: dict | None = None,
):
    """production_replay'in genisletilmis hali — priority_queue + dinamik_slot.

    Replay altyapisini kopyaladim cunku lab.py'a dokunmak parity bozar.
    """
    if not trades:
        return None
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
        and (t["strategy"], t["symbol"]) not in cfg.drop_pairs
    ]
    if not filtered:
        return None
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    eq_curve = [cfg.initial_capital]
    Rs = []

    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date(); last_w = first.isocalendar()[1]; last_m = first.month
    blocked_until = None
    last_entry = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count: dict = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(p["R"])
                eq_curve.append(equity)
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

    def force_close_swap(pos_to_close, current_ts):
        """Premium taksi: bir acik pozisyonu erken kapat. R = mevcut peak'e gore proxy (-0.5 vary).
        Realistic: live'da bunu simulate edemiyoruz, backtest'te kapama=R-multiple kararla.
        Heuristic: trade su anki gunde kapansaydi R=??? bilinmiyor. Konservatif: R=0 (break-even) varsay.
        Yani swap CESARETSIZ kapama — slot acmak icin opportunity cost odenir.
        """
        nonlocal cash, equity, peak_equity
        # Swap maliyeti: pozisyon break-even kapanir (R=0). Bu konservatif tahmin.
        cash += pos_to_close["margin"]
        equity = cash + sum(q["margin"] for q in open_pos if q is not pos_to_close)
        peak_equity = max(peak_equity, equity)
        Rs.append(0.0)  # swap = 0R
        eq_curve.append(equity)
        open_pos.remove(pos_to_close)

    for t in filtered:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            continue
        d_key = t["entry_ts"].date()
        if cfg.btc_halt_calendar and cfg.btc_halt_calendar.get(d_key, False):
            continue
        side_t = t["side"]
        if cfg.alt_data_skip_long and side_t == "long" and cfg.alt_data_skip_long.get(d_key, False):
            continue
        if cfg.alt_data_skip_short and side_t == "short" and cfg.alt_data_skip_short.get(d_key, False):
            continue
        if cfg.same_day_max is not None and same_day_count.get(d_key, 0) >= cfg.same_day_max:
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cfg.same_symbol_side_cooldown_days:
            continue
        cd = t["entry_ts"].date(); cw = t["entry_ts"].isocalendar()[1]; cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity)/max(daily_anchor,1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity)/max(weekly_anchor,1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity)/max(monthly_anchor,1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue

        # DINAMIK SLOT (5): ATR% bazli max_concurrent
        if dynamic_slot and atr_cal is not None:
            atr_pct = atr_cal.get(d_key, 4.0)  # default 4 (normal)
            current_max = dynamic_slot_count(atr_pct, cap_max=slot_cap_max)
        else:
            current_max = cfg.max_concurrent

        # SLOT DOLU MU? PRIORITY QUEUE (4) tetiklenmesi
        if len(open_pos) >= current_max:
            if priority_queue:
                # En zayif acik pozisyonu bul
                weakest = min(open_pos, key=lambda p: p.get("conf", 0))
                # Yeni sinyal margin asar mi?
                if t["conf"] > weakest["conf"] + swap_margin:
                    force_close_swap(weakest, t["entry_ts"])
                    # Devam, slot acildi
                else:
                    continue
            else:
                continue

        dd_from_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_modifier = 1.0
        if cfg.equity_protect_50 and dd_from_peak >= 0.50: continue
        if cfg.equity_protect_30 and dd_from_peak >= 0.30: risk_modifier = 0.5

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * cfg.risk_pct * risk_modifier

        if cfg.vol_target_enabled:
            vf = max(cfg.vol_min_factor, min(cfg.vol_max_factor, cfg.vol_target_atr_pct / sl_pct))
            risk_d *= vf

        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity:
            cap_v = equity * cfg.max_notional_pct_equity
            if notional > cap_v:
                notional = cap_v
                risk_d = notional * sl_pct

        if cfg.concentration_max_per_symbol_pct:
            existing_sym = sum(p["notional"] for p in open_pos if p.get("symbol") == t["symbol"])
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if existing_sym + notional > sym_cap: continue
        if cfg.max_same_side_concurrent:
            sc = sum(1 for p in open_pos if p.get("side") == t["side"])
            if sc >= cfg.max_same_side_concurrent: continue

        margin = notional / cfg.leverage if cfg.leverage > 0 else notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "exit_ts": t["exit_ts"], "margin": margin, "notional": notional,
            "risk": risk_d, "R": t["R"], "symbol": t["symbol"], "side": t["side"],
            "conf": t["conf"],
        })

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]; max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd: max_dd = dd

    wr = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0

    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": wr, "sum_r": sum(Rs) if Rs else 0}


def main():
    print("=" * 110)
    print("v1.0.0 TAKSI FILOSU COZUMLERI — Filo Buyut (1) + Priority Queue (4) + Dinamik Filo (5)")
    print("=" * 110)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    print("BTC ATR% calendar...")
    atr_cal = build_btc_atr_pct()
    dist = {"low": 0, "normal": 0, "high": 0, "crisis": 0}
    for v in atr_cal.values():
        if v < 3: dist["low"] += 1
        elif v < 5: dist["normal"] += 1
        elif v < 7: dist["high"] += 1
        else: dist["crisis"] += 1
    print(f"  BTC ATR% gun dagilim (5y): low<3 {dist['low']}, normal 3-5 {dist['normal']}, "
          f"high 5-7 {dist['high']}, crisis >7 {dist['crisis']}")

    base = ProductionConfig.from_yaml("configs/risk_balanced.yaml")

    start = all_trades[0]["entry_ts"]; end = all_trades[-1]["exit_ts"]
    windows = []; cur = start
    while cur + pd.Timedelta(days=3*365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3*365)))
        cur += pd.Timedelta(days=60)

    scenarios = [
        ("B0 BASELINE (max 8 sabit)",                    base, dict()),
        ("B1 Filo 12 (sabit genisletme)",                 base.with_overrides(max_concurrent=12), dict()),
        ("B4 Priority Queue (8 + swap)",                  base, dict(priority_queue=True)),
        ("B5 Dinamik Filo (4-12 ATR%)",                   base, dict(dynamic_slot=True, atr_cal=atr_cal)),
        ("B6 PriorityQ + Dinamik",                        base, dict(priority_queue=True, dynamic_slot=True, atr_cal=atr_cal)),
        ("B7 Dinamik (cap 15) + PriorityQ",               base, dict(priority_queue=True, dynamic_slot=True, slot_cap_max=15, atr_cal=atr_cal)),
    ]

    print(f"\n{'scenario':<42} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>6} {'minDD':>7} {'r-adj':>6}")
    print("-" * 105)

    for name, cfg, kw in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            w = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = replay_with_options(w, cfg, **kw)
            if r is None: continue
            ann = ((r["final"]/10_000)**(1/3.0)-1)*100
            anns.append(ann); dds.append(r["max_dd"]*100)
        if not anns: continue
        ma, md = mean(anns), mean(dds)
        ra = ma/abs(md) if md else 0
        marker = ""
        if "BASELINE" in name:
            marker = " <-- baseline"
        elif ma > 40 and md > -32:
            marker = " ⭐⭐ WIN"
        elif ma > 40:
            marker = " ⭐ ROI↑"
        elif md > -28:
            marker = " ⭐ DD↓"
        print(f"  {name:<42} {ma:>+6.1f}% {median(anns):>+5.1f}% {min(anns):>+5.1f}% {max(anns):>+5.1f}% {md:>+4.0f}% {min(dds):>+5.0f}% {ra:>5.3f}{marker}")

    print()
    print("# 2023-2026 SINGLE WINDOW (\$10K)")
    ws_s = pd.Timestamp("2023-01-01", tz="UTC"); we_s = pd.Timestamp("2026-05-12", tz="UTC")
    years = (we_s - ws_s).total_seconds() / (365.25 * 86400)
    w = [t for t in all_trades if ws_s <= t["entry_ts"] < we_s]
    for name, cfg, kw in scenarios:
        r = replay_with_options(w, cfg, **kw)
        if r:
            ann = ((r["final"]/10_000)**(1/years)-1)*100
            print(f"  {name:<42} \${r['final']:>8,.0f} yillik {ann:>+6.2f}% DD {r['max_dd']*100:>+5.1f}% n={r['trades']}")


if __name__ == "__main__":
    main()
