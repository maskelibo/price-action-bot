"""SEC29: Phoenix v2.0.4 — 15m Backtest (6 ay).

User isteği: bizim stratejimizi 6 aylık 15m mumlar ile test et.

Champion reference:
  - 1d:  yıllık +%200.3 / DD -%32   / r-adj 6.26  / WR %69.7 (13 pencere 3y)
  - 4h:  yıllık +%68.2  / DD -%23.3 / r-adj 2.923 / WR %49.1 (10 pencere 3y)
  - 1h:  yıllık +%51.7  / DD bug    / r-adj bug   / WR %47.6 (10 pencere 3y)

6 ay tek-pencere — rolling yapılmaz (pool dar). Single window 6mo.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

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
from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.run_real_backtest import _load_symbol_ohlcv

REPORT_OUT = ROOT / "reports" / "lab" / "sec29_phoenix_15m_6mo_2026-05-16.md"

SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]

PHOENIX_STRATEGIES = [
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
    ("obv_engulfing_confluence", "OBVEngulfingConfluenceStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("brooks_h2_l2", "BrooksH2L2Strategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("fvg_fill_reversal", "FVGFillReversalStrategy"),
]

TF = "15m"


def _gather_peakR(module_name: str, class_name: str) -> list:
    try:
        mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name, None)
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
            df = _load_symbol_ohlcv(sym, tf=TF)
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = TF
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
                timeframe=TF,
                initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010},
                slippage_bps=5.0,
                ohlcv_provider=prov,
            )
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
                    "vol_z": 0.0,
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

    w("# SEC29: Phoenix v2.0.4 — 15m Backtest (6 ay)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF}")
    w(f"**Pencere:** 6 ay (single window, 2025-11-16 → 2026-05-16)")
    w(f"**Universe:** {len(SYMBOLS_10)} sym × {len(PHOENIX_STRATEGIES)} strateji = {len(SYMBOLS_10)*len(PHOENIX_STRATEGIES)} hücre")
    w("")
    w("## Reference (3 timeframe karşılaştırma)")
    w("")
    w("| TF | Yıllık | DD | r-adj | WR | Pool |")
    w("|---|---:|---:|---:|---:|---:|")
    w("| 1d Champion | +%200.3 | -%32 | 6.26 | %69.7 | 4,787 |")
    w("| 4h | +%68.2 | -%23.3 | 2.923 | %49.1 | 21,829 |")
    w("| 1h | +%51.7 | bug | bug | %47.6 | 85,431 |")
    w("| **15m (test)** | ? | ? | ? | ? | ? |")
    w("")
    w("## Trade Toplama (10 strateji × 10 sym × 15m × 6mo)")
    w("")
    print("Trade topluyor (Phoenix × 15m × 6mo)...")
    all_trades: list[dict] = []
    for m, c in PHOENIX_STRATEGIES:
        t0 = time.time()
        ts = _gather_peakR(m, c)
        elapsed = time.time() - t0
        all_trades.extend(ts)
        w(f"- {m}: **{len(ts)}** trade ({elapsed:.1f}s)")
        print(f"  {m}: {len(ts)} ({elapsed:.1f}s)")

    all_trades.sort(key=lambda x: x["entry_ts"])
    w("")
    w(f"**Toplam 15m trade pool:** {len(all_trades)}")
    if len(all_trades) > 0:
        Rs = [t["R"] for t in all_trades]
        wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        w(f"**15m pool R stats:** mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")
        n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
        n_peak2 = sum(1 for t in all_trades if t["peak_R"] >= 2.0)
        w(f"**Pyramid eligibility:** peak_R>=1: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%), peak_R>=2: {n_peak2} ({n_peak2*100/len(all_trades):.0f}%)")

    if len(all_trades) < 50:
        w("")
        w("**HATA:** Pool çok küçük (< 50 trade).")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    # Single 6mo window
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    w("")
    w(f"**Pool aralığı:** {start} -> {end}")
    w(f"**Süre:** {(end - start).days} gün")
    w("")

    phoenix_cfg = ProductionConfig.from_yaml("configs/risk_phoenix_v204.yaml")

    scenarios = [
        ("PHOENIX 15m default (mc=12)", phoenix_cfg),
        ("PHOENIX 15m mc=20", phoenix_cfg.with_overrides(max_concurrent=20)),
        ("PHOENIX 15m mc=20 + cooldown=0", phoenix_cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)),
    ]

    w("## Sonuçlar (6 ay single window)")
    w("")
    w(f"| Senaryo | Yıllık | DD | r-adj | n_trade_fill |")
    w(f"|---|---:|---:|---:|---:|")
    print(f"\n{'scenario':<55}  {'yillik':>8}  {'DD':>7}  {'r-adj':>7}  {'n_fill':>7}")
    print("-" * 100)

    period_years = (end - start).days / 365.0

    for name, cfg in scenarios:
        r = production_replay(all_trades, cfg)
        if r is None:
            print(f"  {name:<55}  replay None")
            w(f"| {name} | - | - | - | - |")
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        n_fill = len(r.equity_curve) if hasattr(r, "equity_curve") and r.equity_curve is not None else 0
        print(f"  {name:<55}  {ann:>+7.1f}%  {dd:>+6.1f}%  {ra:>6.3f}  {n_fill:>7}")
        w(f"| {name} | {ann:+.1f}% | {dd:+.1f}% | {ra:.3f} | {n_fill} |")

    # Raw cumsum (replay'den bağımsız sanity)
    w("")
    w("## Raw R-Cumsum (replay-bağımsız)")
    w("")
    cumR = sum(t["R"] for t in all_trades)
    pos_R = sum(t["R"] for t in all_trades if t["R"] > 0)
    neg_R = sum(t["R"] for t in all_trades if t["R"] < 0)
    avg_R_long = sum(t["R"] for t in all_trades if str(t["side"]).lower() == "long") / max(1, sum(1 for t in all_trades if str(t["side"]).lower() == "long"))
    avg_R_short = sum(t["R"] for t in all_trades if str(t["side"]).lower() == "short") / max(1, sum(1 for t in all_trades if str(t["side"]).lower() == "short"))
    w(f"- Total R: {cumR:+.1f}")
    w(f"- Pos sum: +{pos_R:.1f}, Neg sum: {neg_R:+.1f}")
    w(f"- Avg R long: {avg_R_long:+.3f}, short: {avg_R_short:+.3f}")
    w("")
    w("**Raw R yıllık tahmin (replay öncesi):** flat sizing risk %4 ile:")
    rough_ann_pct = (cumR / len(all_trades)) * 4.0 * (len(all_trades) / period_years)
    w(f"  ~%{rough_ann_pct:.1f} (kapital cap + concentration limit + pyramid yok)")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
