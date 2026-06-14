"""Surgical Trail Grid — BE-Kilidi + ATR-Trail + Kombo Backtest.

HIPOTEZ (2026-06-01):
  Champion: trail_pct=0.10, stage=2 (TP2 sonrası peak*(1-0.10)).
  Önceki testler: uniform sıkma + giveback = edge düştü (mean_R ~1.89 champion).
  Bu tur: CERRAHİ iki yaklaşım + kombo.

VARYANTLAR:
  1. BE-KİLİDİ (izole): mark +1R (TP1) geçince SL_tabanı = entry.
     Trail gerisi champion ile AYNI (%10, TP2 sonrası).
     Kâr->zarar felaketi engellemeli; runner değişmemeli.

  2. ATR-TRAIL: sabit %10 yerine peak - N*ATR14 (15m, EWM).
     N ∈ {2.0, 3.0, 4.0}. Aktivasyon champion gibi TP2 sonrası.
     Sembol volatilitesine otomatik adapte.

  3. KOMBO: BE-kilidi + ATR-trail (en iyi N).

METRİKLER:
  mean_R_after_fees, MaxDD, monthly_ROI, win%,
  KÂR→ZARAR ORANI (peak>=0.5R p/t AND exit<0),
  ortalama giveback (peak->exit, kazananlarda).
  55bps + 100bps.

KAYNAK:
  Champion cache: data/_trail_pct_cache/trades_pct0.100_stage2.pkl
  Giveback champion re-sim: data/_giveback_trail_cache/trades_champion_resim_pct0.10_s2.pkl
  (OHLCV eşlemesi + parity %0 doğrulandı)

Çalıştır: .venv/bin/python scripts/surgical_trail_grid.py
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

import numpy as np
import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.run_real_backtest import _load_symbol_ohlcv

# ── Sabitler ────────────────────────────────────────────────────────────────

CHAMPION_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
CHAMPION_CACHE = ROOT / "data" / "_trail_pct_cache" / "trades_pct0.100_stage2.pkl"
# Giveback harness champion re-sim — OHLCV eşlemeli, parity %0
CHAMPION_RESIM_CACHE = ROOT / "data" / "_giveback_trail_cache" / "trades_champion_resim_pct0.10_s2.pkl"
CACHE_DIR = ROOT / "data" / "_surgical_trail_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT",
]

# Champion parametreleri
CHAMPION_TRAIL_PCT = 0.10
CHAMPION_STAGE = 2     # TP2 sonrası trail aktive
TP1_R = 1.0
TP2_R = 1.5
TP1_CLOSE_PCT = 0.25
TP2_CLOSE_PCT = 0.25
RUNNER_FORCE_EXIT_BARS = 48   # 15m x 48 = 12 saat

TAKER_FEE = 0.00075
SLIP_BPS = 5.0
EXTRA_BPS_BASELINE = 55.0
EXTRA_BPS_STRESS = 100.0

ATR_PERIOD = 14        # 15m ATR14 (EWM)
ATR_N_VALUES = [2.0, 3.0, 4.0]

# Kâr→zarar eşiği: peak_profit_pct >= 0.5 * sl_pct (per-trade 0.5R eşdeğeri)
PZ_THRESHOLD_R = 0.5   # bu eşikte peak görülüp R<0 ise "kâr->zarar" sayılır


# ── OHLCV + ATR önbelleği ────────────────────────────────────────────────────

_OHLCV_CACHE: dict[str, tuple] = {}  # sym -> (df, idx_by_ts, atr14_arr)


def get_ohlcv_atr(sym: str):
    """OHLCV, ts→index map ve ATR14 dizisini döndür (lazy load)."""
    if sym not in _OHLCV_CACHE:
        df = _load_symbol_ohlcv(sym, tf="15m")
        if df is None or df.empty:
            _OHLCV_CACHE[sym] = (None, {}, None)
            return None, {}, None
        df = df.sort_values("ts").reset_index(drop=True)
        idx_by_ts = {pd.Timestamp(ts): i for i, ts in enumerate(df["ts"])}

        # ATR14 (EWM true range)
        hi = df["high"].values.astype(float)
        lo = df["low"].values.astype(float)
        cl = df["close"].values.astype(float)
        prev_cl = np.roll(cl, 1)
        prev_cl[0] = cl[0]
        tr = np.maximum(hi - lo, np.maximum(np.abs(hi - prev_cl), np.abs(lo - prev_cl)))
        atr14 = pd.Series(tr).ewm(span=ATR_PERIOD, adjust=False).mean().values

        _OHLCV_CACHE[sym] = (df, idx_by_ts, atr14)
    return _OHLCV_CACHE[sym]


# ── Tek trade yeniden simülatörü ─────────────────────────────────────────────

def resim_trade(
    df,
    atr14_arr: np.ndarray,
    entry_i: int,
    entry_price: float,
    sl_price: float,
    side: str,
    mode: str,        # "champion" | "be_lock" | "atr_trail" | "combo"
    atr_N: float = 3.0,
    max_bars: int | None = None,  # Hard cap: entry_i + max_bars'da zorla kapat
) -> dict:
    """Entry bar'dan itibaren re-sim.

    champion: peak*(1-0.10) trail, TP2 sonrası. BE-kilidi TP1 sonrası (engine parity).
    be_lock:  champion AYNI + TP1 geçilince SL_tabanı = entry (izole eklenti).
    atr_trail: champion trail yerine peak - N*ATR14. TP1 sonrası BE-kilidi yok.
    combo:     be_lock + atr_trail birlikte.

    Döndürür: R, peak_profit_pct, exit_profit_pct, holding_bars, pz_flag (kâr->zarar).
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
    trail_active_bar = None
    partial_pnls: list[tuple[float, float]] = []
    n = len(df)
    exit_j = n - 1

    # Hard cap: exit_ts'den hesaplanan bar sayısı + tolerans
    if max_bars is not None:
        n = min(n, entry_i + max_bars)

    for j in range(entry_i, n):
        bar = df.iloc[j]
        hi = float(bar["high"])
        lo = float(bar["low"])
        close_j = float(bar["close"])

        # ATR bu bar için (forward-safe: entry bar ATR kullanılabilir)
        atr_j = float(atr14_arr[j]) if atr14_arr is not None and j < len(atr14_arr) else initial_R_dist * 0.5
        if atr_j <= 0:
            atr_j = initial_R_dist * 0.5

        if side == "long":
            peak_price = max(peak_price, hi)
            pp = (peak_price - entry_price) / entry_price
            peak_profit_pct = max(peak_profit_pct, pp)

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

            # BE-kilidi: TP1 sonrası SL tabani = entry
            if mode in ("be_lock", "combo") and stage >= 1:
                current_sl = max(current_sl, entry_price)

            # Standart engine BE-kilidi (champion parity): stage>=CHAMPION_STAGE iken
            if mode == "champion" and stage >= CHAMPION_STAGE:
                current_sl = max(current_sl, entry_price)

            # Trail
            if stage >= CHAMPION_STAGE:
                if mode in ("champion", "be_lock"):
                    trail_sl = peak_price * (1.0 - CHAMPION_TRAIL_PCT)
                    current_sl = max(current_sl, entry_price, trail_sl)
                elif mode in ("atr_trail", "combo"):
                    trail_sl = peak_price - atr_N * atr_j
                    current_sl = max(current_sl, entry_price if mode == "combo" else sl_price, trail_sl)
                if trail_active_bar is None:
                    trail_active_bar = j

            # Force-exit (48 bar sonra)
            if trail_active_bar is not None:
                if (j - trail_active_bar) >= RUNNER_FORCE_EXIT_BARS:
                    rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                    if rem > 0:
                        partial_pnls.append((rem, close_j * (1.0 - slip)))
                    exit_j = j
                    break

        else:  # short
            peak_price = min(peak_price, lo)
            pp = (entry_price - peak_price) / entry_price
            peak_profit_pct = max(peak_profit_pct, pp)

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

            # BE-kilidi
            if mode in ("be_lock", "combo") and stage >= 1:
                current_sl = min(current_sl, entry_price)

            if mode == "champion" and stage >= CHAMPION_STAGE:
                current_sl = min(current_sl, entry_price)

            # Trail
            if stage >= CHAMPION_STAGE:
                if mode in ("champion", "be_lock"):
                    trail_sl = peak_price * (1.0 + CHAMPION_TRAIL_PCT)
                    current_sl = min(current_sl, entry_price, trail_sl)
                elif mode in ("atr_trail", "combo"):
                    trail_sl = peak_price + atr_N * atr_j
                    current_sl = min(current_sl, entry_price if mode == "combo" else sl_price, trail_sl)
                if trail_active_bar is None:
                    trail_active_bar = j

            # Force-exit
            if trail_active_bar is not None:
                if (j - trail_active_bar) >= RUNNER_FORCE_EXIT_BARS:
                    rem = qty - qty1 * (1 if stage >= 1 else 0) - qty2 * (1 if stage >= 2 else 0)
                    if rem > 0:
                        partial_pnls.append((rem, close_j * (1.0 + slip)))
                    exit_j = j
                    break
    else:
        # Veri bitti, hala açık
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

    sl_pct = initial_R_dist / entry_price if entry_price > 0 else 0.025
    pz_flag = (peak_profit_pct >= PZ_THRESHOLD_R * sl_pct) and (r_multiple < 0)

    return {
        "R": r_multiple,
        "peak_profit_pct": peak_profit_pct,
        "exit_profit_pct": exit_profit_pct,
        "holding_bars": exit_j - entry_i,
        "pz_flag": pz_flag,
        "stage_reached": stage,
    }


# ── Tüm trade'leri re-sim et ─────────────────────────────────────────────────

def resim_all(
    champion_trades: list[dict],
    mode: str,
    atr_N: float = 3.0,
) -> list[dict]:
    """Champion cache trade'lerini verilen mode ile yeniden simüle et."""
    if mode == "champion":
        cache_key = "champ_resim"
    elif mode == "be_lock":
        cache_key = "be_lock"
    elif mode == "atr_trail":
        cache_key = f"atr_N{atr_N:.1f}"
    else:  # combo
        cache_key = f"combo_N{atr_N:.1f}"

    cache_path = CACHE_DIR / f"trades_{cache_key}.pkl"
    if cache_path.exists():
        with cache_path.open("rb") as f:
            trades = pickle.load(f)
        print(f"  [cache] {cache_key}: n={len(trades)}")
        return trades

    print(f"  [sim]   {cache_key}: {len(champion_trades)} trade re-sim...")
    t0 = time.time()

    new_trades: list[dict] = []
    failed = 0
    missing_ohlcv = 0

    for ct in champion_trades:
        sym = ct["symbol"]
        df, idx_by_ts, atr14_arr = get_ohlcv_atr(sym)
        if df is None:
            missing_ohlcv += 1
            continue

        entry_ts = pd.Timestamp(ct["entry_ts"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")

        entry_i = idx_by_ts.get(entry_ts)
        if entry_i is None:
            # 900sn tolerans
            candidates = [
                (abs((pd.Timestamp(k) - entry_ts).total_seconds()), v)
                for k, v in idx_by_ts.items()
                if abs((pd.Timestamp(k) - entry_ts).total_seconds()) <= 900
            ]
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

        # exit_ts'den max_bars hesapla — parity için hard cap
        # +10 tolerans (OHLCV timestamp hizalaması için)
        exit_ts_raw = ct.get("exit_ts")
        max_bars_val = None
        if exit_ts_raw is not None:
            try:
                exit_ts_pd = pd.Timestamp(exit_ts_raw)
                entry_ts_pd = pd.Timestamp(ct["entry_ts"])
                if exit_ts_pd.tzinfo is None:
                    exit_ts_pd = exit_ts_pd.tz_localize("UTC")
                if entry_ts_pd.tzinfo is None:
                    entry_ts_pd = entry_ts_pd.tz_localize("UTC")
                diff_bars = max(1, int((exit_ts_pd - entry_ts_pd).total_seconds() / 900))
                max_bars_val = diff_bars + 10  # +10 tolerans
            except Exception:
                max_bars_val = None

        try:
            res = resim_trade(
                df=df,
                atr14_arr=atr14_arr,
                entry_i=entry_i,
                entry_price=entry_price,
                sl_price=sl_price,
                side=side,
                mode=mode,
                atr_N=atr_N,
                max_bars=max_bars_val,
            )
        except Exception:
            failed += 1
            continue

        sl_pct = abs(entry_price - sl_price) / entry_price if entry_price > 0 else 0.025

        new_trades.append({
            "entry_ts": ct["entry_ts"],
            "exit_ts": ct["entry_ts"],
            "entry_price": entry_price,
            "initial_sl": sl_price,
            "R": res["R"],
            "peak_profit_pct": res["peak_profit_pct"],
            "exit_profit_pct": res["exit_profit_pct"],
            "pz_flag": res["pz_flag"],
            "holding_bars": res["holding_bars"],
            "symbol": sym,
            "side": side,
            "strategy": ct["strategy"],
            "sl_pct": sl_pct,
            "conf": 0.0,
            "vol_z": 0.0,
        })

    elapsed = time.time() - t0
    print(f"    -> n={len(new_trades)}, failed={failed}, missing={missing_ohlcv} ({elapsed:.0f}s) (cached)")

    with cache_path.open("wb") as f:
        pickle.dump(new_trades, f)

    return new_trades


# ── Metrikler ────────────────────────────────────────────────────────────────

def to_utc(ts):
    if ts is None:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def fee_adjusted_r(trades: list[dict], extra_bps: float) -> list[dict]:
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
        out.append(t2)
    return out


def compute_metrics(
    trades: list[dict],
    cfg: ProductionConfig,
    extra_bps: float,
) -> dict | None:
    adj = fee_adjusted_r(trades, extra_bps)
    adj = sorted(adj, key=lambda x: to_utc(x["entry_ts"]))

    if len(adj) < 30:
        return None

    start = to_utc(adj[0]["entry_ts"])
    end = to_utc(adj[-1]["entry_ts"])

    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        ny = cy + (1 if cm == 12 else 0)
        nm = (cm % 12) + 1
        me = datetime(ny, nm, 1, tzinfo=timezone.utc)
        months.append((ms, me))
        cy, cm = ny, nm

    rets = []
    equity = cfg.initial_capital
    for ms, me in months:
        m_tr = [t for t in adj if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 5:
            continue
        r = production_replay(m_tr, cfg.with_overrides(initial_capital=equity))
        if r is None:
            continue
        rets.append(r.total_return * 100)
        equity = r.final_equity if r.final_equity > 0 else equity

    if not rets:
        return None

    r_full = production_replay(adj, cfg)
    if r_full is None:
        return None

    rs = [t["R"] for t in adj]
    winners = [t for t in adj if t["R"] > 0]
    losers = [t for t in adj if t["R"] <= 0]

    # Kâr->zarar (fee-adjusted R üzerinden)
    pz_count = sum(1 for t in adj if t.get("pz_flag", False))

    # Giveback (kazanan trade'lerde peak->exit açık kâr geri verilen)
    gb_vals = [max(0.0, t.get("peak_profit_pct", 0.0) - t.get("exit_profit_pct", 0.0)) for t in winners]

    return {
        "n": len(adj),
        "n_months": len(rets),
        "monthly_mean_roi": mean(rets),
        "monthly_min_roi": min(rets),
        "monthly_neg": sum(1 for x in rets if x < 0),
        "max_dd": r_full.max_drawdown * 100,
        "total_return": r_full.total_return * 100,
        "mean_r": mean(rs) if rs else 0.0,
        "win_pct": len(winners) / len(adj) * 100 if adj else 0.0,
        "avg_win_r": mean([t["R"] for t in winners]) if winners else 0.0,
        "avg_loss_r": mean([t["R"] for t in losers]) if losers else 0.0,
        "avg_hold_bars": mean([t.get("holding_bars", 0) for t in adj if t.get("holding_bars", 0) > 0]) if any(t.get("holding_bars", 0) > 0 for t in adj) else 0.0,
        "pz_count": pz_count,
        "pz_rate": pz_count / len(adj) * 100 if adj else 0.0,
        "avg_giveback_pct": mean(gb_vals) * 100 if gb_vals else 0.0,
        "extra_bps": extra_bps,
    }


# ── Ana döngü ────────────────────────────────────────────────────────────────

def main():
    print("=" * 175)
    print("SURGICAL TRAIL GRID — BE-Kilidi + ATR-Trail + Kombo")
    print(f"Champion: trail_pct=0.10, stage=2 (TP2 sonrası)")
    print(f"Varyantlar: be_lock | atr_trail(N={ATR_N_VALUES}) | combo(N=best)")
    print(f"Semboller: {len(SYMBOLS)} | 4 strateji | 2021-2026 | 394k trade")
    print(f"Fee: {TAKER_FEE*10000:.1f}bps taker + {SLIP_BPS:.0f}bps slip + extra 55/100bps")
    print(f"Kâr->zarar eşiği: peak_profit_pct >= {PZ_THRESHOLD_R}R(per-trade) AND R<0")
    print("=" * 175)

    base_cfg = ProductionConfig.from_yaml(str(CHAMPION_YAML)).with_overrides(
        pyramid_enabled=False,
        pyramid_triggers=(),
        pyramid_sizes=(),
        fee_bps_per_trade=0.0,
        sl_pct_min=0.0,
        conf_min=0.0,
    )
    print(f"\n[config] risk_pct={base_cfg.risk_pct} initial_capital={base_cfg.initial_capital}")

    # Champion cache yükle
    print(f"\n[Phase 0] Champion cache yükleniyor...")
    with CHAMPION_CACHE.open("rb") as f:
        champion_cache = pickle.load(f)
    print(f"  -> {len(champion_cache)} trade")

    # OHLCV + ATR ön yükleme
    print(f"\n[Phase 1] OHLCV + ATR14 önbellekleniyor ({len(SYMBOLS)} sembol)...")
    for sym in SYMBOLS:
        df, idx, atr14 = get_ohlcv_atr(sym)
        if df is not None:
            print(f"  {sym}: {len(df)} bars, atr14[son]={atr14[-1]:.4f}")
        else:
            print(f"  {sym}: MISSING")

    # Simülasyonlar
    print(f"\n[Phase 2] Re-sim (cache yoksa full OHLCV)...")

    # Champion re-sim (referans)
    print("\nChampion re-sim:")
    champ_resim = resim_all(champion_cache, mode="champion")

    # BE-kilidi
    print("\nBE-kilidi re-sim:")
    be_trades = resim_all(champion_cache, mode="be_lock")

    # ATR-trail grid
    atr_trades: dict[float, list[dict]] = {}
    for N in ATR_N_VALUES:
        print(f"\nATR-trail N={N:.1f}:")
        atr_trades[N] = resim_all(champion_cache, mode="atr_trail", atr_N=N)

    # Kombo: her N ile
    combo_trades: dict[float, list[dict]] = {}
    for N in ATR_N_VALUES:
        print(f"\nKombo (BE+ATR) N={N:.1f}:")
        combo_trades[N] = resim_all(champion_cache, mode="combo", atr_N=N)

    # Parity kontrol
    print("\n[Phase 3] Parity (champion_cache vs champion re-sim):")
    cache_rs = [t["R"] for t in champion_cache]
    resim_rs = [t["R"] for t in champ_resim]
    c_mean = mean(cache_rs)
    r_mean = mean(resim_rs) if resim_rs else 0.0
    diff_pct = abs(c_mean - r_mean) / abs(c_mean) * 100 if c_mean != 0 else 0.0
    print(f"  Cache:  mean_R={c_mean:.4f}, win%={sum(1 for r in cache_rs if r>0)/len(cache_rs)*100:.1f}%")
    print(f"  Re-sim: mean_R={r_mean:.4f}, win%={sum(1 for r in resim_rs if r>0)/len(resim_rs)*100:.1f}%")
    print(f"  Parity diff: {diff_pct:.2f}% ({'OK (<5%)' if diff_pct < 5 else 'WARN (>5%)'})")

    # Metrik tablosu
    print("\n\n" + "=" * 175)
    print("[Phase 4] METRİK TABLOSU")
    print("=" * 175)

    # Hücreler: (label, trades, {atr_N veya None})
    cells = [("champion", champ_resim, None)]
    cells.append(("be_lock", be_trades, None))
    for N in ATR_N_VALUES:
        cells.append((f"atr_N{N:.1f}", atr_trades[N], N))
    for N in ATR_N_VALUES:
        cells.append((f"combo_N{N:.1f}", combo_trades[N], N))

    champion_m55: dict | None = None
    all_results: list[dict] = []

    for cost_label, extra_bps in [("55bps", EXTRA_BPS_BASELINE), ("100bps", EXTRA_BPS_STRESS)]:
        print(f"\n{'─'*175}")
        print(f"MALIYET: {cost_label}")
        hdr = (
            f"  {'Varyant':<18} {'n':>7} {'mon_roi':>8} {'mon_min':>8} "
            f"{'neg':>4} {'MaxDD':>7} {'meanR':>7} {'win%':>6} "
            f"{'P->Z%':>7} {'P->Z_n':>7} {'gb%':>7} {'hold':>5}"
        )
        print(hdr)
        print("  " + "-" * 155)

        for label, trades, _ in cells:
            m = compute_metrics(trades, base_cfg, extra_bps)
            if m is None:
                print(f"  {label:<18} INSUFFICIENT DATA")
                continue
            m["label"] = label
            m["cost_label"] = cost_label
            all_results.append(m)

            if label == "champion" and extra_bps == EXTRA_BPS_BASELINE:
                champion_m55 = m

            tag = ""
            if label == "champion":
                tag = " <-- CHAMPION"
            elif champion_m55 and extra_bps == EXTRA_BPS_BASELINE:
                roi_d = m["monthly_mean_roi"] - champion_m55["monthly_mean_roi"]
                dd_d = m["max_dd"] - champion_m55["max_dd"]
                r_d = m["mean_r"] - champion_m55["mean_r"]
                pz_d = m["pz_rate"] - champion_m55["pz_rate"]
                if roi_d >= 0 and dd_d <= 0:
                    tag = f" [SAFE roi{roi_d:+.2f} dd{dd_d:+.1f} R{r_d:+.3f} pz{pz_d:+.2f}pp]"
                elif roi_d >= -0.5 and abs(r_d) < 0.10 and pz_d < 0:
                    tag = f" [ACCEPT roi{roi_d:+.2f} dd{dd_d:+.1f} R{r_d:+.3f} pz{pz_d:+.2f}pp]"
                else:
                    tag = f" [RISKY roi{roi_d:+.2f} dd{dd_d:+.1f} R{r_d:+.3f} pz{pz_d:+.2f}pp]"

            print(
                f"  {label:<18} "
                f"n={m['n']:>7} "
                f"mon={m['monthly_mean_roi']:>+7.2f}% "
                f"min={m['monthly_min_roi']:>+6.1f}% "
                f"neg={m['monthly_neg']:>3} "
                f"DD={m['max_dd']:>+6.1f}% "
                f"R={m['mean_r']:>+6.3f} "
                f"win={m['win_pct']:>5.1f}% "
                f"PZ={m['pz_rate']:>6.2f}% "
                f"PZn={m['pz_count']:>6} "
                f"gb={m['avg_giveback_pct']:>5.2f}% "
                f"hold={m['avg_hold_bars']:>4.0f}b"
                f"{tag}"
            )

    # Özet Karar
    print("\n\n" + "=" * 175)
    print("ÖZET KARAR")
    print("=" * 175)

    if champion_m55 is None:
        print("HATA: champion metrikleri hesaplanamadı.")
        return

    print(f"\nCHAMPION (55bps):")
    print(
        f"  monthly_ROI={champion_m55['monthly_mean_roi']:+.2f}%  "
        f"MaxDD={champion_m55['max_dd']:+.1f}%  "
        f"meanR={champion_m55['mean_r']:+.3f}  "
        f"win%={champion_m55['win_pct']:.1f}%  "
        f"P->Z={champion_m55['pz_rate']:.2f}% (n={champion_m55['pz_count']})  "
        f"giveback={champion_m55['avg_giveback_pct']:.2f}%"
    )

    challengers_55 = [m for m in all_results if m["label"] != "champion" and m["cost_label"] == "55bps"]

    print(f"\n{'─'*155}")
    print("CHALLENGER KARŞILAŞTIRMA vs CHAMPION (55bps):")
    print(f"  {'Varyant':<18} {'ROI_d':>8} {'DD_d':>7} {'R_d':>7} "
          f"{'PZ%':>7} {'PZ_d':>8} {'gb%':>7} {'gb_d':>7} {'VERDICT':>12}")
    print("  " + "-" * 100)

    gate_pass = []
    for m in challengers_55:
        roi_d = m["monthly_mean_roi"] - champion_m55["monthly_mean_roi"]
        dd_d = m["max_dd"] - champion_m55["max_dd"]
        r_d = m["mean_r"] - champion_m55["mean_r"]
        pz_d = m["pz_rate"] - champion_m55["pz_rate"]
        gb_d = m["avg_giveback_pct"] - champion_m55["avg_giveback_pct"]
        r_loss_pct = abs(r_d) / abs(champion_m55["mean_r"]) * 100 if champion_m55["mean_r"] != 0 else 0

        if roi_d >= 0 and dd_d <= 0:
            verdict = "SAFE"
            gate_pass.append(m)
        elif roi_d >= -0.5 and r_loss_pct < 3.0 and pz_d < 0:
            verdict = "ACCEPTABLE"
        elif pz_d < -2.0 and r_loss_pct < 5.0:
            verdict = "PZ-KORUYUCU"
        else:
            verdict = "RISKY"

        print(
            f"  {m['label']:<18} "
            f"{roi_d:>+8.2f}pp "
            f"{dd_d:>+7.1f}pp "
            f"{r_d:>+7.3f} "
            f"{m['pz_rate']:>6.2f}% "
            f"{pz_d:>+8.2f}pp "
            f"{m['avg_giveback_pct']:>6.2f}% "
            f"{gb_d:>+7.2f}pp "
            f"[{verdict}]"
        )

    # Gate geçenler
    print(f"\n{'─'*155}")
    print("GATE SONUCU (ROI>=champion AND DD<=champion, 55bps):")
    if gate_pass:
        best_gate = max(gate_pass, key=lambda x: x["monthly_mean_roi"])
        print(f"  GEÇEN: {[m['label'] for m in gate_pass]}")
        print(f"  EN İYİ: {best_gate['label']}")
        for m in gate_pass:
            pz_red_pct = (champion_m55["pz_rate"] - m["pz_rate"]) / champion_m55["pz_rate"] * 100 if champion_m55["pz_rate"] > 0 else 0
            r_loss_pct = abs(m["mean_r"] - champion_m55["mean_r"]) / abs(champion_m55["mean_r"]) * 100
            print(
                f"    {m['label']}: "
                f"ROI={m['monthly_mean_roi']:+.2f}%, DD={m['max_dd']:+.1f}%, "
                f"meanR={m['mean_r']:+.3f} ({r_loss_pct:.1f}% kayıp), "
                f"P->Z={m['pz_rate']:.2f}% ({pz_red_pct:.0f}% azalma), "
                f"giveback={m['avg_giveback_pct']:.2f}%"
            )
    else:
        print("  HİÇBİR VARYANT GATE'İ GEÇEMEDİ — Champion korunur.")

    # 100bps stres kontrolü (gate geçenler için)
    if gate_pass:
        champ_100 = next((m for m in all_results if m["label"] == "champion" and m["cost_label"] == "100bps"), None)
        print(f"\n{'─'*155}")
        print("100BPS STRES (gate geçenler):")
        for gm in gate_pass:
            gm_100 = next((m for m in all_results if m["label"] == gm["label"] and m["cost_label"] == "100bps"), None)
            if champ_100 and gm_100:
                roi_d = gm_100["monthly_mean_roi"] - champ_100["monthly_mean_roi"]
                dd_d = gm_100["max_dd"] - champ_100["max_dd"]
                pz_d = gm_100["pz_rate"] - champ_100["pz_rate"]
                status = "OK" if roi_d >= 0 and dd_d <= 0 else "WARN"
                print(
                    f"  {gm['label']:<18}: "
                    f"ROI={gm_100['monthly_mean_roi']:+.2f}% ({roi_d:+.2f}pp), "
                    f"DD={gm_100['max_dd']:+.1f}% ({dd_d:+.1f}pp), "
                    f"P->Z={gm_100['pz_rate']:.2f}% ({pz_d:+.2f}pp)  [{status}]"
                )

    # Deploy tavsiyesi
    print(f"\n{'─'*155}")
    print("DEPLOY TAVSİYESİ:")
    best_pz = min(challengers_55, key=lambda x: x["pz_rate"]) if challengers_55 else None
    best_roi = max(challengers_55, key=lambda x: x["monthly_mean_roi"]) if challengers_55 else None

    if gate_pass:
        best = max(gate_pass, key=lambda x: (
            -x["pz_rate"],           # P->Z düşük önce
            x["monthly_mean_roi"],    # sonra ROI yüksek
        ))
        r_loss_pct = abs(best["mean_r"] - champion_m55["mean_r"]) / abs(champion_m55["mean_r"]) * 100
        pz_red_pct = (champion_m55["pz_rate"] - best["pz_rate"]) / champion_m55["pz_rate"] * 100 if champion_m55["pz_rate"] > 0 else 0
        print(f"  EVET — DEPLOY ADEYİ: {best['label']}")
        print(f"  meanR kaybı: {r_loss_pct:.1f}% (hedef <3%)")
        print(f"  P->Z azalma: {pz_red_pct:.0f}%")
        print(f"  ROI farkı: {best['monthly_mean_roi']-champion_m55['monthly_mean_roi']:+.2f}pp")
        print(f"  DD farkı:  {best['max_dd']-champion_m55['max_dd']:+.1f}pp")
    else:
        # En az zararlı varyant
        if best_pz and challengers_55:
            r_loss_pct = abs(best_pz["mean_r"] - champion_m55["mean_r"]) / abs(champion_m55["mean_r"]) * 100
            pz_red_pct = (champion_m55["pz_rate"] - best_pz["pz_rate"]) / champion_m55["pz_rate"] * 100 if champion_m55["pz_rate"] > 0 else 0
            if r_loss_pct < 5.0 and pz_red_pct > 20:
                print(f"  KOŞULLUp — {best_pz['label']}: P->Z {pz_red_pct:.0f}% azaltıyor ama edge -{r_loss_pct:.1f}%")
                print(f"  Daha fazla stres testi / paper trade sonrası değerlendirin.")
            else:
                print(f"  HAYIR — Gate geçilmedi, en iyi P->Z azaltıcı {best_pz['label']} ama edge kaybı %{r_loss_pct:.1f}")
                print(f"  Champion korunmalı.")

    print("\n[Done]")


if __name__ == "__main__":
    main()
