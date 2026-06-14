"""Fabio order-flow → Value-Area (Volume Profile) crypto backtest.

HYP-2026-06-01-fabio-orderflow-valuearea-crypto (pre-registered).

Fabio (YouTube) ORDER-FLOW scalping → NQ + CRYPTO. NQ verisi yok; crypto'da
GERÇEK HACİM var → Volume Profile / Value Area (VAH/VAL/POC) proxy KURULABİLİR.

ÇEKİRDEK:
  - Önceki KAPANMIŞ takvim-günün GERÇEK-hacim Volume Profile'ı → VAL/VAH/POC.
  - VAL yakınında wick-rejection long ("AAA = value area low'da alış"),
    VAH yakınında wick-rejection short.
  - Seviye-ötesi sıkı stop, hedef POC / karşı value-area kenarı (R:R doğal).
  - Seans filtresi (NY/London/Asya).
  - Dürüst maliyet: 55bps + 100bps round-trip stres.

LOOKAHEAD-GÜVENLİ:
  - VA SADECE t bar'ından ÖNCE kapanmış günün barlarından (groupby prev day).
  - Entry kararı bar KAPANIŞINDA; dolum bir sonraki bar OPEN (konservatif).
  - Intrabar stop/target: ambiguity'de STOP-ÖNCE (konservatif).
  - shift(-1) / center=True YOK.

market.duckdb READ-ONLY. Canlı config/daemon DOKUNULMADI. Deploy YOK.
Reproduce: .venv/bin/python scripts/research/fabio_orderflow_valuearea_crypto.py
"""
from __future__ import annotations
import io, os, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
warnings.filterwarnings("ignore")
os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "market.duckdb"

import duckdb

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"]
TF = "5m"
VENUE = "binance"
VA_PCT = 0.70          # standart Market Profile %70 value area
N_BINS = 50
ATR_LEN = 14           # 5m ATR (intraday)
PROX_K = 0.5           # |close - VA edge| < PROX_K * ATR  (pre-reg: 0.25/0.5)
STOP_M = 0.5           # stop = edge -/+ STOP_M * ATR beyond level
RR_CAP = 4.0           # hedef R clamp (POC çok uzaksa)
SEED = 7

# Seans tanımı (UTC saat). Binance ts Europe/Istanbul (+3) saklı → UTC'ye çevir.
# London ~07-16 UTC, NY ~12-21 UTC (overlap aktif), Asya ~00-07 UTC (zayıf).
def session_of(hour_utc: int) -> str:
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 21:
        return "NY"
    if 0 <= hour_utc < 7:
        return "Asia"
    return "Off"  # 21-24 UTC


def load(con, sym):
    df = con.execute(
        "select ts, open, high, low, close, volume from ohlcv "
        "where symbol=? and timeframe=? and venue=? order by ts",
        [sym, TF, VENUE],
    ).df()
    if df.empty:
        return df
    # ts → UTC
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    # UTC takvim günü, tz-naive (key tutarlılığı için — .values tz'i düşürür)
    df["day"] = df.index.tz_convert("UTC").tz_localize(None).normalize()
    df["hour"] = df.index.hour
    df["session"] = df["hour"].map(session_of)
    # ATR (Wilder benzeri, basit rolling)
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_LEN, min_periods=ATR_LEN).mean()
    return df


def value_area_for_day(day_df: pd.DataFrame):
    """Bir günün barlarından volume profile → (POC, VAL, VAH). GERÇEK hacim.

    Her bar hacmini [low, high] aralığına eşit dağıt (OHLCV proxy — tick yok).
    """
    lo = float(day_df["low"].min())
    hi = float(day_df["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, N_BINS + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    vol = np.zeros(N_BINS)
    bl = day_df["low"].values
    bh = day_df["high"].values
    bv = day_df["volume"].values
    bin_w = (hi - lo) / N_BINS
    for i in range(len(bl)):
        if bh[i] <= bl[i] or bv[i] <= 0:
            continue
        # bar aralığına denk gelen kovalara hacmi eşit yay
        i0 = max(0, int((bl[i] - lo) / bin_w))
        i1 = min(N_BINS - 1, int((bh[i] - lo) / bin_w))
        span = i1 - i0 + 1
        if span <= 0:
            continue
        vol[i0:i1 + 1] += bv[i] / span
    if vol.sum() <= 0:
        return None
    poc_idx = int(np.argmax(vol))
    poc = centers[poc_idx]
    # VA genişletme: POC'tan başla, %70 hacme ulaşana dek komşu kova-çiftleri ekle
    total = vol.sum()
    target = VA_PCT * total
    lo_i = hi_i = poc_idx
    acc = vol[poc_idx]
    while acc < target and (lo_i > 0 or hi_i < N_BINS - 1):
        up = vol[hi_i + 1] if hi_i < N_BINS - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    val = centers[lo_i]
    vah = centers[hi_i]
    return poc, val, vah


def build_va_map(df: pd.DataFrame):
    """Her gün için VA hesapla. KEY: o günün VA'sı SONRAKİ gün kullanılır."""
    va = {}
    for day, g in df.groupby("day"):
        r = value_area_for_day(g)
        if r is not None:
            va[day] = r
    return va


SL_PCT_MIN = 0.0   # fee-erozyon kalkanı (0=kapalı). Memory: 5m floor 0.030.


def simulate_symbol(df: pd.DataFrame, va: dict, prox_k=PROX_K, flip_dir=False,
                    seed=None, sl_pct_min=SL_PCT_MIN):
    """Lookahead-güvenli: t günü için DÜN'ün (t-1) VA'sı kullanılır.

    flip_dir/seed: shuffle baseline için yön rastgeleleştirme.
    Dönen: trade kayıtları listesi.
    """
    rng = np.random.default_rng(seed) if seed is not None else None
    days = sorted(va.keys())
    day_to_prev = {}
    for i in range(1, len(days)):
        day_to_prev[days[i]] = days[i - 1]

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    atr = df["atr"].values
    sess = df["session"].values
    dayarr = df["day"].values
    idx = df.index

    trades = []
    n = len(df)
    i = 0
    while i < n - 2:
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            i += 1
            continue
        dkey = pd.Timestamp(dayarr[i])  # tz-naive UTC gün
        prevd = day_to_prev.get(dkey)
        if prevd is None or prevd not in va:
            i += 1
            continue
        poc, val, vah = va[prevd]
        close_i = c[i]
        low_i = l[i]
        high_i = h[i]

        sig = None  # 'long' | 'short'
        # LONG: bar VAL altına sarkar (wick) ama VAL üstünde kapanır → rejection
        if low_i <= val and close_i > val and abs(close_i - val) < prox_k * a:
            sig = "long"
        # SHORT: bar VAH üstüne taşar ama VAH altında kapanır → rejection
        elif high_i >= vah and close_i < vah and abs(close_i - vah) < prox_k * a:
            sig = "short"

        if sig is None:
            i += 1
            continue

        # shuffle baseline: yönü rastgele çevir (aynı entry zamanları, null yön)
        if rng is not None:
            sig = "long" if rng.random() < 0.5 else "short"
        if flip_dir:
            sig = "short" if sig == "long" else "long"

        # Dolum: bir sonraki bar OPEN (konservatif — sinyal bar kapanışında bilinir)
        if i + 1 >= n:
            break
        entry = o[i + 1]
        if not np.isfinite(entry) or entry <= 0:
            i += 1
            continue

        if sig == "long":
            stop = val - STOP_M * a
            # fee-erozyon kalkanı: stop'u en az sl_pct_min uzağa it
            if sl_pct_min > 0:
                stop = min(stop, entry * (1.0 - sl_pct_min))
            # hedef: POC (VAL üstündeyse) yoksa VAH
            tgt = poc if poc > entry else vah
            risk = entry - stop
        else:
            stop = vah + STOP_M * a
            if sl_pct_min > 0:
                stop = max(stop, entry * (1.0 + sl_pct_min))
            tgt = poc if poc < entry else val
            risk = stop - entry

        if risk <= 0:
            i += 1
            continue
        reward = abs(tgt - entry)
        rr = reward / risk
        if rr < 0.3:
            i += 1
            continue
        rr = min(rr, RR_CAP)
        # nihai hedef R-clamp'e göre fiyat
        if sig == "long":
            tgt = entry + rr * risk
        else:
            tgt = entry - rr * risk

        # Intrabar yürüt: sonraki barlardan başla (entry bar'ı i+1)
        outcome_R = None
        exit_idx = None
        max_hold = 96  # 8 saat @5m — Fabio scalp, gün-içi
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            hj, lj = h[j], l[j]
            if sig == "long":
                hit_stop = lj <= stop
                hit_tgt = hj >= tgt
            else:
                hit_stop = hj >= stop
                hit_tgt = lj <= tgt
            # konservatif: aynı barda ikisi de → STOP önce
            if hit_stop:
                outcome_R = -1.0
                exit_idx = j
                break
            if hit_tgt:
                outcome_R = rr
                exit_idx = j
                break
        if outcome_R is None:
            # zaman aşımı → son kapanışta mark-to-market
            j = min(i + max_hold, n - 1)
            last = c[j]
            outcome_R = ((last - entry) / risk) if sig == "long" else ((entry - last) / risk)
            exit_idx = j

        sl_pct = risk / entry  # round-trip cost → R dönüşümü için
        trades.append({
            "entry_ts": idx[i + 1],
            "exit_ts": idx[exit_idx],
            "session": sess[i],
            "year": pd.Timestamp(idx[i]).year,
            "dir": sig,
            "R": outcome_R,
            "sl_pct": sl_pct,
            "rr": rr,
        })
        # overlap önle: çıkıştan sonra devam et
        i = exit_idx + 1
    return trades


def apply_cost(trades, extra_bps):
    """extra_cost_R = extra_bps / (sl_pct*10000) — Lab honest-cost metodolojisi."""
    out = []
    for t in trades:
        slp = t["sl_pct"]
        extra_R = (extra_bps / (slp * 10000.0)) if slp > 0 else 0.0
        out.append({**t, "R_net": t["R"] - extra_R})
    return out


def calendar_sharpe(trades, key="R_net"):
    """Takvim-günü R toplamı → Sharpe (ppy=365). ŞİŞİRME YOK."""
    if not trades:
        return 0.0
    df = pd.DataFrame(trades)
    df["day"] = pd.to_datetime(df["exit_ts"]).dt.normalize()
    daily = df.groupby("day")[key].sum()
    # boş günleri 0 ile doldur (gerçek takvim)
    full = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full, fill_value=0.0)
    if daily.std(ddof=0) == 0:
        return 0.0
    return float(daily.mean() / daily.std(ddof=0) * np.sqrt(365))


def summ(trades, key="R_net"):
    if not trades:
        return dict(n=0, mean_R=0.0, win=0.0, maxdd=0.0, total_R=0.0, sharpe=0.0)
    df = pd.DataFrame(trades)
    r = df[key].values
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak).min()
    return dict(
        n=len(df),
        mean_R=float(r.mean()),
        win=float((r > 0).mean() * 100),
        maxdd=float(dd),
        total_R=float(r.sum()),
        sharpe=calendar_sharpe(trades, key),
    )


def main():
    con = duckdb.connect(str(DB), read_only=True)
    print("=" * 78)
    print("FABIO ORDER-FLOW → VALUE-AREA (Volume Profile) CRYPTO BACKTEST")
    print("HYP-2026-06-01-fabio-orderflow-valuearea-crypto | git=af14df4")
    print(f"TF={TF} venue={VENUE} VA%={VA_PCT} bins={N_BINS} prox_k={PROX_K} stop_m={STOP_M}")
    print("=" * 78)

    all_real = []           # gerçek sinyal trade'leri (tüm semboller)
    per_symbol = {}
    for sym in SYMBOLS:
        df = load(con, sym)
        if df.empty or len(df) < 5000:
            print(f"  {sym}: yetersiz veri, atla")
            continue
        va = build_va_map(df)
        tr = simulate_symbol(df, va, prox_k=PROX_K)
        per_symbol[sym] = tr
        all_real.extend(tr)
        print(f"  {sym}: bars={len(df)} VA-gün={len(va)} sinyal-trade={len(tr)}")

    print("\n" + "=" * 78)
    print("1) HEADLINE — tüm semboller, maliyet senaryoları (gerçek yön)")
    print("=" * 78)
    print(f"{'cost':>10} | {'n':>5} {'mean_R':>8} {'win%':>6} {'totR':>9} {'maxDD':>8} {'Sharpe':>7}")
    headline = {}
    for label, bps in [("0bps", 0), ("55bps", 55), ("100bps", 100)]:
        tc = apply_cost(all_real, bps)
        s = summ(tc)
        headline[bps] = s
        print(f"{label:>10} | {s['n']:>5} {s['mean_R']:>8.3f} {s['win']:>6.1f} "
              f"{s['total_R']:>9.1f} {s['maxdd']:>8.1f} {s['sharpe']:>7.2f}")

    print("\n" + "=" * 78)
    print("2) SHUFFLE BASELINE (yön rastgele, aynı entry zamanları) — null model")
    print("   55bps maliyet altında. 50 seed, mean_R dağılımı.")
    print("=" * 78)
    shuffle_means = []
    for sd in range(50):
        st = []
        for sym in SYMBOLS:
            df = load(con, sym)
            if df.empty or len(df) < 5000:
                continue
            va = build_va_map(df)
            st.extend(simulate_symbol(df, va, seed=1000 + sd))
        sc = apply_cost(st, 55)
        shuffle_means.append(np.mean([t["R_net"] for t in sc]) if sc else 0.0)
    shuffle_means = np.array(shuffle_means)
    real_mean = headline[55]["mean_R"]
    # tek-taraflı p: shuffle >= real oranı
    p_val = float((shuffle_means >= real_mean).mean())
    print(f"  gerçek mean_R(55bps) = {real_mean:+.4f}")
    print(f"  shuffle mean_R: ort={shuffle_means.mean():+.4f} std={shuffle_means.std():.4f} "
          f"min={shuffle_means.min():+.4f} max={shuffle_means.max():+.4f}")
    print(f"  p-value (tek taraflı, shuffle>=gerçek) = {p_val:.4f}  "
          f"→ {'shuffle GEÇİLDİ (p<0.05)' if p_val < 0.05 else 'shuffle GEÇİLEMEDİ'}")

    print("\n" + "=" * 78)
    print("3) SEANS KIRILIMI (55bps) — Fabio: NY/London aktif, Asya zayıf")
    print("=" * 78)
    tc55 = apply_cost(all_real, 55)
    print(f"{'session':>8} | {'n':>5} {'mean_R':>8} {'win%':>6} {'totR':>9} {'maxDD':>8}")
    for ses in ["NY", "London", "Asia", "Off"]:
        sub = [t for t in tc55 if t["session"] == ses]
        s = summ(sub)
        print(f"{ses:>8} | {s['n']:>5} {s['mean_R']:>8.3f} {s['win']:>6.1f} "
              f"{s['total_R']:>9.1f} {s['maxdd']:>8.1f}")

    print("\n" + "=" * 78)
    print("4) WALK-FORWARD (yıllık OOS, 55bps) — her yıl ayrı")
    print("=" * 78)
    print(f"{'year':>6} | {'n':>5} {'mean_R':>8} {'win%':>6} {'totR':>9} {'Sharpe':>7}")
    yrs = sorted(set(t["year"] for t in tc55))
    pos_years = 0
    for y in yrs:
        sub = [t for t in tc55 if t["year"] == y]
        s = summ(sub)
        if s["mean_R"] > 0:
            pos_years += 1
        print(f"{y:>6} | {s['n']:>5} {s['mean_R']:>8.3f} {s['win']:>6.1f} "
              f"{s['total_R']:>9.1f} {s['sharpe']:>7.2f}")
    print(f"  pozitif yıl: {pos_years}/{len(yrs)}")

    print("\n" + "=" * 78)
    print("5) SEMBOL KIRILIMI (55bps)")
    print("=" * 78)
    print(f"{'symbol':>10} | {'n':>5} {'mean_R':>8} {'win%':>6} {'totR':>9}")
    for sym in SYMBOLS:
        if sym not in per_symbol:
            continue
        sub = apply_cost(per_symbol[sym], 55)
        s = summ(sub)
        print(f"{sym:>10} | {s['n']:>5} {s['mean_R']:>8.3f} {s['win']:>6.1f} {s['total_R']:>9.1f}")

    # proximity k=0.25 robustness
    print("\n" + "=" * 78)
    print("6) PROXIMITY ROBUSTNESS — k=0.25 (55bps)")
    print("=" * 78)
    tight = []
    for sym in SYMBOLS:
        df = load(con, sym)
        if df.empty or len(df) < 5000:
            continue
        va = build_va_map(df)
        tight.extend(simulate_symbol(df, va, prox_k=0.25))
    s = summ(apply_cost(tight, 55))
    print(f"  k=0.25: n={s['n']} mean_R={s['mean_R']:+.3f} win={s['win']:.1f}% "
          f"totR={s['total_R']:.1f} Sharpe={s['sharpe']:.2f}")

    print("\n" + "=" * 78)
    print("7) FEE-AWARE STOP FLOOR — micro-stop fee erozyonuna karşı (memory shield)")
    print("   Stop'u en az sl_pct_min uzağa it; hedef R doğal POC/VAH'ta kalır.")
    print("=" * 78)
    print(f"{'sl_min':>8} | {'n':>5} {'mean_R0':>8} {'mean_R55':>9} {'mean_R100':>10} {'win%':>6} {'Sharpe55':>9}")
    for slmin in [0.005, 0.010, 0.020, 0.030]:
        ft = []
        for sym in SYMBOLS:
            df = load(con, sym)
            if df.empty or len(df) < 5000:
                continue
            va = build_va_map(df)
            ft.extend(simulate_symbol(df, va, sl_pct_min=slmin))
        s0 = summ(apply_cost(ft, 0))
        s55 = summ(apply_cost(ft, 55))
        s100 = summ(apply_cost(ft, 100))
        print(f"{slmin:>8.3f} | {s55['n']:>5} {s0['mean_R']:>8.3f} {s55['mean_R']:>9.3f} "
              f"{s100['mean_R']:>10.3f} {s55['win']:>6.1f} {s55['sharpe']:>9.2f}")

    print("\nDONE.")
    con.close()


if __name__ == "__main__":
    main()
