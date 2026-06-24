"""SEC32: Phoenix-Scalp v1.0 — 15m **6-AY PREVIEW RUN** (single window).

Erken sinyal harness'i (CEO görevi 2026-05-17). Full 5y backfill ARKADA çalışıyor;
6-aylık tek pencere preview ile GO/CONDITIONAL/PAUSE kararı verilir.

DIFF vs SEC29 (önceki dry-run):
  - YAML: configs/risk_phoenix_scalp_15m.yaml (SEC29 yanlışlıkla Phoenix 1d YAML kullandı)
  - DATA: Parquet path (DuckDB lock-safe; data_engineer 5m ingest paralel çalışıyor)
  - METRIC: breaker tetik proxy + fee/slip toplam $ + scalp-spesifik kıyas

Master plan: reports/ceo/2026-05-16_phoenix_scalp_v1_master_plan.md §4.5

Gate kararı (6mo annualized = 6mo return × 2; çok kaba):
  - r-adj ≥ 2.0   → GO         (full 5y backtest tetiklenir)
  - r-adj 1.0-2.0 → CONDITIONAL (strateji/sym ablation gerek)
  - r-adj < 1.0   → PAUSE       (root cause sprint)
"""
from __future__ import annotations

import glob
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

TF = "15m"
REPORT_OUT = ROOT / "reports" / "lab" / "2026-05-17_phoenix_scalp_15m_6mo_preview.md"

SCALP_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m.yaml"

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

# Fee/slip params (engine ile aynı: 7.5 bps taker / -1.0 maker, 5 bps slip)
FEE_TAKER_BPS = 7.5
FEE_MAKER_BPS = -1.0
SLIPPAGE_BPS = 5.0


# ============================================================================
# Parquet loader — DuckDB lock-safe (data_engineer 5m ingest paralel)
# ============================================================================
def _load_parquet_ohlcv(symbol: str, tf: str = TF) -> pd.DataFrame:
    """Read OHLCV from partitioned parquet path (lock-safe vs DuckDB ingest)."""
    sym_dir = symbol.replace("/", "_")
    pattern = str(ROOT / "data" / "parquet" / "binance" / sym_dir / tf / "year=*" / "month=*" / "*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs).sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


# ============================================================================
# Trade collection (per-cell)
# ============================================================================
def _gather_cell(module_name: str, class_name: str, sym: str) -> list[dict]:
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

    df = _load_parquet_ohlcv(sym, tf=TF)
    if df.empty:
        return []
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

    try:
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe=TF,
            initial_capital=10_000.0,
            fees={"taker": FEE_TAKER_BPS / 1e4, "maker": FEE_MAKER_BPS / 1e4},
            slippage_bps=SLIPPAGE_BPS,
            ohlcv_provider=prov,
        )
    except Exception as ex:
        print(f"  [ERR] {module_name}/{sym}: run {ex}")
        return []

    out = []
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

            # Hold duration (15m bar count) — fee erozyon proxy
            hold_minutes = (ts_x - ts_e).total_seconds() / 60.0

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
                "hold_minutes": hold_minutes,
                "risk_pct": risk_pct,
            })
        except Exception:
            continue
    return out


def collect_all(symbols: list[str], strategies: list[tuple[str, str]]) -> list[dict]:
    all_trades: list[dict] = []
    t0 = time.time()
    total = len(symbols) * len(strategies)
    done = 0
    for m, c in strategies:
        m_t0 = time.time()
        m_count = 0
        for sym in symbols:
            done += 1
            ts = _gather_cell(m, c, sym)
            m_count += len(ts)
            all_trades.extend(ts)
        print(f"  [{done}/{total}] {m}: {m_count} trade ({time.time()-m_t0:.1f}s)")
    print(f"  [collect] {len(all_trades)} trade, {time.time()-t0:.1f}s")
    return all_trades


# ============================================================================
# Scenario runner — replay + metrics
# ============================================================================
def run_scenario(trades: list[dict], cfg: ProductionConfig, label: str,
                 period_years: float) -> dict:
    r = production_replay(trades, cfg)
    if r is None:
        return {"label": label, "ok": False}
    ann = r.annualized(period_years) * 100
    dd = r.max_drawdown * 100
    ra = ann / abs(dd) if dd != 0 else 0
    # 6mo gerçek return (annualize değil) — kaba kıyas için
    raw_6mo_return = r.total_return * 100
    return {
        "label": label,
        "ok": True,
        "n": r.trades,
        "wr": r.win_rate * 100,
        "mean_R": r.avg_r,
        "sum_R": r.sum_r,
        "raw_6mo_pct": raw_6mo_return,
        "annual_pct": ann,
        "dd_pct": dd,
        "r_adj": ra,
        "final_equity": r.final_equity,
    }


# ============================================================================
# Fee/Slip aggregate (replay-bağımsız ham hesap)
# ============================================================================
def aggregate_fee_slip(trades: list[dict], initial_capital: float = 10_000.0,
                       risk_pct: float = 0.020) -> dict:
    """Trade pool için yıllık fee+slip $ erozyon tahmini.

    Formül: trade başına round-trip fee = (entry_notional × 2 × taker_bps + slip_bps × 2) / 1e4
    Notional ≈ initial_capital × risk_pct × (1 / sl_pct_avg) × leverage_eff
    Bu kabaca — gerçek replay daha düşük gösterir (cap + pyramid + dynamic sizing)."""
    if not trades:
        return {"total_fee_usdt": 0, "total_slip_usdt": 0, "fee_pct_of_equity": 0}
    # Avg sl_pct = risk_pct / final_risk → trades have risk_pct entry-level
    avg_sl_pct = sum(t["risk_pct"] for t in trades) / max(1, len(trades))
    if avg_sl_pct <= 0:
        return {"total_fee_usdt": 0, "total_slip_usdt": 0, "fee_pct_of_equity": 0}
    # Notional per trade ≈ (equity × risk_pct) / sl_pct (raw, no cap)
    avg_notional = initial_capital * risk_pct / avg_sl_pct
    # Round-trip taker bps (worst case, no maker rebate)
    fee_per_trade = avg_notional * (FEE_TAKER_BPS * 2) / 1e4
    slip_per_trade = avg_notional * (SLIPPAGE_BPS * 2) / 1e4
    total_fee = fee_per_trade * len(trades)
    total_slip = slip_per_trade * len(trades)
    return {
        "total_fee_usdt": total_fee,
        "total_slip_usdt": total_slip,
        "fee_pct_of_equity": (total_fee + total_slip) / initial_capital * 100,
        "n_trades": len(trades),
        "avg_sl_pct": avg_sl_pct,
        "avg_notional": avg_notional,
    }


# ============================================================================
# Ablation — tek-strateji / tek-sym (FAIL ise)
# ============================================================================
def ablation_single_strategy(trades: list[dict], cfg: ProductionConfig,
                             period_years: float) -> list[dict]:
    results = []
    for m, _ in PHOENIX_STRATEGIES:
        sub = [t for t in trades if t["strategy"] == m]
        if len(sub) < 20:
            results.append({"strategy": m, "n": len(sub), "ok": False, "note": "n<20"})
            continue
        r = production_replay(sub, cfg)
        if r is None:
            results.append({"strategy": m, "n": len(sub), "ok": False, "note": "replay None"})
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        results.append({"strategy": m, "n": r.trades, "ok": True,
                        "annual_pct": ann, "dd_pct": dd, "r_adj": ra,
                        "wr": r.win_rate * 100, "mean_R": r.avg_r})
    return results


def ablation_btc_eth_only(trades: list[dict], cfg: ProductionConfig,
                           period_years: float) -> dict:
    sub = [t for t in trades if t["symbol"] in ("BTC/USDT", "ETH/USDT")]
    if not sub:
        return {"ok": False, "note": "no BTC/ETH"}
    r = production_replay(sub, cfg)
    if r is None:
        return {"ok": False, "note": "replay None"}
    ann = r.annualized(period_years) * 100
    dd = r.max_drawdown * 100
    ra = ann / abs(dd) if dd != 0 else 0
    return {"ok": True, "n": r.trades, "annual_pct": ann, "dd_pct": dd,
            "r_adj": ra, "wr": r.win_rate * 100, "mean_R": r.avg_r}


# ============================================================================
# Gate karar
# ============================================================================
def gate_decision(r_adj: float) -> tuple[str, str]:
    if r_adj >= 2.0:
        return "GO", "Full 5y backtest tetiklenir (data_engineer ingest tamamlanınca)."
    elif r_adj >= 1.0:
        return "CONDITIONAL", "Marjinal — strateji/sym ablation gerek, full backtest belki."
    else:
        return "PAUSE", "Root cause sprint gerekli (strateji ablation, config tighten)."


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# SEC32 — Phoenix-Scalp v1.0 15m 6-AY PREVIEW RUN")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w(f"**Timeframe:** {TF}")
    w(f"**Pencere:** 6 ay tek-pencere (2025-11-16 → 2026-05-16)")
    w(f"**Universe:** 10 sym × 10 strateji = 100 hücre")
    w(f"**Risk YAML:** `configs/risk_phoenix_scalp_15m.yaml` (scalp-spesifik, risk_per_trade %2)")
    w(f"**Data source:** Parquet (DuckDB lock-safe — data_engineer 5m ingest paralel çalışıyor)")
    w("")
    w("## Reference (Phoenix TF kıyaslama)")
    w("")
    w("| TF | Yıllık | DD | r-adj | WR | Pool |")
    w("|---|---:|---:|---:|---:|---:|")
    w("| 1d Champion (v2.0.4) | +%200.3 | -%32 | 6.26 | %69.7 | 4,787 (13-pencere 3y) |")
    w("| 4h (SEC27) | +%68.2 | -%23.3 | 2.923 | %49.1 | 21,829 (10-pencere 3y) |")
    w("| 1h (SEC28, bug) | +%51.7 | bug | bug | %47.6 | 85,431 (10-pencere 3y) |")
    w("| **15m 6mo preview** | ? | ? | ? | ? | ? (1 pencere 6mo) |")
    w("")
    w("## Gate Threshold (6mo preview)")
    w("")
    w("- **GO:** annualized r-adj ≥ 2.0 → full 5y backtest tetiklenir")
    w("- **CONDITIONAL:** annualized r-adj 1.0-2.0 → ablation gerek")
    w("- **PAUSE:** annualized r-adj < 1.0 → root cause sprint")
    w("")

    # ========================================================================
    # YAML validation
    # ========================================================================
    if not SCALP_YAML.exists():
        w(f"**STOP:** `{SCALP_YAML.name}` bulunamadı. risk_officer sprint tamamlanmadı.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return
    risk_cfg = ProductionConfig.from_yaml(str(SCALP_YAML))
    w(f"## YAML Doğrulama")
    w("")
    w(f"- risk_pct: {risk_cfg.risk_pct*100:.2f}%  (1d %4 → scalp %2)")
    w(f"- max_concurrent: {risk_cfg.max_concurrent}  (1d 12 → scalp 16)")
    w(f"- daily_dd: {risk_cfg.daily_dd*100:.1f}% / weekly: {risk_cfg.weekly_dd*100:.1f}% / monthly: {risk_cfg.monthly_dd*100:.1f}%")
    w(f"- monthly_dd_long: {risk_cfg.monthly_dd_long*100 if risk_cfg.monthly_dd_long else 'n/a'}% / short: {risk_cfg.monthly_dd_short*100 if risk_cfg.monthly_dd_short else 'n/a'}%")
    w(f"- consecutive_losses: {risk_cfg.consecutive_loss_n} / pause: {risk_cfg.consecutive_loss_pause_days}g")
    w(f"- pyramid_enabled: {risk_cfg.pyramid_enabled}  (scalp = False, hold süresi kısa)")
    w(f"- max_notional_pct_equity: {risk_cfg.max_notional_pct_equity*100 if risk_cfg.max_notional_pct_equity else 'n/a'}%")
    w("")

    # ========================================================================
    # Trade collection
    # ========================================================================
    w("## Trade Toplama (parquet path)")
    w("")
    t0 = time.time()
    all_trades = collect_all(SYMBOLS_10, PHOENIX_STRATEGIES)
    collect_elapsed = time.time() - t0
    w(f"- Toplam trade: **{len(all_trades)}**")
    w(f"- Süre: {collect_elapsed:.1f}s ({collect_elapsed/60:.1f} min)")

    if len(all_trades) < 100:
        w("")
        w(f"**STOP:** Pool < 100 trade — preview anlamsız.")
        REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
        return

    all_trades.sort(key=lambda x: x["entry_ts"])
    pool_start = all_trades[0]["entry_ts"]
    pool_end = all_trades[-1]["exit_ts"]
    period_years = (pool_end - pool_start).days / 365.0

    Rs = [t["R"] for t in all_trades]
    wr_raw = sum(1 for r in Rs if r > 0) / len(Rs) * 100
    mean_R_raw = sum(Rs) / len(Rs)
    mean_hold_min = sum(t["hold_minutes"] for t in all_trades) / len(all_trades)

    w(f"- Pool R stats: mean R **{mean_R_raw:+.3f}**, sumR **{sum(Rs):+.1f}**, WR **{wr_raw:.1f}%**")
    n_peak1 = sum(1 for t in all_trades if t["peak_R"] >= 1.0)
    n_peak2 = sum(1 for t in all_trades if t["peak_R"] >= 2.0)
    w(f"- Pyramid eligibility: peak_R≥1: {n_peak1} ({n_peak1*100/len(all_trades):.0f}%), "
      f"peak_R≥2: {n_peak2} ({n_peak2*100/len(all_trades):.0f}%)  [scalp pyramid OFF]")
    w(f"- Avg hold: {mean_hold_min:.1f} dakika ({mean_hold_min/60:.2f} saat)")
    w(f"- Pool range: {pool_start} → {pool_end} ({(pool_end - pool_start).days} gün, {period_years:.3f} yıl)")
    w("")

    # ========================================================================
    # Fee/Slip aggregate (replay-bağımsız ham hesap)
    # ========================================================================
    w("## Fee/Slip Aggregate (ham — replay-bağımsız)")
    w("")
    fs = aggregate_fee_slip(all_trades, initial_capital=10_000.0, risk_pct=risk_cfg.risk_pct)
    w(f"- Avg notional/trade: ${fs['avg_notional']:.0f}  (avg sl_pct {fs['avg_sl_pct']*100:.2f}%)")
    w(f"- Total fee (round-trip taker): **${fs['total_fee_usdt']:.0f}**")
    w(f"- Total slip: **${fs['total_slip_usdt']:.0f}**")
    w(f"- Fee+Slip % of initial equity: **{fs['fee_pct_of_equity']:.1f}%** (6 ay)")
    w(f"- Annualized (×2): **~{fs['fee_pct_of_equity']*2:.1f}%/yıl** ← scalp fee yükü baseline")
    w("")

    # ========================================================================
    # Scenario replay — default (scalp YAML)
    # ========================================================================
    w("## Replay Sonuçları (6-ay tek pencere)")
    w("")
    scenarios = [
        ("PHOENIX-SCALP 15m default (mc=16, pyramid OFF)", risk_cfg),
        ("PHOENIX-SCALP 15m mc=20 + cooldown=0", risk_cfg.with_overrides(
            max_concurrent=20, same_symbol_side_cooldown_days=0)),
        ("PHOENIX-SCALP 15m pyramid ON (Phoenix 1d standard)", risk_cfg.with_overrides(
            pyramid_enabled=True, pyramid_triggers=(1.0, 2.0), pyramid_sizes=(0.50, 0.30))),
    ]
    w(f"| Senaryo | n | WR | mean R | 6mo raw % | Annual % | DD % | r-adj |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")
    results = []
    for name, cfg in scenarios:
        res = run_scenario(all_trades, cfg, name, period_years)
        if not res["ok"]:
            w(f"| {name} | - | - | - | - | - | - | - |")
            continue
        results.append(res)
        w(f"| {name} | {res['n']} | {res['wr']:.1f}% | {res['mean_R']:+.3f} | "
          f"{res['raw_6mo_pct']:+.1f}% | {res['annual_pct']:+.1f}% | "
          f"{res['dd_pct']:+.1f}% | {res['r_adj']:.3f} |")

    # ========================================================================
    # Karşılaştırma + karar
    # ========================================================================
    w("")
    w("## Phoenix TF Kıyaslama")
    w("")
    if results:
        best = max(results, key=lambda r: r["r_adj"])
        w(f"**Best 15m scenario:** {best['label']}")
        w(f"- Annualized: {best['annual_pct']:+.1f}%  (vs 1d +200.3% / 4h +68.2% / 1h +51.7%)")
        w(f"- DD: {best['dd_pct']:+.1f}%  (vs 1d -32% / 4h -23.3%)")
        w(f"- r-adj: {best['r_adj']:.3f}  (vs 1d 6.26 / 4h 2.923)")
        w(f"- WR: {best['wr']:.1f}%  (vs 1d %69.7 / 4h %49.1 / 1h %47.6)")
        w("")
        decision, note = gate_decision(best["r_adj"])
        w(f"## Gate Karar: **{decision}**")
        w("")
        w(f"- {note}")
        w(f"- 6mo annualized r-adj: **{best['r_adj']:.3f}**  (gate: ≥2.0 GO, 1.0-2.0 COND, <1.0 PAUSE)")
        w("")

        # FAIL ise ablation
        if decision in ("CONDITIONAL", "PAUSE"):
            w("## Ablation — Tek-Strateji (FAIL ise)")
            w("")
            w(f"| Strateji | n | WR | mean R | Annual % | DD % | r-adj |")
            w(f"|---|---:|---:|---:|---:|---:|---:|")
            t0 = time.time()
            single_strat = ablation_single_strategy(all_trades, risk_cfg, period_years)
            print(f"  [ablation strat] {time.time()-t0:.1f}s")
            for s in sorted(single_strat, key=lambda x: -(x.get("r_adj") or -999)):
                if not s["ok"]:
                    w(f"| {s['strategy']} | {s['n']} | - | - | - | - | - |")
                    continue
                w(f"| {s['strategy']} | {s['n']} | {s['wr']:.1f}% | {s['mean_R']:+.3f} | "
                  f"{s['annual_pct']:+.1f}% | {s['dd_pct']:+.1f}% | {s['r_adj']:.3f} |")
            w("")
            pos_strats = [s for s in single_strat if s.get("ok") and s.get("r_adj", 0) >= 1.0]
            w(f"- Pozitif r-adj≥1.0 strateji sayısı: **{len(pos_strats)}/10**")
            w("")

            w("## Ablation — BTC + ETH Only (likidite avantajı)")
            w("")
            btc_eth = ablation_btc_eth_only(all_trades, risk_cfg, period_years)
            if btc_eth["ok"]:
                w(f"- n: {btc_eth['n']}, WR {btc_eth['wr']:.1f}%, mean R {btc_eth['mean_R']:+.3f}")
                w(f"- Annual {btc_eth['annual_pct']:+.1f}% / DD {btc_eth['dd_pct']:+.1f}% / r-adj {btc_eth['r_adj']:.3f}")
                w("")
                if btc_eth["r_adj"] > best["r_adj"]:
                    w(f"  → BTC+ETH only daha iyi (+{btc_eth['r_adj']-best['r_adj']:.2f} r-adj)")
                else:
                    w(f"  → Sym ablation katkı yok ({btc_eth['r_adj']-best['r_adj']:+.2f} r-adj delta)")
            else:
                w(f"- {btc_eth.get('note', 'no result')}")
            w("")
    else:
        w("**STOP:** Hiçbir senaryo replay üretmedi.")
        decision = "PAUSE"

    # ========================================================================
    # 5y projection notu
    # ========================================================================
    w("## 5y Backfill Projeksiyonu")
    w("")
    w("- 6mo preview tek-pencere; 5y full = 13-pencere walk-forward (2y train + 3mo OOS + 1mo step)")
    w("- Rolling pencere ortalaması genelde tek-pencere'den **daha düşük** olur (regime variance)")
    w("- Phoenix 1d empirik: tek-pencere 5y ≈ +%200, 13-pencere ort = +%200 (denge)")
    w("- 4h empirik: 10-pencere ort +%68 (tek-pencere'den ~2x düşük olabilir)")
    w("- 15m tahmin: 6mo annualized × 0.5-0.8 = full 5y rolling tahmini bant")
    w("")
    w("## CEO Brief (öneri)")
    w("")
    w(f"- Karar: **{decision}**")
    if decision == "GO":
        w("- Action: data_engineer 5y ingest tamamlandığında SEC31 13-pencere walk-forward tetiklenir.")
    elif decision == "CONDITIONAL":
        w("- Action: Ablation tablosundan en zayıf 2-3 strateji/sym dropout aday → revised config ile retest.")
        w("- Full 5y backtest yine tetiklenebilir ama düşük öncelik (1d champion'a paralel).")
    else:
        w("- Action: 15m archive aday. Root cause: fee erozyon, regime variance, strateji TF uyumsuz.")
        w("- Master plan §7 KILL kriteri yakın — 5m/1m sprint iptal aday.")
    w("")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nRapor: {REPORT_OUT}")


if __name__ == "__main__":
    main()
