"""SEC28: Phoenix v2.0.4 1h Primary Timeframe Pivot.

Hipotez: SEC28 (2026-05-16) Phoenix 4h r-adj 2.923 (1d 6.26 üstün ama beklenenden iyi).
1h'de fee/slippage erosion 4x daha ağır → 4h sonucundan daha kötü beklenir,
ama Phoenix'in pyramid+side-cond avantajı 1h'de de kısmen korunabilir mi?

Champion reference: Phoenix v2.0.4 1d = yıllık +%200.3 / DD -%32 / r-adj 6.26 / WR %69.7
4h reference: Phoenix v2.0.4 4h = yıllık +%68.2 / DD -%23.3 / r-adj 2.923 / WR %49.1

Adımlar:
1. PHOENIX_STRATEGIES (10) × SYMBOLS_10 trade collect (peak_R enriched) — tf=1h
2. configs/risk_phoenix_v204.yaml ile production_replay
3. Rolling walk-forward (2y train + 3mo OOS + 1mo step)
4. Phoenix 1d vs 4h vs 1h karşılaştırma

Output: reports/lab/sec28_phoenix_1h_pivot_2026-05-16.md
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.backtest.lab import ProductionConfig, production_replay, _lazy_build_funding_filters
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v097_balanced_optimization import build_fng_short_skip


REPORT_OUT = ROOT / "reports" / "lab" / "sec28_phoenix_1h_pivot_2026-05-16.md"

# Phoenix v2.0.4: 11 sym - MATIC (4h yok) = 10 sym
SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]

# Phoenix v2.0.4: TOP_10 - wyckoff + FVG = 10 strateji
PHOENIX_STRATEGIES = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    # ("wyckoff_phase_d", "WyckoffPhaseDStrategy"),  # 🔥 PHOENIX DISABLED
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("fvg_fill_reversal", "FVGFillReversalStrategy"),
]


def _gather_4h_peakR(module_name: str, class_name: str) -> list:
    """Phoenix 1h gather — peak_R enriched (pyramid için kritik)."""
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name, None)
        if cls is None:
            for name in dir(mod):
                if name.endswith("Strategy") and not name.startswith("_"):
                    cls = getattr(mod, name)
                    break
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn or not cls:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  {module_name}: SKIP ({e})")
        return []

    out = []
    for sym in SYMBOLS_10:
        try:
            df = _load_symbol_ohlcv(sym, tf="1h")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1h"
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
                timeframe="1h",
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                entry_price = float(t["entry_price"])
                initial_sl = float(t["initial_sl"])
                mfe_pct = float(t.get("mfe_pct", 0))
                risk_pct = abs(initial_sl - entry_price) / entry_price if entry_price > 0 else 0.04
                side = str(t["side"]).lower()
                if side == "long":
                    peak_R = mfe_pct / risk_pct if risk_pct > 0 else 0
                else:
                    peak_R = -mfe_pct / risk_pct if risk_pct > 0 else 0
                final_R = float(t["realized_r_multiple"])
                peak_R = max(peak_R, final_R)

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
                    vz_val = df["vol_z_pre"].iloc[idx]
                    vz = float(vz_val) if not pd.isna(vz_val) else 0.0
                out.append({
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": entry_price,
                    "initial_sl": initial_sl,
                    "R": final_R,
                    "peak_R": peak_R,
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                })
        except Exception as ex:
            print(f"  {module_name}/{sym}: ERR {ex}")
            continue
    return out


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# SEC28: Phoenix v2.0.4 — 1h Primary Timeframe Pivot")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("## Champion Baseline (1d, RESUME.md)")
    w("")
    w("Phoenix v2.0.4: 13-pencere ort **yıllık +%200.3 / DD -%32 / r-adj 6.26 / WR %69.7** (13/13 pencere pozitif)")
    w("")
    w("## Hipotez")
    w("")
    w("SEC6 (2026-05-13) v0.9.7 BALANCED'da 4h pivot RED (yıllık +14.4% vs +33.6%) sonuç verdi.")
    w("v2.0.4 PHOENIX (pyramid + side-cond DD + mc=12 + FVG) farklı edge dinamiklerine sahip —")
    w("4h pivot Phoenix için de RED mi olur, yoksa pyramid+side-cond avantajı 4h'de de korunur mu?")
    w("")
    w("## Trade Toplama (10 Phoenix strateji × 10 sym × 1h)")
    w("")
    print("Trade topluyor (Phoenix × 1h)...")
    all_trades: list[dict] = []
    for m, c in PHOENIX_STRATEGIES:
        t0 = time.time()
        ts = _gather_4h_peakR(m, c)
        elapsed = time.time() - t0
        all_trades.extend(ts)
        w(f"- {m}: **{len(ts)}** trade ({elapsed:.1f}s)")
        print(f"  {m}: {len(ts)} ({elapsed:.1f}s)")

    all_trades.sort(key=lambda x: x["entry_ts"])
    w("")
    w(f"**Toplam 1h trade pool:** {len(all_trades)}")
    w(f"**Phoenix 1d:** ~4787 trade, 4h:** 21829 (SEC27)")
    if len(all_trades) > 0:
        Rs = [t["R"] for t in all_trades]
        wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        w(f"**1h pool R stats:** mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")
        n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
        n_peak2 = sum(1 for t in all_trades if t["peak_R"] >= 2.0)
        w(f"**Pyramid eligibility:** peak_R>=1: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%), peak_R>=2: {n_peak2} ({n_peak2*100/len(all_trades):.0f}%)")

    if len(all_trades) < 100:
        w("")
        w("**HATA:** 1h pool yetersiz (< 100 trade).")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    # Walk-forward windows: 2y train + 3mo OOS + 1mo step
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    train_days = 2 * 365
    while cur + pd.Timedelta(days=train_days + 90) <= end:
        windows.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=30)
    w("")
    w(f"**Pencere sayısı:** {len(windows)} (2y rolling, 30 gün step — 1h pool 3y)")
    w(f"**1h pool aralığı:** {start} -> {end}")
    w("")

    # PHOENIX config — direkt yaml'dan
    phoenix_cfg = ProductionConfig.from_yaml("configs/risk_phoenix_v204.yaml")

    # Senaryolar:
    # - PHOENIX 1h default (yaml as-is: mc=12, pyramid, side-cond)
    # - PHOENIX 1h max_conc=20 (1h pool büyük, slot artırılınca)
    # - PHOENIX 1h cooldown=0 (4h cooldown 1d=3 ayni iken 12 bar gibi davranır → çok dar)
    scenarios = [
        ("PHOENIX 1h default (mc=12, pyramid, side-cond)",
         all_trades,
         phoenix_cfg),
        ("PHOENIX 1h max_conc=20",
         all_trades,
         phoenix_cfg.with_overrides(max_concurrent=20)),
        ("PHOENIX 1h mc=20 + cooldown=0",
         all_trades,
         phoenix_cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)),
    ]

    w("## Sonuçlar")
    w("")
    w(f"| Senaryo | Yıllık | Median | Min | Max | DD | r-adj | Negatif |")
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
            anns.append(r.annualized(2.0) * 100)  # 2y train pencere
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
    w("## Karar (vs Champion Phoenix 1d: yıllık +%200.3 / DD -%32 / r-adj 6.26)")
    w("")
    if not rated:
        w("**RED:** Hiçbir 4h senaryo çalışmadı.")
    else:
        best = max(rated, key=lambda x: x[4])  # max r-adj
        w(f"**Best 4h senaryo:** {best[0]}")
        w(f"  - yıllık {best[1]:+.1f}% (vs 1d +%200.3, delta {best[1]-200.3:+.1f}pp)")
        w(f"  - DD {best[3]:+.1f}% (vs 1d -%32, delta {best[3]-(-32):+.1f}pp)")
        w(f"  - r-adj {best[4]:.3f} (vs 1d 6.26, delta {best[4]-6.26:+.3f})")
        w("")
        if best[4] > 6.26 and best[1] > 200.3:
            w("**TOURNAMENT WINNER:** 4h pivot Champion'ı yendi.")
            w("-> v2.1 release adayı, manual onay gerekli.")
        elif best[4] > 5.0:
            w("**MARJINAL:** 4h marjinal yakın, paper trading doğrulamalı.")
        else:
            w("**CHAMPION CONFIRMED:** 1d preset 4h'ten net iyi.")
            w("-> Production lock korundu, 4h yolu archive.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
