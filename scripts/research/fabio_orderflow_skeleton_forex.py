#!/usr/bin/env python3
"""Fabio order-flow scalper — MEKANİK İSKELET backtest (forex, paper/research).

HONEST FRAMING (rapora birebir geçer):
  Order-flow (delta/footprint/absorption/volume-profile) BIZIM VERIMIZDEN ÜRETİLEMEZ.
  forex_market.duckdb ohlcv.volume = 0.0 (6 yılın tamamında). Footprint/delta/CVD yok.
  Bu script Fabio'nun edge'inin ISKELETINI test eder:
    seans-filtreli + yatay-seviye reddi + sıkı stop + R:R hedef + BE/trailing.
  Order-flow onayı OLMADAN. "İskelet tek başına edge taşıyor mu?" sorusunu cevaplar.

LOOKAHEAD GUARANTEE:
  - feature/karar t-1 close itibariyle; giriş t bar OPEN.
  - shift(-1) / center=True / future-rolling YOK.
  - önceki-gün H/L strictly geçmiş UTC takvim gününden.
  - bar-içi: stop ÖNCE, TP SONRA (aynı barda ikisi de => stop sayılır, konservatif).

Usage:
  python scripts/research/fabio_orderflow_skeleton_forex.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

DB = "data/forex_market.duckdb"
TF = "15m"
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]  # intraday verisi olan tek 3 major
SEED = 42

# --- maliyet modeli (pip cinsi, round-trip toplam) ---
PIP = {"EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01}
SPREAD_PIP = {"EUR/USD": 0.8, "GBP/USD": 1.3, "USD/JPY": 1.0}
COMMISSION_PIP = 0.5      # ECN konservatif
SLIPPAGE_PIP = 0.2        # stop'ta ek

# --- round-number grid (psikolojik seviye proxy) ---
RN_GRID = {"EUR/USD": 0.0050, "GBP/USD": 0.0050, "USD/JPY": 0.50}

# --- sabit strateji parametreleri (NO grid-search; video + base'den türetildi) ---
ATR_N = 14
PROX_ATR = 0.25       # seviye yakınlığı
STOP_ATR = 0.30       # seviye ötesi sıkı stop
TP_R = 1.5            # R:R hedef (sonraki seviye yoksa)
BE_R = 1.0           # 1R'de breakeven
TRAIL_ATR = 1.0       # trailing aktivasyon sonrası
BODY_MAX = 0.50       # gövde <= %50 range
WICK_MIN = 0.40       # ters fitil >= %40 range
MAX_HOLD_BARS = 48    # 12 saat (15m) — scalp time-exit

# --- seans pencereleri (UTC) ---
# London aktif 07:00-11:00 UTC, NY aktif 13:00-17:00 UTC. Asya 00:00-06:00 (zayıf, ayrı raporlanır).
SESSIONS = {
    "London": (7, 11),
    "NY": (13, 17),
    "Asia": (0, 6),
}
ACTIVE_SESSIONS = ["London", "NY"]  # sinyal sadece bu ikisinde


@dataclass
class Trade:
    symbol: str
    session: str
    year: int
    side: int            # +1 long, -1 short
    entry_ts: pd.Timestamp
    entry: float
    stop: float
    r_gross: float       # R cinsi gross sonuç
    r_net: float         # maliyet sonrası
    bars_held: int


def load(con, sym: str) -> pd.DataFrame:
    df = con.execute(
        "SELECT ts, open, high, low, close FROM ohlcv "
        "WHERE symbol=? AND timeframe=? ORDER BY ts",
        [sym, TF],
    ).df()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df


def add_features(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    df = df.copy()
    # --- ATR(14) causal (Wilder), t-1 close itibariyle bilinir ---
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / ATR_N, adjust=False, min_periods=ATR_N).mean()

    # --- önceki UTC takvim gününün H/L (STRICTLY geçmiş gün) ---
    daygrp = df.index.floor("D")
    day_high = df["high"].groupby(daygrp).transform("max")
    day_low = df["low"].groupby(daygrp).transform("min")
    # bugünün running değil; ÖNCEKI günün tam H/L lazım -> günlük agg sonra shift
    daily = pd.DataFrame({"dh": df["high"].groupby(daygrp).max(),
                          "dl": df["low"].groupby(daygrp).min()})
    daily["pdh"] = daily["dh"].shift(1)   # previous day high
    daily["pdl"] = daily["dl"].shift(1)
    df["day"] = daygrp
    df = df.merge(daily[["pdh", "pdl"]], left_on="day", right_index=True, how="left")
    df = df.set_index(df.index)  # index korunur (merge index'i bozmadı çünkü on=day)
    df["session"] = df.index.hour.map(_hour_to_session)
    return df


def _hour_to_session(h: int) -> str:
    for name, (lo, hi) in SESSIONS.items():
        if lo <= h < hi:
            return name
    return "Off"


def _round_levels(price: float, grid: float, n: int = 2) -> list[float]:
    base = round(price / grid) * grid
    return [base + k * grid for k in range(-n, n + 1)]


def generate_signals(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """t-1 close itibariyle sinyal; giriş t open.

    rejection bar (t-1 barında değerlendirilir):
      - bullish: bar bir support seviyeye 0.25 ATR yakınından aşağı sarkıp
        yukarı kapanır (alt fitil >= %40, gövde <= %50, close > open).
      - bearish: simetrik resistance.
    """
    out = []
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    atr = df["atr"].values
    pdh = df["pdh"].values
    pdl = df["pdl"].values
    sess = df["session"].values
    idx = df.index
    grid = RN_GRID[sym]

    for i in range(1, len(df) - 1):
        a = atr[i - 1]  # t-1 itibariyle bilinen ATR (causal ewm min_periods=14)
        if not np.isfinite(a) or a <= 0:
            continue
        # KARAR BARI = t-1 (index i-1). GİRİŞ = t (index i) open.
        # Ama sinyal geometrisini i-1 barından oku; sadece geçmiş.
        b = i - 1
        rng = h[b] - l[b]
        if rng <= 0:
            continue
        body = abs(c[b] - o[b])
        if body > BODY_MAX * rng:
            continue
        # seans giriş barına (t) göre — aktif seansta mı?
        if sess[i] not in ACTIVE_SESSIONS:
            continue
        # aday seviyeler: pdh, pdl + round numbers (b barı close'una göre)
        levels = []
        if np.isfinite(pdh[b]):
            levels.append(("R", pdh[b]))
        if np.isfinite(pdl[b]):
            levels.append(("S", pdl[b]))
        for lv in _round_levels(c[b], grid, 2):
            levels.append(("RN", lv))

        prox = PROX_ATR * a
        lower_wick = min(o[b], c[b]) - l[b]
        upper_wick = h[b] - max(o[b], c[b])

        sig = None
        for _kind, lvl in levels:
            # bullish rejection @ support: bar low seviyeye yakın değdi, yukarı kapandı
            if (abs(l[b] - lvl) <= prox and c[b] > o[b]
                    and lower_wick >= WICK_MIN * rng):
                stop = lvl - STOP_ATR * a
                if o[i] - stop > 0:  # entry t-open, geçerli stop mesafesi
                    sig = (+1, lvl, stop)
                    break
            # bearish rejection @ resistance
            if (abs(h[b] - lvl) <= prox and c[b] < o[b]
                    and upper_wick >= WICK_MIN * rng):
                stop = lvl + STOP_ATR * a
                if stop - o[i] > 0:
                    sig = (-1, lvl, stop)
                    break
        if sig is None:
            continue
        side, lvl, stop = sig
        entry = o[i]  # t bar OPEN — lookahead-safe
        out.append({
            "entry_i": i, "entry_ts": idx[i], "side": side,
            "entry": entry, "stop": stop, "level": lvl,
            "atr": a, "session": sess[i], "year": idx[i].year,
        })
    return pd.DataFrame(out)


def _next_level(side: int, entry: float, atr: float, pdh, pdl, grid: float):
    """TP için bir sonraki yatay seviye (entry'nin ötesinde, hedef yönde)."""
    cands = []
    for lv in (pdh, pdl):
        if np.isfinite(lv):
            cands.append(lv)
    cands += _round_levels(entry, grid, 3)
    if side > 0:
        ahead = [lv for lv in cands if lv > entry + 0.1 * atr]
        return min(ahead) if ahead else None
    else:
        ahead = [lv for lv in cands if lv < entry - 0.1 * atr]
        return max(ahead) if ahead else None


def simulate(df: pd.DataFrame, sigs: pd.DataFrame, sym: str) -> list[Trade]:
    """Bar-içi: stop ÖNCE, TP SONRA. BE@1R, trail 1.0 ATR sonra. Konservatif."""
    h = df["high"].values
    l = df["low"].values
    o = df["open"].values
    c = df["close"].values
    pdh = df["pdh"].values
    pdl = df["pdl"].values
    grid = RN_GRID[sym]
    pip = PIP[sym]
    cost_pip = SPREAD_PIP[sym] + COMMISSION_PIP
    slip_pip = SLIPPAGE_PIP
    n = len(df)
    trades = []

    for _, s in sigs.iterrows():
        i0 = int(s["entry_i"])
        side = int(s["side"])
        entry = float(s["entry"])
        stop = float(s["stop"])
        atr = float(s["atr"])
        risk = abs(entry - stop)  # 1R fiyat cinsi
        if risk <= 0:
            continue
        # TP: min(next level dist, TP_R) — hangisi yakınsa
        nl = _next_level(side, entry, atr, pdh[i0], pdl[i0], grid)
        tp_r_price = entry + side * TP_R * risk
        if nl is not None:
            tp = nl if (side > 0 and nl < tp_r_price) or (side < 0 and nl > tp_r_price) else tp_r_price
        else:
            tp = tp_r_price
        be_price = entry + side * BE_R * risk

        cur_stop = stop
        be_armed = False
        trail_armed = False
        peak = entry
        exit_price = None
        bars = 0
        for j in range(i0, min(i0 + MAX_HOLD_BARS, n)):
            bars = j - i0 + 1
            hi, lo = h[j], l[j]
            # --- güncel stop/TP'ye karşı bar-içi (stop ÖNCE) ---
            if side > 0:
                if lo <= cur_stop:
                    exit_price = cur_stop; break
                if hi >= tp:
                    exit_price = tp; break
                # BE / trail update (bu bar SONRASI için; lookahead yok: bu barın H/L'siyle peak)
                peak = max(peak, hi)
                if not be_armed and hi >= be_price:
                    cur_stop = max(cur_stop, entry); be_armed = True
                if be_armed:
                    trail_armed = True
                if trail_armed:
                    cur_stop = max(cur_stop, peak - TRAIL_ATR * atr)
            else:
                if hi >= cur_stop:
                    exit_price = cur_stop; break
                if lo <= tp:
                    exit_price = tp; break
                peak = min(peak, lo)
                if not be_armed and lo <= be_price:
                    cur_stop = min(cur_stop, entry); be_armed = True
                if be_armed:
                    trail_armed = True
                if trail_armed:
                    cur_stop = min(cur_stop, peak + TRAIL_ATR * atr)
        if exit_price is None:
            # time-exit at close of last held bar
            jlast = min(i0 + MAX_HOLD_BARS, n) - 1
            exit_price = c[jlast]
            bars = jlast - i0 + 1

        gross_price = side * (exit_price - entry)
        r_gross = gross_price / risk
        # maliyet (pip -> fiyat -> R)
        cost_price = (cost_pip + slip_pip) * pip
        r_net = (gross_price - cost_price) / risk
        trades.append(Trade(sym, s["session"], int(s["year"]), side,
                            s["entry_ts"], entry, stop, r_gross, r_net, bars))
    return trades


# ===================== metrics & robustness =====================

def calc_kpis(rs: np.ndarray) -> dict:
    if len(rs) == 0:
        return {"n": 0}
    eq = np.cumsum(rs)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    wins = rs > 0
    mean = rs.mean()
    sd = rs.std(ddof=1) if len(rs) > 1 else 0.0
    # t-test mean_R vs 0
    t = mean / (sd / np.sqrt(len(rs))) if sd > 0 else 0.0
    from scipy import stats
    p = 2 * (1 - stats.t.cdf(abs(t), df=len(rs) - 1)) if sd > 0 else 1.0
    return {
        "n": len(rs),
        "mean_R": round(mean, 4),
        "win%": round(100 * wins.mean(), 1),
        "sum_R": round(eq[-1], 2),
        "maxDD_R": round(dd.min(), 2),
        "t": round(t, 2),
        "p": round(float(p), 4),
    }


def shuffle_baseline(rs: np.ndarray, n_iter: int = 1000, seed: int = SEED) -> dict:
    """Null: trade R sırası rastgele -> sum_R dağılımı. Edge tarih-bağımlı mı?

    Sign-flip permutation: her R'nin işaretini rastgele çevir (mean=0 null).
    Gerçek mean_R, null dağılımının %95'inin üstünde mi?
    """
    if len(rs) < 5:
        return {"shuffle_p": 1.0, "obs_mean": 0.0, "null_p95": 0.0}
    rng = np.random.default_rng(seed)
    obs = rs.mean()
    null = np.empty(n_iter)
    for k in range(n_iter):
        signs = rng.choice([-1, 1], size=len(rs))
        null[k] = (rs * signs).mean()
    # one-sided: obs > null
    p = (np.sum(null >= obs) + 1) / (n_iter + 1)
    return {"shuffle_p": round(float(p), 4),
            "obs_mean": round(float(obs), 4),
            "null_p95": round(float(np.percentile(null, 95)), 4)}


def main():
    con = duckdb.connect(DB, read_only=True)
    all_trades: list[Trade] = []
    audit = {}
    for sym in SYMBOLS:
        df = load(con, sym)
        df = add_features(df, sym)
        # LOOKAHEAD AUDIT: pdh/pdl bugünün barından önceki günden mi?
        # spot-check: ilk geçerli pdh satırı, o günün önceki gününe ait olmalı
        sigs = generate_signals(df, sym)
        tr = simulate(df, sigs, sym)
        all_trades += tr
        audit[sym] = {"bars": len(df), "signals": len(sigs), "trades": len(tr)}
    con.close()

    df_tr = pd.DataFrame([t.__dict__ for t in all_trades])
    if df_tr.empty:
        print("NO TRADES")
        return

    print("=== AUDIT (bars/signals/trades) ===")
    for s, a in audit.items():
        print(f"  {s}: {a}")

    rs_all = df_tr["r_net"].values
    print("\n=== OVERALL (net-of-cost) ===")
    print(calc_kpis(rs_all))
    print("gross:", calc_kpis(df_tr["r_gross"].values))
    print("shuffle:", shuffle_baseline(rs_all))

    print("\n=== BY SYMBOL x SESSION (net mean_R / n) ===")
    piv = df_tr.groupby(["symbol", "session"]).agg(
        n=("r_net", "size"),
        mean_R=("r_net", "mean"),
        win=("r_net", lambda x: (x > 0).mean() * 100),
        sumR=("r_net", "sum"),
    ).round(3)
    print(piv.to_string())

    print("\n=== BY YEAR (walk-forward OOS proxy, net) ===")
    by_year = df_tr.groupby("year")["r_net"].agg(["size", "mean", "sum"]).round(3)
    by_year["pos"] = by_year["mean"] > 0
    print(by_year.to_string())
    print(f"\nWalk-forward: {by_year['pos'].sum()}/{len(by_year)} yıl mean_R>0")

    print("\n=== BY SESSION (pooled) ===")
    print(df_tr.groupby("session")["r_net"].agg(["size", "mean", "sum"]).round(3).to_string())

    print("\n=== BY SYMBOL (pooled) ===")
    print(df_tr.groupby("symbol")["r_net"].agg(["size", "mean", "sum"]).round(3).to_string())

    # monthly ROI proxy: risk %1, mean_R per trade * trades/month
    months = (df_tr["entry_ts"].max() - df_tr["entry_ts"].min()).days / 30.44
    monthly_R = rs_all.sum() / months
    print(f"\nMonthly ROI proxy (risk 1%/trade): {monthly_R*1.0:.2f}% (={monthly_R:.2f} R/ay) over {months:.1f} months")

    # save trades for reproducibility
    df_tr.to_csv("reports/research/fabio_skeleton_forex_trades.csv", index=False)
    print("\ntrades -> reports/research/fabio_skeleton_forex_trades.csv")


if __name__ == "__main__":
    main()
