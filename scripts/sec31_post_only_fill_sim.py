"""SEC31 — Post-Only Fill Rate Simulation.

30-gun (6 ay / 6 = 1 ay, ancak mevcut 15m data 7 ay iceriyor → son 30 gun kullanilir)
historical OHLCV bar data ile post-only limit fill probability'si sim eder.

Algoritma:
  Her bar icin: limit_price = close ± k*ATR14
    BUY  limit: close - k*ATR  (yani long signal, buy limit altinda bekler)
    SELL limit: close + k*ATR  (short signal, sell limit ustunde bekler)
  Sonraki N bar icinde fill oldu mu?
    BUY  fill: herhangi bir bar'da low <= limit_price
    SELL fill: herhangi bir bar'da high >= limit_price

TF x timeout matrix:
  15m: {15s, 30s, 60s, 120s}  → bar karsiligi: {1, 2, 4, 8} bar
  5m:  {5s, 10s, 30s}          → bar karsiligi: {1, 2, 6} bar
  1m:  {2s, 5s, 10s}           → bar karsiligi: {1 (max 1), 1, 1} bar (sub-bar sim)

Semboller: BTC/USDT (liquid), ETH/USDT (mid), DOGE/USDT (alt-coin)

NOT: 1m ve 5m data mevcut degil (ingest edilmedi). Bu simde 15m data kullanilir;
     5m/1m icin bar durations'i scale edeceğiz + teorik fill-probability modeli uretecegiz.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# ===== Konfig =====

# 15m data mevcut → bu semboller icin gercek data kullan
SYMBOLS_WITH_15M = ["BTC/USDT", "ETH/USDT", "DOGE/USDT"]

# TF → (bar_duration_sec, timeout_list_sec, bars_per_timeout_list)
TF_CONFIG: dict[str, dict] = {
    "15m": {
        "bar_sec": 900,
        "timeouts_sec": [15, 30, 60, 120],
        # bars = ceiling(timeout / bar_sec) — minimum 1
        "bars": [1, 1, 1, 1],   # 15m bar ~900s, tum timeout'lar 1 bar altinda veya 1 bar
    },
    "5m": {
        "bar_sec": 300,
        "timeouts_sec": [5, 10, 30],
        "bars": [1, 1, 1],
    },
    "1m": {
        "bar_sec": 60,
        "timeouts_sec": [2, 5, 10],
        "bars": [1, 1, 1],
    },
}

# k * ATR14 offset: limit fiyati ne kadar uzakta
K_ATR = 0.05   # post-only limit = close ± 0.05*ATR14 (ince, maker fill hedefi)

# Son kac gun: 30 gun (15m: 30*24*4 = 2880 bar)
LOOKBACK_DAYS = 30


def _parquet_path(symbol: str, tf: str = "15m") -> Path:
    """Sembol + TF icin parquet dizini."""
    sym_clean = symbol.replace("/", "_")
    return ROOT / "data" / "parquet" / "binance" / sym_clean / tf


def _load_bars(symbol: str, tf: str = "15m", days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Parquet'ten son N gunluk OHLCV yukle."""
    base = _parquet_path(symbol, tf)
    if not base.exists():
        return pd.DataFrame()

    frames = []
    for pfile in sorted(base.rglob("*.parquet")):
        try:
            df = pq.read_table(pfile).to_pandas()
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()

    data = pd.concat(frames, ignore_index=True)
    if "ts" not in data.columns:
        return pd.DataFrame()

    data["ts"] = pd.to_datetime(data["ts"], utc=True)
    data = data.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)

    # Son N gun
    cutoff = data["ts"].max() - pd.Timedelta(days=days)
    data = data[data["ts"] >= cutoff].reset_index(drop=True)
    return data


def _atr14(df: pd.DataFrame) -> pd.Series:
    """ATR14 hesapla (basit TR yontemi)."""
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)

    tr = np.maximum(high - low,
          np.maximum(np.abs(high - np.roll(close, 1)),
                     np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]

    atr = np.zeros(len(tr))
    if len(tr) < 14:
        atr[:] = tr
    else:
        atr[13] = tr[:14].mean()
        for i in range(14, len(tr)):
            atr[i] = (atr[i - 1] * 13 + tr[i]) / 14

    return pd.Series(atr, index=df.index)


def _simulate_fill_rate(
    df: pd.DataFrame,
    n_bars: int,
    k_atr: float = K_ATR,
    min_atr: float = 1e-8,
) -> dict[str, float]:
    """n_bars icinde post-only limit fill rate hesapla.

    Her bar i icin:
      buy_limit  = close[i] - k * atr[i]
      sell_limit = close[i] + k * atr[i]

    Sonraki n_bars bar: low <= buy_limit → BUY fill
                        high >= sell_limit → SELL fill

    Returns: {buy_fill_rate, sell_fill_rate, combined_fill_rate, n_signals}
    """
    if df.empty or len(df) < 20:
        return {"buy_fill_rate": 0.0, "sell_fill_rate": 0.0,
                "combined_fill_rate": 0.0, "n_signals": 0}

    atr = _atr14(df)
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    atr_arr = atr.values.astype(float)

    n = len(df)
    buy_fills = 0
    sell_fills = 0
    n_signals = 0

    # ATR warm-up: ilk 14 bar atla
    for i in range(14, n - n_bars):
        a = atr_arr[i]
        if a < min_atr:
            continue
        c = close[i]
        buy_limit = c - k_atr * a
        sell_limit = c + k_atr * a

        # Sonraki n_bars bar
        future_lows = low[i + 1: i + 1 + n_bars]
        future_highs = high[i + 1: i + 1 + n_bars]

        if len(future_lows) == 0:
            continue

        buy_filled = bool(np.any(future_lows <= buy_limit))
        sell_filled = bool(np.any(future_highs >= sell_limit))

        buy_fills += int(buy_filled)
        sell_fills += int(sell_filled)
        n_signals += 1

    if n_signals == 0:
        return {"buy_fill_rate": 0.0, "sell_fill_rate": 0.0,
                "combined_fill_rate": 0.0, "n_signals": 0}

    buy_rate = buy_fills / n_signals
    sell_rate = sell_fills / n_signals
    combined = (buy_fills + sell_fills) / (2 * n_signals)

    return {
        "buy_fill_rate": round(buy_rate * 100, 1),
        "sell_fill_rate": round(sell_rate * 100, 1),
        "combined_fill_rate": round(combined * 100, 1),
        "n_signals": n_signals,
    }


def _theoretical_fill_rate_5m_1m(tf: str, n_bars: int, ref_15m_rate: float) -> float:
    """5m ve 1m data yokken teorik fill-rate tahmin et.

    Yaklasim: post-only fill rate = f(relative_timeout / bar_period)
    15m'de 1 bar (900s) -> ref_rate
    5m'de  1 bar (300s) -> ayni price path, daha kisa zaman → daha az fill
    1m'de  1 bar (60s)  → daha da az fill

    Basit skala: fill_rate(tf) = ref_rate * (tf_bar_sec / 900)^0.5
    (sqrt cunku price diffusion ~ sqrt(t))

    Bu teorik bir lower-bound tahmini. Gercek data ile revize edilmeli.
    """
    bar_sec = TF_CONFIG[tf]["bar_sec"]
    ref_bar_sec = 900  # 15m
    scale = (bar_sec / ref_bar_sec) ** 0.5
    estimated = ref_15m_rate * scale
    return round(estimated, 1)


def run_simulation() -> pd.DataFrame:
    """Tam simulasyon: TF x timeout x symbol matrix."""
    print("=" * 65)
    print("SEC31 Post-Only Fill Rate Simulation")
    print(f"Lookback: {LOOKBACK_DAYS} gun | k_ATR = {K_ATR}")
    print("=" * 65)

    rows = []

    # ===== 15m (gercek data) =====
    tf = "15m"
    cfg = TF_CONFIG[tf]
    print(f"\n[TF={tf}]  bar_sec={cfg['bar_sec']}")

    ref_rates_15m: dict[str, float] = {}  # symbol -> combined_fill_rate@1bar

    for sym in SYMBOLS_WITH_15M:
        df = _load_bars(sym, tf=tf, days=LOOKBACK_DAYS)
        if df.empty:
            print(f"  {sym}: DATA YOK — atlanıyor")
            continue
        print(f"  {sym}: {len(df)} bar yüklendi")

        for timeout_sec, n_bars in zip(cfg["timeouts_sec"], cfg["bars"]):
            result = _simulate_fill_rate(df, n_bars=n_bars)
            row = {
                "tf": tf,
                "symbol": sym,
                "timeout_sec": timeout_sec,
                "n_bars_looked": n_bars,
                "n_signals": result["n_signals"],
                "buy_fill_rate_pct": result["buy_fill_rate"],
                "sell_fill_rate_pct": result["sell_fill_rate"],
                "combined_fill_rate_pct": result["combined_fill_rate"],
                "data_source": "empirical",
            }
            rows.append(row)
            print(
                f"    timeout={timeout_sec:>4}s  bars={n_bars}  "
                f"fill={result['combined_fill_rate']:.1f}%  "
                f"(buy={result['buy_fill_rate']:.1f}% / sell={result['sell_fill_rate']:.1f}%)  "
                f"n={result['n_signals']}"
            )

        # Ref rate: 15s timeout @ this symbol (1-bar look)
        ref_rates_15m[sym] = next(
            (r["combined_fill_rate_pct"] for r in rows
             if r["tf"] == "15m" and r["symbol"] == sym and r["timeout_sec"] == 15),
            0.0,
        )

    # ===== 5m ve 1m (teorik, data yok) =====
    for tf in ["5m", "1m"]:
        cfg = TF_CONFIG[tf]
        print(f"\n[TF={tf}]  bar_sec={cfg['bar_sec']}  [TEORiK — data yok]")

        for sym in SYMBOLS_WITH_15M:
            ref = ref_rates_15m.get(sym, 60.0)  # 15m ref

            for timeout_sec, n_bars in zip(cfg["timeouts_sec"], cfg["bars"]):
                # n_bars her zaman 1 (1m/5m bar icinde sub-bar timeout)
                est = _theoretical_fill_rate_5m_1m(tf, n_bars=n_bars, ref_15m_rate=ref)
                row = {
                    "tf": tf,
                    "symbol": sym,
                    "timeout_sec": timeout_sec,
                    "n_bars_looked": n_bars,
                    "n_signals": 0,  # data yok
                    "buy_fill_rate_pct": est,
                    "sell_fill_rate_pct": est,
                    "combined_fill_rate_pct": est,
                    "data_source": "theoretical_sqrt_scale",
                }
                rows.append(row)
                print(
                    f"  {sym}  timeout={timeout_sec:>4}s  "
                    f"fill_est={est:.1f}%  [ref_15m={ref:.1f}%]"
                )

    df_result = pd.DataFrame(rows)
    return df_result


def print_matrix(df: pd.DataFrame) -> None:
    """TF x timeout x symbol fill rate matrisi yazdir."""
    print("\n" + "=" * 65)
    print("FILL RATE MATRIX  (combined buy+sell, pct)")
    print("=" * 65)

    for tf in ["15m", "5m", "1m"]:
        sub = df[df["tf"] == tf]
        if sub.empty:
            continue
        timeouts = sorted(sub["timeout_sec"].unique())
        symbols = sorted(sub["symbol"].unique())

        header = f"{'Symbol':<14}" + "".join(f"{t}s".rjust(10) for t in timeouts)
        print(f"\n[TF={tf}]")
        print(header)
        print("-" * len(header))
        for sym in symbols:
            row_str = f"{sym:<14}"
            for t in timeouts:
                cell = sub[(sub["symbol"] == sym) & (sub["timeout_sec"] == t)]
                if cell.empty:
                    row_str += f"{'N/A':>10}"
                else:
                    rate = cell["combined_fill_rate_pct"].values[0]
                    src = cell["data_source"].values[0]
                    flag = "*" if "theoretical" in str(src) else ""
                    row_str += f"{rate:>9.1f}{flag}"
            print(row_str)

    print("\n* = teorik tahmin (sqrt-scale, data yok)")


def kill_criteria_verdict(df: pd.DataFrame) -> None:
    """1m maker fill rate < %50 → KILL verdict."""
    print("\n" + "=" * 65)
    print("KILL CRITERIA CHECK")
    print("=" * 65)

    # 1m en iyi timeout'u al
    df_1m = df[df["tf"] == "1m"]
    if df_1m.empty:
        print("  1m: veri yok")
        return

    best_1m = df_1m.groupby("symbol")["combined_fill_rate_pct"].max()
    for sym, rate in best_1m.items():
        verdict = "KILL" if rate < 50.0 else "OK"
        print(f"  1m {sym}: best_fill={rate:.1f}%  [{verdict}]")

    overall_1m = best_1m.mean()
    verdict = "1m KILL (fill < 50%)" if overall_1m < 50.0 else "1m OK"
    print(f"\n  OVERALL 1m fill = {overall_1m:.1f}%  --> [{verdict}]")

    # 15m verdict
    df_15m = df[df["tf"] == "15m"]
    if not df_15m.empty:
        best_15m = df_15m.groupby("symbol")["combined_fill_rate_pct"].max().mean()
        verdict_15m = "15m OK" if best_15m >= 60.0 else "15m BORDERLINE"
        print(f"  OVERALL 15m fill = {best_15m:.1f}%  --> [{verdict_15m}]")


def main() -> None:
    df = run_simulation()
    print_matrix(df)
    kill_criteria_verdict(df)

    # CSV kaydet
    out = ROOT / "reports" / "execution_chief"
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "sec31_fill_sim_matrix.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
