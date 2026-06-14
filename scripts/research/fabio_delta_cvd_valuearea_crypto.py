"""Fabio order-flow delta/CVD + Value-Area ABLATION backtest (crypto).

HYP-2026-06-01-fabio-delta-cvd-valuearea-crypto (pre-registered).

ASIL SORU: Önceki tur value-area'yı TEK BAŞINA test etti → RED (0bps yön ≈ shuffle, p=0.50).
Eksik olan ORDER FLOW onayı (bar-bazlı signed delta / CVD). Bu script onu ekler ve ABLATION
yapar:
  (a) value-area TEK BAŞINA   — önceki RED baseline
  (b) value-area + delta onayı — VAL long yalnız delta/CVD pozitife döndüyse,
                                  VAH short yalnız delta/CVD negatife döndüyse
  (c) sadece delta/CVD momentum (value-area YOK)

Delta order-flow onayı (b), (a)'nın üstüne EDGE EKLİYOR mu? → mean_R_after_fees farkı +
shuffle p-değeri (her varyant kendi shuffle'ı). 12 ay küçük örneklem — multiple-testing
paranoyak (Bonferroni ham-p < 0.004 eşiği).

VERİ: data/_fabio_delta_klines/<SYM>_<tf>.parquet (taker-buy klines, self-contained OHLCV+delta).
  delta_bar = 2*taker_buy - volume. CVD = cumsum(delta), takvim-günü reset.

LOOKAHEAD-GÜVENLİ:
  - VA SADECE önceki kapanmış gün (t-1 günü) barlarından.
  - Sinyal bar t kapanışında değerlendirilir, AMA delta-onay t-1 bar'ın delta'sı /
    t-1'e kadar CVD ile (t bar delta'sı KULLANILMAZ → giriş t+1 open).
  - Intrabar stop/target çakışmasında STOP önce (konservatif).
  - shift(-1) / center=True YOK.
  - Shuffle baseline: yön rastgele → gizli lookahead olsaydı shuffle gerçeği yenemezdi.

Reproduce: .venv/bin/python scripts/research/fabio_delta_cvd_valuearea_crypto.py
Deploy YOK. Canlı config/daemon DOKUNULMADI.
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

ROOT = Path(__file__).resolve().parents[2]
KLINES = ROOT / "data" / "_fabio_delta_klines"

SYMS = {"BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT"}
VA_PCT = 0.70
N_BINS = 50
ATR_LEN = 14
PROX_K = 0.5
STOP_M = 0.5
RR_CAP = 4.0
MAX_HOLD = 96     # 5m: 8h; 15m'de 24h (scalp/gün-içi)
SL_PCT_MIN = 0.0  # fee-aware floor opsiyonel
SEED = 7


def session_of(hour_utc: int) -> str:
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 21:
        return "NY"
    if 0 <= hour_utc < 7:
        return "Asia"
    return "Off"


def load(fsym, tf):
    df = pd.read_parquet(KLINES / f"{fsym}_{tf}.parquet").copy()
    df = df.set_index("ts")
    df["day"] = df.index.tz_convert("UTC").tz_localize(None).normalize()
    df["hour"] = df.index.hour
    df["session"] = df["hour"].map(session_of)
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_LEN, min_periods=ATR_LEN).mean()
    # CVD: takvim-günü reset (intraday akış). delta zaten parquet'te.
    df["cvd"] = df.groupby("day")["delta"].cumsum()
    # delta-momentum: son 3 bar delta toplamı (t bar dahil — kullanırken t-1 shift edilir)
    df["delta_mom3"] = df["delta"].rolling(3, min_periods=1).sum()
    return df


def value_area_for_day(day_df):
    lo = float(day_df["low"].min()); hi = float(day_df["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, N_BINS + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    vol = np.zeros(N_BINS)
    bl = day_df["low"].values; bh = day_df["high"].values; bv = day_df["volume"].values
    bin_w = (hi - lo) / N_BINS
    for i in range(len(bl)):
        if bh[i] <= bl[i] or bv[i] <= 0:
            continue
        i0 = max(0, int((bl[i] - lo) / bin_w))
        i1 = min(N_BINS - 1, int((bh[i] - lo) / bin_w))
        span = i1 - i0 + 1
        if span <= 0:
            continue
        vol[i0:i1 + 1] += bv[i] / span
    if vol.sum() <= 0:
        return None
    poc_idx = int(np.argmax(vol)); poc = centers[poc_idx]
    total = vol.sum(); target = VA_PCT * total
    lo_i = hi_i = poc_idx; acc = vol[poc_idx]
    while acc < target and (lo_i > 0 or hi_i < N_BINS - 1):
        up = vol[hi_i + 1] if hi_i < N_BINS - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1; acc += vol[hi_i]
        else:
            lo_i -= 1; acc += vol[lo_i]
    return poc, centers[lo_i], centers[hi_i]


def build_va_map(df):
    va = {}
    for day, g in df.groupby("day"):
        r = value_area_for_day(g)
        if r is not None:
            va[day] = r
    return va


def _exec_trade(o, h, l, c, atr, n, i, sig, val, vah, poc, sl_pct_min, max_hold):
    """Ortak yürütme: giriş i+1 open, stop/target, intrabar STOP-önce."""
    if i + 1 >= n:
        return None
    entry = o[i + 1]
    a = atr[i]
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(a) or a <= 0:
        return None
    if sig == "long":
        stop = val - STOP_M * a
        if sl_pct_min > 0:
            stop = min(stop, entry * (1.0 - sl_pct_min))
        tgt = poc if poc > entry else vah
        risk = entry - stop
    else:
        stop = vah + STOP_M * a
        if sl_pct_min > 0:
            stop = max(stop, entry * (1.0 + sl_pct_min))
        tgt = poc if poc < entry else val
        risk = stop - entry
    if risk <= 0:
        return None
    reward = abs(tgt - entry)
    rr = reward / risk
    if rr < 0.3:
        return None
    rr = min(rr, RR_CAP)
    tgt = entry + rr * risk if sig == "long" else entry - rr * risk
    outcome_R = None; exit_idx = None
    for j in range(i + 1, min(i + 1 + max_hold, n)):
        hj, lj = h[j], l[j]
        if sig == "long":
            hit_stop = lj <= stop; hit_tgt = hj >= tgt
        else:
            hit_stop = hj >= stop; hit_tgt = lj <= tgt
        if hit_stop:
            outcome_R = -1.0; exit_idx = j; break
        if hit_tgt:
            outcome_R = rr; exit_idx = j; break
    if outcome_R is None:
        j = min(i + max_hold, n - 1)
        last = c[j]
        outcome_R = ((last - entry) / risk) if sig == "long" else ((entry - last) / risk)
        exit_idx = j
    return entry, stop, rr, risk / entry, outcome_R, exit_idx


def simulate(df, va, variant, prox_k=PROX_K, seed=None, sl_pct_min=SL_PCT_MIN,
             max_hold=MAX_HOLD, delta_lookback=1):
    """variant: 'va_only' | 'va_delta' | 'delta_only'.

    delta_lookback: onayda kullanılan delta/CVD t-delta_lookback bar'a kadar (lookahead-güvenli).
    seed: shuffle baseline (yön rastgele).
    """
    rng = np.random.default_rng(seed) if seed is not None else None
    days = sorted(va.keys())
    day_to_prev = {days[i]: days[i - 1] for i in range(1, len(days))}

    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    atr = df["atr"].values; sess = df["session"].values; dayarr = df["day"].values
    cvd = df["cvd"].values; delta = df["delta"].values; dmom = df["delta_mom3"].values
    idx = df.index
    n = len(df)
    trades = []
    i = 1  # i>=delta_lookback gerekiyor; delta_lookback=1 → i>=1
    while i < n - 2:
        if i < delta_lookback:
            i += 1; continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            i += 1; continue

        # --- delta/CVD onay sinyalleri (LOOKAHEAD-GÜVENLİ: t-delta_lookback'e kadar) ---
        # CVD eğimi: cvd[i-lb] - cvd[i-lb-1] (t bar'ın delta'sı YOK)
        lb = delta_lookback
        prev_delta = delta[i - lb]           # t-1 bar delta'sı
        prev_dmom = dmom[i - lb]             # t-1'e kadar 3-bar delta momentum
        # CVD yön değişimi: t-1 ve t-2 deltası → momentum işareti zaten kapsıyor
        buyer_flow = (prev_delta > 0) or (prev_dmom > 0)   # alıcı baskısı geliyor
        seller_flow = (prev_delta < 0) or (prev_dmom < 0)  # satıcı baskısı geliyor

        sig = None
        if variant in ("va_only", "va_delta"):
            dkey = pd.Timestamp(dayarr[i])
            prevd = day_to_prev.get(dkey)
            if prevd is None or prevd not in va:
                i += 1; continue
            poc, val, vah = va[prevd]
            close_i = c[i]; low_i = l[i]; high_i = h[i]
            if low_i <= val and close_i > val and abs(close_i - val) < prox_k * a:
                sig = "long"
            elif high_i >= vah and close_i < vah and abs(close_i - vah) < prox_k * a:
                sig = "short"
            if sig is None:
                i += 1; continue
            if variant == "va_delta":
                # delta onayı: yön ile akış uyumlu olmalı
                if sig == "long" and not buyer_flow:
                    i += 1; continue
                if sig == "short" and not seller_flow:
                    i += 1; continue
        else:  # delta_only — value-area yok, saf delta momentum
            poc = val = vah = None
            # giriş: delta momentum güçlü yön değişimi (t-1'e kadar)
            # long: önceki bar delta>0 ve 3-bar momentum pozitif (akış alıcıya döndü)
            if prev_delta > 0 and prev_dmom > 0:
                sig = "long"
            elif prev_delta < 0 and prev_dmom < 0:
                sig = "short"
            if sig is None:
                i += 1; continue
            # value-area olmadığı için stop/target ATR-bazlı (1R stop, RR_CAP hedef)
            entry_px = o[i + 1] if i + 1 < n else None
            if entry_px is None or not np.isfinite(entry_px) or entry_px <= 0:
                i += 1; continue
            if sig == "long":
                val = entry_px - STOP_M * a   # stop seviyesi proxy
                vah = entry_px + RR_CAP * STOP_M * a
                poc = entry_px + RR_CAP * STOP_M * a
            else:
                vah = entry_px + STOP_M * a
                val = entry_px - RR_CAP * STOP_M * a
                poc = entry_px - RR_CAP * STOP_M * a

        # shuffle / flip
        if rng is not None:
            sig = "long" if rng.random() < 0.5 else "short"

        res = _exec_trade(o, h, l, c, atr, n, i, sig, val, vah, poc, sl_pct_min, max_hold)
        if res is None:
            i += 1; continue
        entry, stop, rr, sl_pct, outcome_R, exit_idx = res
        trades.append({
            "entry_ts": idx[i + 1], "exit_ts": idx[exit_idx], "session": sess[i],
            "month": pd.Timestamp(idx[i]).strftime("%Y-%m"), "dir": sig,
            "R": outcome_R, "sl_pct": sl_pct, "rr": rr,
        })
        i = exit_idx + 1
    return trades


def apply_cost(trades, extra_bps):
    out = []
    for t in trades:
        slp = t["sl_pct"]
        extra_R = (extra_bps / (slp * 10000.0)) if slp > 0 else 0.0
        out.append({**t, "R_net": t["R"] - extra_R})
    return out


def calendar_sharpe(trades, key="R_net"):
    if not trades:
        return 0.0
    df = pd.DataFrame(trades)
    df["day"] = pd.to_datetime(df["exit_ts"]).dt.normalize()
    daily = df.groupby("day")[key].sum()
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
    eq = np.cumsum(r); peak = np.maximum.accumulate(eq); dd = (eq - peak).min()
    return dict(n=len(df), mean_R=float(r.mean()), win=float((r > 0).mean() * 100),
                maxdd=float(dd), total_R=float(r.sum()),
                sharpe=calendar_sharpe(trades, key))


def collect(tf, variant, prox_k=PROX_K, seed=None, sl_pct_min=SL_PCT_MIN, cache=None):
    """Tüm sembollerden trade topla. cache: {(fsym,tf): (df,va)} hızlandırma."""
    allt = []
    for ccxt_sym, fsym in SYMS.items():
        if cache is not None and (fsym, tf) in cache:
            df, va = cache[(fsym, tf)]
        else:
            df = load(fsym, tf)
            va = build_va_map(df)
            if cache is not None:
                cache[(fsym, tf)] = (df, va)
        allt.extend(simulate(df, va, variant, prox_k=prox_k, seed=seed, sl_pct_min=sl_pct_min,
                             max_hold=(MAX_HOLD if tf == "5m" else 96)))
    return allt


def shuffle_p(tf, variant, real_mean, bps, cache, n_seed=50):
    means = []
    for sd in range(n_seed):
        st = collect(tf, variant, seed=2000 + sd, cache=cache)
        sc = apply_cost(st, bps)
        means.append(np.mean([t["R_net"] for t in sc]) if sc else 0.0)
    means = np.array(means)
    p = float((means >= real_mean).mean())
    return p, means.mean(), means.std()


def main():
    print("=" * 84)
    print("FABIO DELTA/CVD + VALUE-AREA ABLATION — CRYPTO ORDER-FLOW")
    print("HYP-2026-06-01-fabio-delta-cvd-valuearea-crypto")
    print("Veri: taker-buy klines (fapi idx9), BTC/ETH/SOL, ~13 ay, 5m+15m")
    print("delta=2*taker_buy-vol ; CVD=cumsum(delta) gün-reset ; onay t-1 bar (lookahead-safe)")
    print("=" * 84)

    cache = {}
    BPS = 55  # ana karar maliyeti

    for tf in ["5m", "15m"]:
        print("\n" + "#" * 84)
        print(f"### TIMEFRAME = {tf}")
        print("#" * 84)

        variants = {
            "a_va_only": "va_only",
            "b_va_delta": "va_delta",
            "c_delta_only": "delta_only",
        }
        results = {}
        for label, v in variants.items():
            tr = collect(tf, v, cache=cache)
            results[label] = tr

        print(f"\n--- ABLATION TABLOSU (tf={tf}) ---")
        print(f"{'variant':>14} | {'n':>6} {'meanR_0':>9} {'meanR_55':>9} {'meanR_100':>10} "
              f"{'win%_55':>8} {'Sharpe55':>9} {'shuf_p_0':>9} {'shuf_p_55':>9}")
        for label in ["a_va_only", "b_va_delta", "c_delta_only"]:
            tr = results[label]
            s0 = summ(apply_cost(tr, 0))
            s55 = summ(apply_cost(tr, 55))
            s100 = summ(apply_cost(tr, 100))
            v = variants[label]
            p0, _, _ = shuffle_p(tf, v, s0["mean_R"], 0, cache)
            p55, _, _ = shuffle_p(tf, v, s55["mean_R"], 55, cache)
            print(f"{label:>14} | {s55['n']:>6} {s0['mean_R']:>9.4f} {s55['mean_R']:>9.4f} "
                  f"{s100['mean_R']:>10.4f} {s55['win']:>8.1f} {s55['sharpe']:>9.2f} "
                  f"{p0:>9.3f} {p55:>9.3f}")

        # ASIL KARŞILAŞTIRMA: (b) - (a) delta katkısı (0bps, fee bağımsız yön-edge)
        a0 = summ(apply_cost(results["a_va_only"], 0))["mean_R"]
        b0 = summ(apply_cost(results["b_va_delta"], 0))["mean_R"]
        a55 = summ(apply_cost(results["a_va_only"], 55))["mean_R"]
        b55 = summ(apply_cost(results["b_va_delta"], 55))["mean_R"]
        print(f"\n  DELTA KATKISI (b−a): 0bps {b0-a0:+.4f}  | 55bps {b55-a55:+.4f}")

        # walk-forward: aylık OOS (b varyantı, 55bps)
        print(f"\n--- WALK-FORWARD aylık OOS (b_va_delta, 55bps, tf={tf}) ---")
        tc = apply_cost(results["b_va_delta"], 55)
        months = sorted(set(t["month"] for t in tc))
        pos = 0
        line = []
        for m in months:
            sub = [t for t in tc if t["month"] == m]
            s = summ(sub)
            if s["mean_R"] > 0:
                pos += 1
            line.append(f"{m}:{s['mean_R']:+.2f}(n{s['n']})")
        print("  " + "  ".join(line))
        print(f"  pozitif ay: {pos}/{len(months)}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
