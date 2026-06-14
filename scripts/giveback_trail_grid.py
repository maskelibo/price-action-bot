"""Giveback Trail Grid — Geç-Aktive Kâr Koruma Trail Backtest.

HIPOTEZ (2026-06-01):
  Mevcut champion: trail_pct=0.10, stage=2 (TP2 sonrası fiyat-bazlı).
  Yeni mantık: entry kârı (%) takip et, peak_profit% >= T olunca SL'i
  peak_profit%-G noktasında kilitle (ratchet: sadece lehte hareket).
  T < eşiği = champion let-run korunur (küçük runner'lar serbest).

YÖNTEM:
  1. Champion cache (data/_trail_pct_cache/trades_pct0.100_stage2.pkl)
     engine tarafından üretilmiş gerçek trade'ler — in_position mantığı
     korunmuş, 394k trade, 4 strateji × 10 sembol × 2021-2026.
  2. Her trade için: entry_ts → OHLCV bar bul, entry bar'dan itibaren
     giveback trail mantığıyla yeniden simüle et.
  3. Referans champion: cache'deki R değerleri (= engine re-sim ile parity).
     Her giveback hücresi: aynı entry/exit fırsatları, farklı trail exit.
  4. Giveback metriği: kazanan trade'lerde peak_profit% - exit_profit%
     (ne kadar açık kâr geri verildi).

GRID:
  T (aktivasyon eşiği) ∈ {0.06, 0.08, 0.09, 0.10}
  G (giveback puanı)   ∈ {0.02, 0.03, 0.04}
  Fee: 55bps + 100bps extra

Çalıştır: .venv/bin/python scripts/giveback_trail_grid.py
"""
from __future__ import annotations

import os
import pickle
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from price_action.backtest.lab import ProductionConfig, production_replay  # noqa: E402
from scripts.run_real_backtest import _load_symbol_ohlcv  # noqa: E402

# ----- Sabitler -----
CHAMPION_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
CHAMPION_CACHE = ROOT / "data" / "_trail_pct_cache" / "trades_pct0.100_stage2.pkl"
CACHE_DIR = ROOT / "data" / "_giveback_trail_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

# Champion parametreleri
CHAMPION_TRAIL_PCT = 0.10
CHAMPION_STAGE = 2

# TP yapısı — engine'deki champion config (25/25/50)
TP1_R = 1.0
TP2_R = 1.5
TP1_CLOSE_PCT = 0.25
TP2_CLOSE_PCT = 0.25
RUNNER_FORCE_EXIT_BARS = 48   # 15m x 48 = 12 saat

TAKER_FEE = 0.00075
SLIP_BPS = 5.0
EXTRA_BPS_BASELINE = 55.0
EXTRA_BPS_STRESS = 100.0

# Giveback grid
T_VALUES = [0.06, 0.08, 0.09, 0.10]
G_VALUES = [0.02, 0.03, 0.04]


# ── OHLCV önbelleği ─────────────────────────────────────────────────────────

_OHLCV_CACHE: dict[str, tuple[object, dict]] = {}   # sym → (df, idx_by_ts)


def get_ohlcv(sym: str):
    """OHLCV ve ts→index map'ini döndür (lazy load)."""
    if sym not in _OHLCV_CACHE:
        df = _load_symbol_ohlcv(sym, tf="15m")
        if df is None or df.empty:
            return None, {}
        df = df.sort_values("ts").reset_index(drop=True)
        idx_by_ts = {pd.Timestamp(ts): i for i, ts in enumerate(df["ts"])}
        _OHLCV_CACHE[sym] = (df, idx_by_ts)
    return _OHLCV_CACHE[sym]


# ── Trade yeniden simülatörü ────────────────────────────────────────────────

def resim_trade_giveback(
    df,                  # full OHLCV DataFrame (sym)
    entry_i: int,        # entry bar index (df.iloc[entry_i])
    entry_price: float,
    sl_price: float,
    side: str,
    atr_val: float,
    mode: str,           # "champion" | "giveback"
    trail_T: float = 0.08,
    trail_G: float = 0.03,
) -> dict:
    """Entry bar'dan itibaren yeniden simüle et.

    Champion mode: stage>=2 sonra peak*(1-0.10) trail (engine parity).
    Giveback mode: champion trail AYNI + peak_profit% >= T olunca
                   SL = entry*(1 + peak_profit% - G) ratchet override.

    Döndürür: R, peak_profit_pct, exit_profit_pct, giveback_activated, holding_bars.
    """
    slip = SLIP_BPS / 10_000.0
    initial_R_dist = abs(entry_price - sl_price)
    if initial_R_dist <= 0:
        initial_R_dist = entry_price * 0.025

    tp1_price = (
        (entry_price + TP1_R * initial_R_dist) if side == "long"
        else (entry_price - TP1_R * initial_R_dist)
    )
    tp2_price = (
        (entry_price + TP2_R * initial_R_dist) if side == "long"
        else (entry_price - TP2_R * initial_R_dist)
    )

    qty = 1.0
    qty1 = qty * TP1_CLOSE_PCT
    qty2 = qty * TP2_CLOSE_PCT

    stage = 0
    current_sl = sl_price
    peak_price = entry_price
    peak_profit_pct = 0.0
    giveback_activated = False
    giveback_sl_price: float | None = None

    partial_pnls: list[tuple[float, float]] = []   # (qty_closed, exit_price)
    trail_active_bar: int | None = None
    n = len(df)
    exit_j = n - 1

    for j in range(entry_i, n):
        bar = df.iloc[j]
        hi = float(bar["high"])
        lo = float(bar["low"])
        close_j = float(bar["close"])
        rel_j = j - entry_i   # entry'den geçen bar sayısı

        if side == "long":
            peak_price = max(peak_price, hi)
            profit_pct_now = (peak_price - entry_price) / entry_price
            peak_profit_pct = max(peak_profit_pct, profit_pct_now)

            # SL hit
            if lo <= current_sl:
                rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                partial_pnls.append((rem, current_sl * (1.0 - slip)))
                exit_j = j
                break

            # TP1
            if stage == 0 and hi >= tp1_price:
                partial_pnls.append((qty1, tp1_price * (1.0 - slip)))
                stage = 1
            # TP2
            if stage >= 1 and hi >= tp2_price:
                partial_pnls.append((qty2, tp2_price * (1.0 - slip)))
                stage = 2

            # Break-even lock
            if stage >= 1:
                current_sl = max(current_sl, entry_price)

            # Champion trail (stage >= 2)
            if stage >= CHAMPION_STAGE:
                champ_sl = peak_price * (1.0 - CHAMPION_TRAIL_PCT)
                current_sl = max(current_sl, entry_price, champ_sl)
                if trail_active_bar is None:
                    trail_active_bar = j

            # Giveback trail override
            if mode == "giveback" and peak_profit_pct >= trail_T:
                giveback_activated = True
                new_gb_sl = entry_price * (1.0 + peak_profit_pct - trail_G)
                if giveback_sl_price is None:
                    giveback_sl_price = max(entry_price, new_gb_sl)
                else:
                    giveback_sl_price = max(giveback_sl_price, new_gb_sl)
                current_sl = max(current_sl, giveback_sl_price)

            # Force-exit: trail aktive olduktan 48 bar sonra
            if trail_active_bar is not None:
                if (j - trail_active_bar) >= RUNNER_FORCE_EXIT_BARS:
                    rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                    if rem > 0:
                        partial_pnls.append((rem, close_j * (1.0 - slip)))
                    exit_j = j
                    break

        else:  # short
            peak_price = min(peak_price, lo)
            profit_pct_now = (entry_price - peak_price) / entry_price
            peak_profit_pct = max(peak_profit_pct, profit_pct_now)

            # SL hit
            if hi >= current_sl:
                rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                partial_pnls.append((rem, current_sl * (1.0 + slip)))
                exit_j = j
                break

            # TP1
            if stage == 0 and lo <= tp1_price:
                partial_pnls.append((qty1, tp1_price * (1.0 + slip)))
                stage = 1
            # TP2
            if stage >= 1 and lo <= tp2_price:
                partial_pnls.append((qty2, tp2_price * (1.0 + slip)))
                stage = 2

            # Break-even lock
            if stage >= 1:
                current_sl = min(current_sl, entry_price)

            # Champion trail (stage >= 2)
            if stage >= CHAMPION_STAGE:
                champ_sl = peak_price * (1.0 + CHAMPION_TRAIL_PCT)
                current_sl = min(current_sl, entry_price, champ_sl)
                if trail_active_bar is None:
                    trail_active_bar = j

            # Giveback trail override
            if mode == "giveback" and peak_profit_pct >= trail_T:
                giveback_activated = True
                new_gb_sl = entry_price * (1.0 - (peak_profit_pct - trail_G))
                if giveback_sl_price is None:
                    giveback_sl_price = min(entry_price, new_gb_sl)
                else:
                    giveback_sl_price = min(giveback_sl_price, new_gb_sl)
                current_sl = min(current_sl, giveback_sl_price)

            # Force-exit
            if trail_active_bar is not None:
                if (j - trail_active_bar) >= RUNNER_FORCE_EXIT_BARS:
                    rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                    if rem > 0:
                        partial_pnls.append((rem, close_j * (1.0 + slip)))
                    exit_j = j
                    break
    else:
        # Bitti, hala açık
        final_p = float(df.iloc[n - 1]["close"])
        rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
        if rem > 0:
            partial_pnls.append((rem, final_p))

    # Aggregate
    gross = 0.0
    fee_total = 0.0
    total_qty = 0.0
    weighted_exit = 0.0
    for q_c, ep in partial_pnls:
        pnl_unit = (ep - entry_price) if side == "long" else (entry_price - ep)
        gross += pnl_unit * q_c
        fee_total += (entry_price + ep) * q_c * TAKER_FEE
        total_qty += q_c
        weighted_exit += ep * q_c

    exit_price = weighted_exit / total_qty if total_qty > 0 else entry_price
    net = gross - fee_total
    r_multiple = net / (initial_R_dist * qty) if initial_R_dist > 0 else 0.0

    exit_profit_pct = (
        (exit_price - entry_price) / entry_price if side == "long"
        else (entry_price - exit_price) / entry_price
    )

    return {
        "R": r_multiple,
        "peak_profit_pct": peak_profit_pct,
        "exit_profit_pct": exit_profit_pct,
        "giveback_activated": giveback_activated,
        "holding_bars": exit_j - entry_i,
        "stage_reached": stage,
    }


# ── Cache'deki trade'ler üzerinde yeniden simülasyon ─────────────────────────

def resim_all_trades(
    champion_trades: list[dict],
    mode: str,
    trail_T: float = 0.08,
    trail_G: float = 0.03,
) -> list[dict]:
    """Champion cache'deki trade'leri yeni trail mantığıyla yeniden simüle et.

    Cache:  mode=champion_resim
    Giveback: mode=giveback_T{T}_G{G}
    """
    if mode == "champion_resim":
        cache_key = "champion_resim_pct0.10_s2"
    else:
        cache_key = f"giveback_T{trail_T:.2f}_G{trail_G:.2f}"

    cache_path = CACHE_DIR / f"trades_{cache_key}.pkl"
    if cache_path.exists():
        with cache_path.open("rb") as f:
            trades = pickle.load(f)
        print(f"  [cache] {cache_key}: n={len(trades)}")
        return trades

    print(f"  [sim]   {cache_key}: {len(champion_trades)} trade yeniden simüle ediliyor...")
    t0 = time.time()

    new_trades: list[dict] = []
    failed = 0
    missing_ohlcv = 0

    for ct in champion_trades:
        sym = ct["symbol"]
        df, idx_by_ts = get_ohlcv(sym)
        if df is None:
            missing_ohlcv += 1
            continue

        entry_ts = pd.Timestamp(ct["entry_ts"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")

        entry_i = idx_by_ts.get(entry_ts)
        if entry_i is None:
            # Yakın ts ara (15m=900s tolerans)
            candidates = [(abs((pd.Timestamp(k) - entry_ts).total_seconds()), v)
                          for k, v in idx_by_ts.items()
                          if abs((pd.Timestamp(k) - entry_ts).total_seconds()) <= 900]
            if candidates:
                entry_i = min(candidates)[1]
            else:
                failed += 1
                continue

        entry_price = float(ct["entry_price"])
        sl_price = float(ct["initial_sl"])
        side = str(ct["side"])

        if abs(entry_price - sl_price) < 1e-10:
            failed += 1
            continue

        atr_val = abs(entry_price - sl_price) * 0.5

        try:
            res = resim_trade_giveback(
                df=df,
                entry_i=entry_i,
                entry_price=entry_price,
                sl_price=sl_price,
                side=side,
                atr_val=atr_val,
                mode=mode,
                trail_T=trail_T,
                trail_G=trail_G,
            )
        except Exception:
            failed += 1
            continue

        sl_pct = abs(entry_price - sl_price) / entry_price if entry_price > 0 else 0.025

        new_trades.append({
            "entry_ts": ct["entry_ts"],
            "exit_ts": ct["entry_ts"],   # aylık bucketing için entry yeterli
            "entry_price": entry_price,
            "initial_sl": sl_price,
            "R": res["R"],
            "peak_profit_pct": res["peak_profit_pct"],
            "exit_profit_pct": res["exit_profit_pct"],
            "giveback_activated": res["giveback_activated"],
            "holding_bars": res["holding_bars"],
            "symbol": sym,
            "side": side,
            "strategy": ct["strategy"],
            "sl_pct": sl_pct,
            "conf": 0.0,
            "vol_z": 0.0,
        })

    elapsed = time.time() - t0
    print(f"    -> n={len(new_trades)}, failed={failed}, missing_ohlcv={missing_ohlcv} ({elapsed:.0f}s) (cached)")

    with cache_path.open("wb") as f:
        pickle.dump(new_trades, f)

    return new_trades


# ── Metrikler ───────────────────────────────────────────────────────────────

def to_utc(ts):
    if ts is None:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def fee_adjusted_r(trades: list[dict], extra_bps: float) -> list[dict]:
    """R'ye ek fee cost ekle (R-space)."""
    out = []
    for t in trades:
        sl_pct = t.get("sl_pct", 0.025)
        if sl_pct <= 0:
            ep = t.get("entry_price", 0)
            isl = t.get("initial_sl", 0)
            sl_pct = abs(ep - isl) / ep if ep > 0 else 0.025
        extra_r = (extra_bps / (sl_pct * 10_000.0)) if sl_pct > 0 else 0.0
        t2 = dict(t)
        t2["R"] = t["R"] - extra_r
        if "conf" not in t2:
            t2["conf"] = 0.0
        if "vol_z" not in t2:
            t2["vol_z"] = 0.0
        out.append(t2)
    return out


def compute_metrics(trades: list[dict], cfg: ProductionConfig, extra_bps: float) -> dict | None:
    adj = fee_adjusted_r(trades, extra_bps)
    adj_sorted = sorted(adj, key=lambda x: to_utc(x["entry_ts"]))

    if len(adj_sorted) < 30:
        return None

    start = to_utc(adj_sorted[0]["entry_ts"])
    end = to_utc(adj_sorted[-1]["entry_ts"])

    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        me_y = cy + (1 if cm == 12 else 0)
        me_m = (cm % 12) + 1
        me = datetime(me_y, me_m, 1, tzinfo=timezone.utc)
        months.append((ms, me))
        cy, cm = me_y, me_m

    rets = []
    equity = cfg.initial_capital
    for ms, me in months:
        m_tr = [t for t in adj_sorted if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 5:
            continue
        r = production_replay(m_tr, cfg.with_overrides(initial_capital=equity))
        if r is None:
            continue
        rets.append(r.total_return * 100)
        equity = r.final_equity if r.final_equity > 0 else equity

    if not rets:
        return None

    r_full = production_replay(adj_sorted, cfg)
    if r_full is None:
        return None

    rs = [t["R"] for t in adj_sorted]
    winners = [r for r in rs if r > 0]
    losers = [r for r in rs if r <= 0]

    # Giveback metriği
    winning_trades = [t for t in adj_sorted if t["R"] > 0]
    giveback_vals = []
    activated_gb_vals = []
    for t in winning_trades:
        pp = t.get("peak_profit_pct", 0.0)
        ep = t.get("exit_profit_pct", 0.0)
        gb = max(0.0, pp - ep)
        giveback_vals.append(gb * 100)
        if t.get("giveback_activated", False):
            activated_gb_vals.append(gb * 100)

    # peak_profit_pct >= T olan trade'ler (giveback aktive edilen potansiyel)
    n_big = sum(1 for t in adj_sorted if t.get("peak_profit_pct", 0.0) >= 0.06)

    return {
        "n": len(adj_sorted),
        "n_months": len(rets),
        "monthly_mean_roi": mean(rets),
        "monthly_min_roi": min(rets),
        "monthly_neg": sum(1 for x in rets if x < 0),
        "max_dd": r_full.max_drawdown * 100,
        "total_return": r_full.total_return * 100,
        "mean_r": mean(rs) if rs else 0.0,
        "win_pct": len(winners) / len(rs) * 100 if rs else 0.0,
        "avg_win_r": mean(winners) if winners else 0.0,
        "avg_loss_r": mean(losers) if losers else 0.0,
        "avg_hold_bars": mean([t.get("holding_bars", 0) for t in adj_sorted if t.get("holding_bars", 0) > 0]) if any(t.get("holding_bars", 0) > 0 for t in adj_sorted) else 0.0,
        "avg_giveback_pct": mean(giveback_vals) if giveback_vals else 0.0,
        "avg_giveback_activated_pct": mean(activated_gb_vals) if activated_gb_vals else 0.0,
        "n_activated": len(activated_gb_vals),
        "n_big_movers": n_big,
        "extra_bps": extra_bps,
    }


# ── Ana döngü ────────────────────────────────────────────────────────────────

def main():
    print("=" * 165)
    print("GIVEBACK TRAIL GRID — Geç-Aktive Kâr Koruma Trail Backtest")
    print(f"Kaynak: champion cache {CHAMPION_CACHE.name} ({394615} trades)")
    print(f"Champion: peak*(1-0.10) trail, stage>=2 | Giveback: peak_profit%>=T → SL=peak-G (ratchet)")
    print(f"T grid: {[f'{v:.0%}' for v in T_VALUES]}")
    print(f"G grid: {[f'{v:.0%}' for v in G_VALUES]}")
    print(f"Fee: {TAKER_FEE*10000:.1f}bps taker + {SLIP_BPS:.0f}bps slip + extra 55/100bps")
    print("=" * 165)

    # Champion yaml config
    base_cfg = ProductionConfig.from_yaml(str(CHAMPION_YAML)).with_overrides(
        pyramid_enabled=False,
        pyramid_triggers=(),
        pyramid_sizes=(),
        fee_bps_per_trade=0.0,
        sl_pct_min=0.0,
        conf_min=0.0,
    )
    print(f"\n[config] risk_pct={base_cfg.risk_pct} initial_capital={base_cfg.initial_capital}")

    # Cache'den champion trade'leri yükle
    print(f"\n[Phase 0] Champion cache yükleniyor...")
    with CHAMPION_CACHE.open("rb") as f:
        champion_cache_trades = pickle.load(f)
    print(f"  -> {len(champion_cache_trades)} trade yüklendi")

    # ── Phase 1: OHLCV önbelleği ──
    print(f"\n[Phase 1] OHLCV önbellek yükleniyor ({len(SYMBOLS)} sembol)...")
    for sym in SYMBOLS:
        df, idx = get_ohlcv(sym)
        if df is not None:
            print(f"  {sym}: {len(df)} bars")
        else:
            print(f"  {sym}: MISSING")

    # ── Phase 2: Simülasyonlar ──
    print(f"\n[Phase 2] Simülasyonlar (cache yoksa full re-sim)...")

    # Champion re-sim (referans — cache'deki R ile karşılaştır)
    print("\nChampion re-sim (parity check):")
    champion_resim = resim_all_trades(champion_cache_trades, mode="champion_resim")

    # Giveback grid
    grid_trades: dict[tuple, list[dict]] = {}
    total_cells = len(T_VALUES) * len(G_VALUES)
    done = 0
    for T in T_VALUES:
        for G in G_VALUES:
            print(f"\nGiveback T={T:.0%} G={G:.0%} ({done+1}/{total_cells}):")
            trades = resim_all_trades(champion_cache_trades, mode="giveback", trail_T=T, trail_G=G)
            grid_trades[(T, G)] = trades
            done += 1

    # ── Phase 3: Parity kontrol ──
    print("\n[Phase 3] Parity kontrol (champion cache vs re-sim)...")
    cache_rs = [t["R"] for t in champion_cache_trades]
    resim_rs = [t["R"] for t in champion_resim]
    cache_mean = mean(cache_rs)
    resim_mean = mean(resim_rs) if resim_rs else 0.0
    cache_win = sum(1 for r in cache_rs if r > 0) / len(cache_rs) * 100
    resim_win = sum(1 for r in resim_rs if r > 0) / len(resim_rs) * 100 if resim_rs else 0.0
    parity_diff = abs(cache_mean - resim_mean) / cache_mean * 100 if cache_mean != 0 else 0.0
    print(f"  Cache:  mean_R={cache_mean:.4f}, win={cache_win:.1f}%")
    print(f"  Re-sim: mean_R={resim_mean:.4f}, win={resim_win:.1f}%")
    print(f"  Parity diff: {parity_diff:.1f}% ({'OK (<5%)' if parity_diff < 5 else 'WARN (>5%)'})")

    # ── Phase 4: Metrikler ──
    print("\n\n" + "=" * 165)
    print("[Phase 4] Metrik tablosu — 55bps ve 100bps")
    print("=" * 165)

    champion_m: dict | None = None
    all_results: list[dict] = []

    for cost_label, extra_bps in [("55bps", EXTRA_BPS_BASELINE), ("100bps", EXTRA_BPS_STRESS)]:
        print(f"\n{'─'*165}")
        print(f"MALIYET: {cost_label}")
        print(f"{'─'*165}")
        hdr = (
            f"  {'Label':<22} {'n':>7} {'mon_roi':>8} {'mon_min':>8} "
            f"{'neg':>4} {'MaxDD':>7} {'meanR':>7} {'win%':>6} {'hold':>5} "
            f"{'gb_all%':>8} {'gb_actv%':>9} {'n_actv':>7} {'n_big':>7}"
        )
        print(hdr)
        print("  " + "-" * 140)

        # Champion re-sim
        m = compute_metrics(champion_resim, base_cfg, extra_bps)
        if m is not None:
            m["label"] = "CHAMPION"
            m["T"] = None
            m["G"] = None
            m["cost_label"] = cost_label
            if extra_bps == EXTRA_BPS_BASELINE:
                champion_m = m
            all_results.append(m)
            _print_row(m, is_champion=True)

        # Grid
        for T in T_VALUES:
            for G in G_VALUES:
                trades = grid_trades[(T, G)]
                m = compute_metrics(trades, base_cfg, extra_bps)
                if m is None:
                    print(f"  T={T:.0%} G={G:.0%}: INSUFFICIENT DATA")
                    continue
                label = f"T={T:.0%} G={G:.0%}"
                m["label"] = label
                m["T"] = T
                m["G"] = G
                m["cost_label"] = cost_label
                all_results.append(m)
                _print_row(m, champion=champion_m if extra_bps == EXTRA_BPS_BASELINE else None)

    # ── Phase 5: Özet Karar ──
    print("\n\n" + "=" * 165)
    print("OZET KARAR")
    print("=" * 165)

    if champion_m is None:
        print("HATA: Champion metrikleri hesaplanamadi.")
        return

    print(f"\nCHAMPION re-sim (55bps):")
    print(f"  monthly_ROI={champion_m['monthly_mean_roi']:+.2f}%  "
          f"MaxDD={champion_m['max_dd']:+.1f}%  "
          f"meanR={champion_m['mean_r']:+.3f}  "
          f"win={champion_m['win_pct']:.1f}%  "
          f"giveback(all)={champion_m['avg_giveback_pct']:.2f}%  "
          f"big_movers={champion_m['n_big_movers']}")

    challengers_55 = [m for m in all_results if m["label"] != "CHAMPION" and m["cost_label"] == "55bps"]

    print(f"\n{'─'*130}")
    print("CHALLENGER KARSILASTIRMA vs CHAMPION (55bps):")
    print(f"  {'Label':<20} {'ROI':>9} {'ROI_d':>8} {'DD':>8} {'DD_d':>7} "
          f"{'meanR':>7} {'R_d':>7} {'win%':>6} {'win_d':>6} "
          f"{'gb_all%':>8} {'gb_a%':>7} {'n_act':>7}  {'VERDICT':>12}")
    print("  " + "-" * 128)

    gate_pass = []
    for m in challengers_55:
        roi_d = m["monthly_mean_roi"] - champion_m["monthly_mean_roi"]
        dd_d = m["max_dd"] - champion_m["max_dd"]
        r_d = m["mean_r"] - champion_m["mean_r"]
        win_d = m["win_pct"] - champion_m["win_pct"]

        if roi_d >= 0 and dd_d <= 0:
            verdict = "SAFE"
            gate_pass.append(m)
        elif roi_d >= -0.5 and dd_d <= 2.0:
            verdict = "ACCEPTABLE"
        else:
            verdict = "RISKY"

        print(
            f"  {m['label']:<20} {m['monthly_mean_roi']:>+9.2f}% {roi_d:>+8.2f}pp "
            f"{m['max_dd']:>+8.1f}% {dd_d:>+7.1f}pp "
            f"{m['mean_r']:>+7.3f} {r_d:>+7.3f} "
            f"{m['win_pct']:>6.1f}% {win_d:>+6.1f}pp "
            f"{m['avg_giveback_pct']:>8.2f}% {m['avg_giveback_activated_pct']:>7.2f}% "
            f"{m['n_activated']:>7}  [{verdict}]"
        )

    print(f"\n{'─'*130}")
    print("EN IYI CHALLENGER (55bps, ROI bazli):")
    if challengers_55:
        best_roi = max(challengers_55, key=lambda x: x["monthly_mean_roi"])
        roi_d = best_roi["monthly_mean_roi"] - champion_m["monthly_mean_roi"]
        dd_d = best_roi["max_dd"] - champion_m["max_dd"]
        gb_d = best_roi["avg_giveback_pct"] - champion_m["avg_giveback_pct"]
        print(f"  {best_roi['label']}: ROI={best_roi['monthly_mean_roi']:+.2f}% ({roi_d:+.2f}pp), "
              f"DD={best_roi['max_dd']:+.1f}% ({dd_d:+.1f}pp), "
              f"meanR={best_roi['mean_r']:+.3f}, "
              f"giveback={best_roi['avg_giveback_pct']:.2f}% ({gb_d:+.2f}pp vs champ)")

    print(f"\n{'─'*130}")
    print("GIVEBACK METRIGI ANALIZI (kazanan trade'lerde acik kar geri verilmesi):")
    print(f"  Champion giveback (tum kazananlar): {champion_m['avg_giveback_pct']:.2f}%  "
          f"activated: {champion_m['avg_giveback_activated_pct']:.2f}%")
    for m in challengers_55:
        gb_d = m["avg_giveback_pct"] - champion_m["avg_giveback_pct"]
        print(f"  {m['label']:<20}: gb_all={m['avg_giveback_pct']:.2f}% ({gb_d:+.2f}pp), "
              f"gb_actv={m['avg_giveback_activated_pct']:.2f}%, "
              f"n_aktive={m['n_activated']}")

    print(f"\n{'─'*130}")
    print("GATE SONUCU (ROI>=champion AND DD<=champion, 55bps):")
    if gate_pass:
        print(f"  GECEN HUCRELER: {[m['label'] for m in gate_pass]}")
        best_gate = max(gate_pass, key=lambda x: x["monthly_mean_roi"])
        gb_d = best_gate["avg_giveback_pct"] - champion_m["avg_giveback_pct"]
        print(f"  EN IYI GATE: {best_gate['label']}")
        print(f"    ROI={best_gate['monthly_mean_roi']:+.2f}%, DD={best_gate['max_dd']:+.1f}%, "
              f"meanR={best_gate['mean_r']:+.3f}, giveback={best_gate['avg_giveback_pct']:.2f}% "
              f"({gb_d:+.2f}pp vs champion)")
    else:
        print("  HICBIR HUCRE GATE'I GECEMEDI — Champion korunur.")

    # 100bps cross-check
    print(f"\n{'─'*130}")
    print("100BPS STRESS CROSS-CHECK (gate gecenler):")
    if gate_pass:
        champ_100 = next((m for m in all_results if m["label"] == "CHAMPION" and m["cost_label"] == "100bps"), None)
        for gm in gate_pass:
            gm_100 = next((m for m in all_results if m["label"] == gm["label"] and m["cost_label"] == "100bps"), None)
            if champ_100 and gm_100:
                roi_d = gm_100["monthly_mean_roi"] - champ_100["monthly_mean_roi"]
                dd_d = gm_100["max_dd"] - champ_100["max_dd"]
                status = "OK" if roi_d >= 0 and dd_d <= 0 else "WARN"
                print(f"  {gm['label']:<20}: ROI={gm_100['monthly_mean_roi']:+.2f}% ({roi_d:+.2f}pp), "
                      f"DD={gm_100['max_dd']:+.1f}% ({dd_d:+.1f}pp)  [{status}]")

    print("\n[Done]")


def _print_row(m: dict, champion: dict | None = None, is_champion: bool = False):
    tag = " <-- CHAMPION" if is_champion else ""
    if champion and not is_champion:
        roi_d = m["monthly_mean_roi"] - champion["monthly_mean_roi"]
        dd_d = m["max_dd"] - champion["max_dd"]
        if roi_d >= 0 and dd_d <= 0:
            tag = " [SAFE]"
        elif roi_d >= -0.5 and dd_d <= 2.0:
            tag = " [ACCEPT]"
        else:
            tag = " [RISKY]"
    print(
        f"  {m['label']:<22} "
        f"n={m['n']:>7} "
        f"mon={m['monthly_mean_roi']:>+7.2f}% "
        f"min={m['monthly_min_roi']:>+6.1f}% "
        f"neg={m['monthly_neg']:>3} "
        f"DD={m['max_dd']:>+6.1f}% "
        f"R={m['mean_r']:>+6.3f} "
        f"win={m['win_pct']:>5.1f}% "
        f"hold={m['avg_hold_bars']:>4.0f}b "
        f"gb={m['avg_giveback_pct']:>5.2f}% "
        f"gba={m['avg_giveback_activated_pct']:>5.2f}% "
        f"nact={m['n_activated']:>6} "
        f"nbig={m['n_big_movers']:>6}"
        f"{tag}"
    )


if __name__ == "__main__":
    main()
