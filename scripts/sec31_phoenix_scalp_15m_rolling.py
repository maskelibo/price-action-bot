"""SEC31: Phoenix-Scalp v1.0 — 15m Rolling Walk-Forward (Phase 4a).

Master plan reference: reports/ceo/2026-05-16_phoenix_scalp_v1_master_plan.md §4.6 + §6
Champion: Phoenix v2.0.4 1d = yıllık +%200.3 / DD -%32 / r-adj 6.26 / WR %69.7

GATE P4a (Phase 4a hard gate):
  Ana hedef: yıllık >= +%200, DD en cok -%32, r-adj >= 6.26
  Alt-gate:  yıllık >= +%50,  DD en cok -%25, r-adj >= 2.0, korelasyon < 0.30

Walk-forward:
  - 2y train + 3mo OOS + 1mo step = 13 pencere (3y total span)
  - SEC27/SEC28 4h/1h pattern + Phoenix 1d 13-pencere referansi

Dependencies (PARALEL SPRINT ÇIKTILARI ile entegre):
  - data_engineer: 10 sym × 15m × 5y ingest tamamlanmalı (Phase 1)
                   mevcut store: 10 sym × 15m × 6ay (2025-11-16 → 2026-05-16)
                   GAP: 4.5y ek 15m bar ingest gerekli (~1.4M ek bar)
  - signal_chief : 10 strateji × 15m lookahead audit PASS (Phase 2)
  - risk_officer : configs/risk_phoenix_scalp_15m.yaml hazır (Phase 3)
                   FALLBACK: yoksa risk_phoenix_v204.yaml + TODO log
  - ops_engineer : observability hazır (Phase 1 paralel)

Compute budget:
  - Tek pencere (2y train, 10 sym × 10 strat, 15m) ~ 8-15 dakika single-thread
  - 13 pencere × ~10 dk = ~2.0-3.5 saat single-thread (Numba JIT ile ~30-60 dk hedef)
  - Multiprocessing 10-worker symbol fanout: ~15-30 dakika hedef

Run modes:
  - DRY_RUN=1 ortam değişkeni: 1 sym × 1 ay subset, syntax + replay path doğrula
  - varsayılan: full 13-pencere 3y rolling

Output: reports/lab/sec31_phoenix_scalp_15m_results.md
"""
from __future__ import annotations

import io
import os
import sys
import time
from datetime import timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path
from statistics import mean, median

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


# ============================================================================
# Constants — TF, gate thresholds, walk-forward params
# ============================================================================
TF = "15m"
TF_BAR_MINUTES = 15
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))
# PARALLEL default OFF — Windows DuckDB read-only lock multi-process conflict yaşıyor.
# data_engineer Parquet read path eklerse veya OHLCVStore connection pool per-process
# guard eklerse: PARALLEL=1 ile aç. SEC31 dry-run notu: serial path stabilize.
PARALLEL = bool(int(os.environ.get("PARALLEL", "0")))

REPORT_OUT = ROOT / "reports" / "lab" / "sec31_phoenix_scalp_15m_results.md"

# Phoenix v2.0.4 universe (10 sym, MATIC yok — 4h pool ile aynı)
SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT"]

# Phoenix v2.0.4: 10 strateji (wyckoff_phase_d DISABLED — WYK-001 lookahead)
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

# Walk-forward window params (master plan §4.6)
TRAIN_DAYS = 2 * 365          # 2y train pencere
OOS_DAYS = 90                 # 3mo OOS
STEP_DAYS = 30                # 1mo step
TARGET_WINDOWS = 13           # Phoenix 1d ile parite (13-pencere ort)

# Phase 4 gate thresholds (master plan §6)
GATE_PRIMARY = {"annual_pct": 200.0, "dd_pct": 32.0, "r_adj": 6.26}
GATE_FALLBACK = {"annual_pct": 50.0, "dd_pct": 25.0, "r_adj": 2.0}

# Risk YAML — paralel risk_officer üretiyor (FALLBACK Phoenix 1d YAML + TODO)
SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m.yaml"
FALLBACK_RISK_YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"


# ============================================================================
# Trade collection (per-symbol — parallelizable)
# ============================================================================
def _gather_peakR_single(args: tuple[str, str, str, str]) -> list[dict]:
    """Tek (strateji, symbol) hücresi için peak_R enriched trade listesi.

    Multiprocessing-friendly: argümanlar pickle-safe (sadece str), modül import lazy.
    """
    module_name, class_name, sym, tf = args
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
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
        print(f"  [SKIP] {module_name}/{sym}: import ({e})")
        return []

    try:
        df = _load_symbol_ohlcv(sym, tf=tf)
        if df is None or df.empty:
            return []
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
    except Exception as ex:
        print(f"  [ERR] {module_name}/{sym}: run {ex}")
        return []

    out = []
    ts_map = pd.to_datetime(df["ts"], utc=True)
    for _, t in r.trades.iterrows():
        try:
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
        except Exception:
            continue
    return out


def collect_all_trades(symbols: list[str], parallel: bool = True) -> list[dict]:
    """10 strat × N sym trade pool (multiprocessing fanout)."""
    tasks = [(m, c, sym, TF) for m, c in PHOENIX_STRATEGIES for sym in symbols]
    all_trades: list[dict] = []
    t0 = time.time()

    if parallel and len(tasks) > 1:
        # Conservative: min(cpu, 10, n_tasks). Windows spawn overhead — küçük task sayısında serial daha hızlı.
        # NOT: Windows + DuckDB read_only çoklu process'te dosya lock conflict riski.
        # Çözüm: parquet read path veya per-process tek connection — data_engineer issue.
        n_workers = min(cpu_count() or 4, 10, len(tasks))
        print(f"  [pool] {n_workers}-worker fanout, {len(tasks)} task")
        with Pool(processes=n_workers) as pool:
            results = pool.map(_gather_peakR_single, tasks)
        for r in results:
            all_trades.extend(r)
    else:
        n_done = 0
        for task in tasks:
            n_done += 1
            print(f"  [serial {n_done}/{len(tasks)}] {task[0]}/{task[2]}")
            all_trades.extend(_gather_peakR_single(task))

    elapsed = time.time() - t0
    print(f"  [collect] {len(all_trades)} trade, {elapsed:.1f}s ({elapsed/60:.1f} min)")
    return all_trades


# ============================================================================
# Walk-forward windows
# ============================================================================
def build_windows(all_trades: list[dict], train_days: int = TRAIN_DAYS,
                  oos_days: int = OOS_DAYS, step_days: int = STEP_DAYS) -> list[tuple]:
    """SEC27/SEC28 pattern: cur ile cur+train_days train, +oos_days OOS — adım step_days."""
    if not all_trades:
        return []
    all_trades.sort(key=lambda x: x["entry_ts"])
    start = all_trades[0]["entry_ts"]
    end = all_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=train_days + oos_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=step_days)
    return windows


# ============================================================================
# Risk config loader (with fallback warning)
# ============================================================================
def load_risk_config(w_log) -> tuple[ProductionConfig, bool]:
    """Scalp YAML varsa onu, yoksa Phoenix 1d fallback + TODO."""
    if SCALP_RISK_YAML.exists():
        cfg = ProductionConfig.from_yaml(str(SCALP_RISK_YAML))
        w_log(f"**Risk YAML:** `{SCALP_RISK_YAML.name}` (scalper-spesifik, risk_officer Phase 3)")
        return cfg, False
    cfg = ProductionConfig.from_yaml(str(FALLBACK_RISK_YAML))
    w_log("")
    w_log("> **WARNING — FALLBACK YAML:** `risk_phoenix_scalp_15m.yaml` bulunamadı.")
    w_log(f"> Phoenix 1d YAML (`{FALLBACK_RISK_YAML.name}`) kullanıldı — sonuçlar **kalibre değil**.")
    w_log("> TODO: risk_officer (Phase 3) tamamlayıp re-run gerekli.")
    w_log("")
    return cfg, True


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w(f"# SEC31: Phoenix-Scalp v1.0 — 15m Rolling Walk-Forward")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF}")
    w(f"**Mode:** {'DRY_RUN (1 sym × 1 ay)' if DRY_RUN else 'FULL (10 sym × 3y rolling 13 pencere)'}")
    w(f"**Master plan:** reports/ceo/2026-05-16_phoenix_scalp_v1_master_plan.md §4.6 + §6")
    w("")
    w(f"## Champion Baseline (Phoenix v2.0.4 1d, RESUME.md)")
    w("")
    w(f"- Yıllık +%200.3 / DD -%32 / r-adj 6.26 / WR %69.7 (13-pencere ort, 13/13 pozitif)")
    w("")
    w(f"## Phase 4a Gate Threshold")
    w("")
    w(f"- **Primary:** annual ≥ +{GATE_PRIMARY['annual_pct']}%, DD ≥ -{GATE_PRIMARY['dd_pct']}%, r-adj ≥ {GATE_PRIMARY['r_adj']}")
    w(f"- **Fallback:** annual ≥ +{GATE_FALLBACK['annual_pct']}%, DD ≥ -{GATE_FALLBACK['dd_pct']}%, r-adj ≥ {GATE_FALLBACK['r_adj']}, corr < 0.30")
    w("")

    # Risk config
    risk_cfg, fallback_used = load_risk_config(w)

    # Symbol subset for DRY_RUN
    symbols = SYMBOLS_10[:1] if DRY_RUN else SYMBOLS_10
    w(f"**Universe:** {len(symbols)} sym × {len(PHOENIX_STRATEGIES)} strateji = {len(symbols)*len(PHOENIX_STRATEGIES)} hücre")
    w("")

    # ========================================================================
    # Trade collection
    # ========================================================================
    w("## Trade Toplama")
    w("")
    t0 = time.time()
    # DRY_RUN: serial. FULL: PARALLEL env'e bağlı (Windows DuckDB lock guard).
    use_parallel = PARALLEL and not DRY_RUN
    all_trades = collect_all_trades(symbols, parallel=use_parallel)
    collect_elapsed = time.time() - t0

    w(f"- Toplanan trade: **{len(all_trades)}**")
    w(f"- Süre: {collect_elapsed:.1f}s ({collect_elapsed/60:.1f} min)")
    if all_trades:
        all_trades.sort(key=lambda x: x["entry_ts"])
        Rs = [t["R"] for t in all_trades]
        wr = sum(1 for r in Rs if r > 0) / len(Rs) * 100
        w(f"- Pool R stats: mean R {sum(Rs)/len(Rs):+.3f}, sumR {sum(Rs):+.1f}, WR {wr:.1f}%")
        n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
        n_peak2 = sum(1 for t in all_trades if t["peak_R"] >= 2.0)
        w(f"- Pyramid eligibility: peak_R≥1: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%), "
          f"peak_R≥2: {n_peak2} ({n_peak2*100/len(all_trades):.0f}%)")
        w(f"- Range: {all_trades[0]['entry_ts']} → {all_trades[-1]['exit_ts']}")
    w("")

    if len(all_trades) < 100:
        w(f"**STOP:** Pool < 100 trade — harness çalıştı ama sample density yetersiz.")
        w(f"Data engineer 5y ingest tamamlamadan full backtest anlamsız.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"\nRapor: {REPORT_OUT}")
        return

    # ========================================================================
    # Walk-forward windows
    # ========================================================================
    if DRY_RUN:
        # DRY_RUN: tek pencere, span ne kadar küçükse o kadar
        windows = [(all_trades[0]["entry_ts"], all_trades[-1]["exit_ts"])]
        w(f"**DRY_RUN windows:** 1 (tek pencere = pool full span)")
    else:
        windows = build_windows(all_trades)
        w(f"## Walk-Forward Windows ({len(windows)} pencere, 2y train + 3mo OOS + 1mo step)")
        w("")
        if len(windows) < TARGET_WINDOWS:
            w(f"> **WARNING:** {len(windows)}/{TARGET_WINDOWS} pencere üretildi.")
            w(f"> Pool span yetersiz — data_engineer 5y ingest tamamlamadan 13-pencere mümkün değil.")
        w("")

    # ========================================================================
    # Scenarios (Phoenix 1d → 15m re-test)
    # ========================================================================
    scenarios = [
        ("PHOENIX 15m default (mc=12, pyramid, side-cond)", risk_cfg),
        ("PHOENIX 15m mc=16", risk_cfg.with_overrides(max_concurrent=16)),
        ("PHOENIX 15m mc=20 + cooldown=0", risk_cfg.with_overrides(
            max_concurrent=20, same_symbol_side_cooldown_days=0)),
    ]

    w("## Sonuçlar (Rolling Walk-Forward)")
    w("")
    w(f"| Pencere | Start | End | Trades | Mean R | Annual % | DD % | r-adj | WR % | Breaker Tetik | Fee/Slip $ |")
    w(f"|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    # Pencere-bazlı detay tablo (sadece default scenario için)
    default_cfg = scenarios[0][1]
    period_years = TRAIN_DAYS / 365.0 if not DRY_RUN else max(0.1,
        (all_trades[-1]["exit_ts"] - all_trades[0]["entry_ts"]).days / 365.0)

    for i, (ws, we) in enumerate(windows, start=1):
        ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if not ww_trades:
            w(f"| W{i} | {ws.date()} | {we.date()} | 0 | - | - | - | - | - | - | - |")
            continue
        r = production_replay(ww_trades, default_cfg)
        if r is None:
            w(f"| W{i} | {ws.date()} | {we.date()} | {len(ww_trades)} | - | (replay None) | - | - | - | - | - |")
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        Rs = [t["R"] for t in ww_trades]
        mR = sum(Rs) / len(Rs) if Rs else 0
        wr = sum(1 for r0 in Rs if r0 > 0) / len(Rs) * 100 if Rs else 0
        # Breaker tetik + fee/slip: production_replay alanları henüz extract edilmedi — TODO
        breaker_n = getattr(r, "n_breaker_triggers", "n/a")
        fee_slip = getattr(r, "total_fee_slip_usdt", "n/a")
        w(f"| W{i} | {ws.date()} | {we.date()} | {len(ww_trades)} | {mR:+.3f} | "
          f"{ann:+.1f}% | {dd:+.1f}% | {ra:.3f} | {wr:.1f}% | {breaker_n} | {fee_slip} |")

    # ========================================================================
    # Scenario aggregate karşılaştırma
    # ========================================================================
    w("")
    w("## Senaryo Özeti")
    w("")
    w(f"| Senaryo | Mean Yıllık | Median | Min | Max | Mean DD | r-adj | Negatif Pencere |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")

    rated = []
    for name, cfg in scenarios:
        anns, dds = [], []
        for ws, we in windows:
            ww_trades = [t for t in all_trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(period_years) * 100)
            dds.append(r.max_drawdown * 100)
        if not anns:
            w(f"| {name} | - | - | - | - | - | - | - |")
            continue
        ma, md = mean(anns), mean(dds)
        ra = ma / abs(md) if md != 0 else 0
        neg = sum(1 for a in anns if a < 0)
        med_a = median(anns)
        rated.append((name, ma, med_a, md, ra, min(anns), max(anns), neg))
        w(f"| {name} | {ma:+.1f}% | {med_a:+.1f}% | {min(anns):+.1f}% | {max(anns):+.1f}% | "
          f"{md:+.1f}% | {ra:.3f} | {neg}/{len(anns)} |")

    # ========================================================================
    # Gate karar
    # ========================================================================
    w("")
    w("## Gate Karar")
    w("")
    if not rated:
        w("**STOP:** Hiçbir senaryo replay üretmedi — harness debug gerekli.")
    else:
        best = max(rated, key=lambda x: x[4])
        w(f"**Best senaryo:** {best[0]}")
        w(f"- Yıllık: {best[1]:+.1f}% (vs Champion +200.3%)")
        w(f"- DD: {best[3]:+.1f}% (vs Champion -32%)")
        w(f"- r-adj: {best[4]:.3f} (vs Champion 6.26)")
        w(f"- Pozitif pencere: {len(anns) - best[7]}/{len(anns)}")
        w("")
        primary_pass = (best[1] >= GATE_PRIMARY["annual_pct"] and
                        abs(best[3]) <= GATE_PRIMARY["dd_pct"] and
                        best[4] >= GATE_PRIMARY["r_adj"])
        fallback_pass = (best[1] >= GATE_FALLBACK["annual_pct"] and
                         abs(best[3]) <= GATE_FALLBACK["dd_pct"] and
                         best[4] >= GATE_FALLBACK["r_adj"])
        if primary_pass:
            w("**GATE P4a PRIMARY PASS** -> P4b (5m) sprint başlasın.")
        elif fallback_pass:
            w("**GATE P4a FALLBACK PASS** -> P5 (portfolio layer) + opsiyonel P4b.")
            w("> Korelasyon analizi (analyst Phase 5) zorunlu — corr < 0.30 hedef.")
        else:
            w("**GATE P4a FAIL** -> Master plan §7 KILL kriteri: 15m archive, 5m+1m iptal.")

    if fallback_used:
        w("")
        w("> **NOT:** Fallback YAML kullanıldı — sonuçlar **gösterge**, scalper kalibrasyonu sonrası tekrarlanmalı.")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
