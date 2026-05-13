"""SEC6: 4h Primary Timeframe Pivot — TOP_10 stratejilerini 4h'de calistir + BALANCED retest.

Hipotez: 1d pool 4787 trade ile lokal optimum. 4h ile 6x daha cok bar = farkli vol regime,
yeni edge potansiyeli.

Adimlar:
1. _gather_4h: TOP_10 stratejilerini 4h OHLCV ile calistir
2. Trade pool karsilastirmasi (1d vs 4h trade sayilari)
3. BALANCED+F&G ile 4h ensemble walk-forward (13 pencere 3y rolling)
4. CHAMPION (1d) vs CHALLENGER (4h) karari

Output: reports/lab/sec6_4h_pivot_2026-05-13.md
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import TOP_10, SYMBOLS_11
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip

REPORT_OUT = ROOT / "reports" / "lab" / "sec6_4h_pivot_2026-05-13.md"


def _gather_tf(module_name, class_name, tf="4h"):
    """v09_optimize_top10._gather'in tf-parametreli versiyonu."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name}.{class_name} init: {e}")
        return []

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf=tf)
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = tf
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
                timeframe=tf,
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
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
                    pre = df.loc[mask, "vol_z_pre"]
                    if not pre.empty:
                        vz_val = pre.iloc[-1]
                        if pd.notna(vz_val):
                            vz = float(vz_val)
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

    w("# SEC6: 4h Primary Timeframe Pivot — 2026-05-13")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("## Hipotez")
    w("")
    w("1d pool 4787 trade ile lokal optimum (3 sprint zincir kanit). 4h ile 6x daha cok bar = farkli vol regime ve mikro-structure -> yeni edge potansiyeli.")
    w("")
    w("## Trade Toplama (TOP_10 × 11 sym × 4h)")
    w("")
    print("Trade topluyor (TOP_10 × 4h)...")
    all_trades_4h: list[dict] = []
    for m, c in TOP_10:
        ts = _gather_tf(m, c, tf="4h")
        all_trades_4h.extend(ts)
        w(f"- {m}: **{len(ts)}** trade")
        print(f"  {m}: {len(ts)}")

    all_trades_4h.sort(key=lambda x: x["entry_ts"])
    w("")
    w(f"**Toplam 4h trade pool:** {len(all_trades_4h)}")
    w(f"**1d baseline trade pool:** 4787")
    if len(all_trades_4h) > 0:
        ratio = len(all_trades_4h) / 4787
        w(f"**Pool buyume:** {ratio:.2f}x (target ~6x)")

    if len(all_trades_4h) < 100:
        w("")
        w("**HATA:** 4h pool yetersiz (< 100 trade). Strategy'ler 4h ile uyumsuz olabilir.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    # Quick stats
    Rs = [t["R"] for t in all_trades_4h]
    wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
    w("")
    w(f"**4h pool R stats:** mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")

    # Walk-forward
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    combined_short_skip = {**fund_short_dict, **dict(fng_short_20)}

    # 4h data sadece 3y (2023-05 -> 2026-05), pencere yapisi 3y'a sigmaz.
    # 4h-specific: 2y train + 3mo OOS + 1mo step
    start = all_trades_4h[0]["entry_ts"]
    end = all_trades_4h[-1]["exit_ts"]
    windows = []
    cur = start
    train_days = 2 * 365
    while cur + pd.Timedelta(days=train_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=30)
    w("")
    w(f"**Pencere sayisi:** {len(windows)} (2y rolling, 30 gun step — 4h-specific cunku data 3y)")
    w(f"**4h pool araligi:** {start} -> {end}")
    w("")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    overrides = dict(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
    )

    # Senaryolar:
    # - CHAMPION (1d): mevcut BALANCED+F&G (sadece reference, 1d trades ile)
    # - CHALLENGER 4h-A: BALANCED+F&G + 4h trades + max_conc=8 default
    # - CHALLENGER 4h-B: + max_conc=20 (4h pool 6x buyuk, default cok dar olabilir)
    # - CHALLENGER 4h-C: + max_conc=20 + per_symbol_cooldown=0 (4h cooldown 1d ayni iken anlamsiz)
    scenarios = [
        ("4h + BALANCED+F&G (max_conc=8 default)",
         all_trades_4h,
         base_bal.with_overrides(**overrides)),
        ("4h + BALANCED+F&G (max_conc=20)",
         all_trades_4h,
         base_bal.with_overrides(max_concurrent=20, **overrides)),
        ("4h + BALANCED+F&G (max_conc=20, cooldown=0)",
         all_trades_4h,
         base_bal.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0, **overrides)),
    ]

    w("## Sonuclar")
    w("")
    w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")
    print(f"\n{'scenario':<55}  {'yillik':>8}  {'med':>7}  {'min':>7}  {'max':>7}  {'DD':>6}  {'r-adj':>7}  {'neg':>4}")
    print("-" * 115)

    rated = []
    for name, trades, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in trades if ws <= t["entry_ts"] < we]
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
        print(f"  {name:<55}  {ma:>+6.1f}%  {med_a:>+5.1f}%  {min(anns):>+5.1f}%  {max(anns):>+5.1f}%  {md:>+4.0f}%  {ra:>6.3f}  {neg:>3}")
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | {md:+.1f}% | {ra:.3f} | {neg} |")

    # Karar
    w("")
    w("## Karar (vs Champion 1d: yıllık +33.6% / DD -32.6% / r-adj 1.029)")
    w("")
    if not rated:
        w("**RED:** Hicbir 4h senaryo calismadi.")
    else:
        best = max(rated, key=lambda x: x[4])  # max r-adj
        w(f"**Best 4h senaryo:** {best[0]} — yillik {best[1]:+.1f}%, DD {best[3]:+.1f}%, r-adj {best[4]:.3f}")
        w("")
        if best[4] > 1.029:
            w(f"**TOURNAMENT WINNER:** 4h pivot Champion'i yendi (r-adj +{best[4]-1.029:.3f}).")
            w("-> v1.1 release adayy, manual onay gerekli.")
        elif best[4] > 0.95:
            w("**MARJINAL:** 4h marjinal yakin (r-adj 0.95-1.03 araliginda) — paper trading dogrulamali.")
        else:
            w(f"**CHAMPION CONFIRMED:** 1d preset 4h'tan iyi (r-adj 1.029 vs {best[4]:.3f}).")
            w("-> Production lock korundu, 4h yolu archive.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
