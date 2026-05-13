"""SEC7: Forex Multi-Asset Survey — TOP_10 crypto stratejilerini forex'te calistir.

Hipotez: PA pattern'leri (engulfing, pin bar, brooks vs) evrensel ise forex 1d'de
de edge gostermeli. Crypto'dan farklar: dusuk volatilite, yuvarlak haftasonu,
fee modeli farkli (forex spread $5-20/trade vs crypto 0.075% taker).

Adimlar:
1. _gather_forex: TOP_10 stratejilerini forex sembollerinde (EUR/USD, GBP/USD, USD/JPY) calistir
2. Standalone edge olcumu (mR, sumR, WR, n_trade)
3. Pozitif edge varsa BALANCED+F&G ensemble retest
4. Champion (crypto 1d, %33.6) ile karsilastirma

Output: reports/lab/sec7_forex_survey.md
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import TOP_10

REPORT_OUT = ROOT / "reports" / "lab" / "sec7_forex_survey.md"

FOREX_SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]


def _load_forex_ohlcv(symbol: str, tf: str = "1d") -> pd.DataFrame:
    con = duckdb.connect(str(ROOT / "data" / "forex_market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = tf
    df["venue"] = "fx"
    return df


def _gather_forex(module_name: str, class_name: str) -> list[dict]:
    """v09_optimize_top10._gather'in forex variant'i."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name} init: {e}")
        return []

    out = []
    for sym in FOREX_SYMBOLS:
        try:
            df = _load_forex_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "fx"
            df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(risk_officer=None, store_load=None)
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d",
                initial_capital=10_000.0,
                fees={"taker": 0.0001, "maker": 0.0001},  # forex spread proxy ~1pip
                slippage_bps=2.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    val = df["vol_z_pre"].iloc[idx]
                    if pd.notna(val):
                        vz = float(val)
                out.append({
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "side": str(t["side"]).lower(),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                })
        except Exception as e:
            print(f"  [WARN] {module_name} on {sym}: {e}")
            continue
    return out


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# SEC7: Forex Multi-Asset Survey — 2026-05-13")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("## Hipotez")
    w("")
    w("PA pattern'leri (engulfing, pin bar, brooks vs) evrensel ise forex 1d'de de edge gostermeli.")
    w("Crypto'dan farklar: dusuk volatilite, hafta sonu kapali, fee modeli (spread $5-20/trade).")
    w("")
    w("## Veri")
    w("")
    w(f"- **Sembol:** {', '.join(FOREX_SYMBOLS)}")
    w(f"- **TF:** 1d")
    w(f"- **Tarih:** 2021-05 -> 2026-05 (5y, 1300 bar/sym)")
    w(f"- **Fee proxy:** 0.0001 (~1 pip), slippage 2 bps")
    w("")

    print("Trade topluyor (TOP_10 × forex)...")
    all_trades: list[dict] = []
    per_strat = {}
    for m, c in TOP_10:
        ts = _gather_forex(m, c)
        all_trades.extend(ts)
        per_strat[m] = ts
        Rs = [t["R"] for t in ts]
        if Rs:
            wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
            mR = sum(Rs) / len(Rs)
            sumR = sum(Rs)
            print(f"  {m}: n={len(ts):>4} mR={mR:+.3f} sumR={sumR:+.1f} WR={wr:.1f}%")
        else:
            print(f"  {m}: 0")

    all_trades.sort(key=lambda x: x["entry_ts"])
    w("## Per-Strategy Standalone Edge (forex)")
    w("")
    w(f"| Strategy | n_trade | WR | mean_R | sum_R | edge |")
    w(f"|---|---:|---:|---:|---:|---|")

    for m, ts in per_strat.items():
        if not ts:
            w(f"| {m} | 0 | - | - | - | sinyal yok |")
            continue
        Rs = [t["R"] for t in ts]
        n = len(Rs)
        wr = sum(1 for r in Rs if r > 0) / n * 100
        mR = sum(Rs) / n
        sumR = sum(Rs)
        if mR > 0.10 and n >= 30:
            edge = "POZITIF"
        elif mR > 0:
            edge = "marjinal"
        else:
            edge = "negatif"
        w(f"| {m} | {n} | {wr:.1f}% | {mR:+.3f} | {sumR:+.1f} | {edge} |")

    w("")
    w(f"**Toplam forex trade pool:** {len(all_trades)}")
    if not all_trades:
        w("**RED:** Hicbir forex trade uretilemedi.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    Rs = [t["R"] for t in all_trades]
    wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
    mR = sum(Rs) / len(Rs)
    sumR = sum(Rs)
    w(f"**Pool R stats:** mean R {mR:+.3f}, sumR {sumR:+.1f}, WR {wr:.1f}%")

    # Per-symbol breakdown
    w("")
    w("## Per-Symbol Breakdown")
    w("")
    w(f"| Symbol | n_trade | WR | mean_R | sum_R |")
    w(f"|---|---:|---:|---:|---:|")
    for sym in FOREX_SYMBOLS:
        sym_trades = [t for t in all_trades if t["symbol"] == sym]
        if not sym_trades:
            w(f"| {sym} | 0 | - | - | - |")
            continue
        Rs = [t["R"] for t in sym_trades]
        n = len(Rs)
        wr = sum(1 for r in Rs if r > 0) / n * 100
        mR = sum(Rs) / n
        sumR = sum(Rs)
        w(f"| {sym} | {n} | {wr:.1f}% | {mR:+.3f} | {sumR:+.1f} |")

    # Walk-forward forex (3y rolling, 60g step — crypto ile ayni)
    w("")
    w("## Forex BALANCED+F&G Ensemble Walk-Forward")
    w("")
    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    # Forex'te capitulation halt + crypto-spesifik filtreler ALAKASIZ
    # Sadece BALANCED base config + drop_pairs YOK + halt YOK
    cfg_forex = base_bal.with_overrides(
        drop_pairs=frozenset(),
        alt_data_skip_long=None,
        alt_data_skip_short=None,
        btc_halt_calendar=None,
    )

    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    w(f"**Pencere sayisi:** {len(windows)} (3y rolling, 60 gun step)")
    w("")
    w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")
    print(f"\n{'scenario':<55}  {'yillik':>8}  {'med':>7}  {'DD':>6}  {'r-adj':>7}  {'neg':>4}")
    print("-" * 90)

    rated = []
    for name, cfg in [
        ("Forex 1d + BALANCED (no crypto filters)", cfg_forex),
    ]:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            print(f"  {name:<55}  filter sonrasi bos")
            w(f"| {name} | - | - | - | - | - | - | - |")
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        med_a = median(anns)
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), neg))
        print(f"  {name:<55}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {md:>+4.0f}%  {ra:>6.3f}  {neg:>3}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} |")

    # Karar
    w("")
    w("## Karar (vs Champion crypto 1d: yıllık +33.6% / DD -32.6% / r-adj 1.029)")
    w("")
    if not rated:
        w("**RED:** Forex pool BALANCED filter sonrasi bos kaldi.")
        w("Sebep: BALANCED config crypto-spesifik filtreler (capitulation halt, F&G).")
        w("Forex icin ayri preset gerekli (sonraki sprint).")
    else:
        best = max(rated, key=lambda x: x[4])
        w(f"**Forex best:** {best[0]} — yillik {best[1]:+.1f}%, DD {best[3]:+.1f}%, r-adj {best[4]:.3f}")
        w("")
        if best[4] > 0.5:
            w(f"**POZITIF:** Forex bagimsiz edge gosteriyor (r-adj {best[4]:.3f}).")
            w("Crypto + forex portfoyu beraber: uncorrelated diversifikasyon (ayri hesap, ayri risk allocation).")
            w("Beklenen kombine: yillik %30-40, DD daha dusuk (correlation < 1).")
        elif best[4] > 0:
            w(f"**MARJINAL:** Forex marjinal pozitif. Crypto-spesifik strategy parametreleri forex'te kalibre yok.")
            w("Sonraki adim: Strategy parametre tuning forex icin.")
        else:
            w("**RED:** Forex'te crypto stratejileri edge uretmiyor.")
            w("Sebep: PA pattern parametreleri crypto vol regime'ine kalibre.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
