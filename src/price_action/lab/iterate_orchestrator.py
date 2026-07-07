"""Otonom iterate orchestrator — umut verici stratejileri 6-7 round geliştir.

Faz 14.24 (2026-05-27): User talebi.
'İşte böyle geliştirilir bot. Bunu otonom hale getir. Israrcı olsun
umut vaad edenlere. Yarın sorduğumda bug çıkmasın.'

Sistem:
  1. scripts/find_promising_to_iterate.py (cron 06:05 TR) tarama yapar
     → reports/researcher_iterate_queue/iterate-queue-*.md
  2. Bu orchestrator (cron her 2 saat) queue okur + her target için bir
     sonraki round çalıştırır.
  3. State: data/state/iterate_state.json (per-target progress, idempotent)
  4. BEATS_LIVE / SUPER ELITE bulununca Telegram notify.
  5. Tüm 7 round bitince target "completed" işaretlenir.

Idempotency: aynı target × round için tekrar koşulursa eski state'den
devam eder (already-tested cell'leri atlar).

Error handling: her cell try/except, sadece skip + log. Crash olmaz.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Suppress noisy logs from price_action
os.environ.setdefault("PA_LOG_QUIET", "1")
import warnings

warnings.filterwarnings("ignore")
import logging

logging.getLogger("price_action").setLevel(logging.ERROR)

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))
# FIX 2026-07-02 (fabrika RW P1-6): iterate helper'ları (iterate_rsi2_variants,
# iterate_rsi2_v4) scripts/ altında — path'te yoktu → her variant ImportError
# ile None dönüyordu, target'lar 0-variant'la "completed" işaretlendi (33 gün
# ölü orkestratör, rsi2 7 round × 0 variant).
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from price_action.logging_config import logger

STATE_PATH = REPO_ROOT / "data" / "state" / "iterate_state.json"
QUEUE_DIR = REPO_ROOT / "reports" / "researcher_iterate_queue"
RESULTS_DIR = REPO_ROOT / "memory" / "researcher" / "realistic_backtest_results"

# Live bot baseline (companion karşılaştırması için)
LIVE_BASELINE = {
    "monthly_roi": 12.99,
    "max_dd": -15.48,
    "annualized": 329.0,
}

# Acceptance tiers (iterate_protocol.md ile uyumlu)
TIERS = {
    "LOOSE": {"roi_min": 4.0, "dd_min": -25.0, "neg_max": 22},
    "STRICT": {"roi_min": 5.0, "dd_min": -20.0, "neg_max": 20},
    "ELITE": {"roi_min": 10.0, "dd_min": -20.0, "neg_max": 15},
    "BEATS_LIVE": {"roi_min": 13.0, "dd_min": -20.0, "neg_max": 15},
    "SUPER_ELITE": {"roi_min": 16.0, "dd_min": -18.0, "neg_max": 12},
}

MAX_ROUND = 7
NOTIFY_TIERS = ("BEATS_LIVE", "SUPER_ELITE")


# =====================================================================
# State management
# =====================================================================


def load_state() -> dict[str, Any]:
    """State'i oku, yoksa boş başlat."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            logger.warning("iterate.state_corrupted_resetting")
    return {"targets": {}, "last_run": None, "schema_version": 1}


def save_state(state: dict[str, Any]) -> None:
    """State'i atomik yaz (tempfile + rename)."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_PATH)


def get_target_state(state: dict, target_id: str) -> dict:
    """Bir hedefin state'ini al, yoksa init."""
    if target_id not in state["targets"]:
        state["targets"][target_id] = {
            "status": "pending",
            "current_round": 0,
            "rounds_completed": [],
            "best_variant": None,
            "all_variants": [],
            "started_at": None,
            "completed_at": None,
            "last_round_at": None,
            "errors": [],
        }
    return state["targets"][target_id]


# =====================================================================
# Tier classifier
# =====================================================================


def classify_tier(m: dict) -> str:
    """Sonuç metriklerinden en yüksek geçilen tier."""
    roi = m.get("monthly_roi", 0)
    dd = m.get("max_dd", 0)
    neg = m.get("monthly_neg_count", m.get("neg_count", 999))
    # Reverse order (most strict first)
    for tier in ("SUPER_ELITE", "BEATS_LIVE", "ELITE", "STRICT", "LOOSE"):
        t = TIERS[tier]
        if roi >= t["roi_min"] and dd >= t["dd_min"] and neg <= t["neg_max"]:
            return tier
    return "REJECT"


# =====================================================================
# Round design (strategy-agnostic templates)
# =====================================================================


def _round_template(round_num: int, best_so_far: dict | None) -> list[dict]:
    """Round numarasına göre varyant spec listesi üret.

    rsi2 vaka çalışmasından çıkardığımız patikalar:
      R1: temel patikalar (risk, BE, regime, confluence)
      R2: alternatif filter (concurrent, vol, sembol)
      R3: best_so_far inceltme (daha sıkı halt)
      R4: ROI öncelik (monthly halt + loss_pause)
      R5: ELITE (tp_r genişletme + combo)
      R6: BEATS_LIVE (tp_r 2.5/3.0 + concurrent + monthly)
      R7: SUPER ELITE (best_so_far hibritleri)
    """
    if round_num == 1:
        return [
            {
                "name": "v1_baseline",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 999},
            },
            {
                "name": "v2_risk_red",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.002, "daily_dd_halt": 0.02, "max_concurrent": 999},
            },
            {
                "name": "v3_high_risk",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.003, "max_concurrent": 999},
            },
            {
                "name": "v4_concurrent4",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4},
            },
            {
                "name": "v5_loss_pause3",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 999, "consecutive_loss_pause": 3},
            },
            {
                "name": "v6_combo_r2_r4",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.002, "max_concurrent": 4, "daily_dd_halt": 0.02},
            },
        ]
    if round_num == 2:
        return [
            {
                "name": "v7_concurrent6",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3},
            },
            {
                "name": "v8_concurrent4_pause3",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3},
            },
            {
                "name": "v9_pause2",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 2},
            },
            {
                "name": "v10_monthly0.12",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4, "monthly_dd_halt": 0.12},
            },
            {
                "name": "v11_tp2.0",
                "tp_r": 2.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 999},
            },
        ]
    if round_num == 3:
        return [
            {
                "name": "v12_balance",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.003, "max_concurrent": 6, "daily_dd_halt": 0.025},
            },
            {
                "name": "v13_strict_combo",
                "tp_r": 1.5,
                "equity": {
                    "risk_pct": 0.002,
                    "max_concurrent": 4,
                    "consecutive_loss_pause": 3,
                    "daily_dd_halt": 0.015,
                },
            },
            {
                "name": "v14_pause4",
                "tp_r": 1.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 4},
            },
            {
                "name": "v15_short_only",
                "tp_r": 1.5,
                "side_only": "short",
                "equity": {"risk_pct": 0.005, "max_concurrent": 4},
            },
            {
                "name": "v16_long_only",
                "tp_r": 1.5,
                "side_only": "long",
                "equity": {"risk_pct": 0.005, "max_concurrent": 4},
            },
        ]
    if round_num == 4:
        return [
            {
                "name": "v17_pause3_monthly",
                "tp_r": 1.5,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": 4,
                    "consecutive_loss_pause": 3,
                    "monthly_dd_halt": 0.15,
                },
            },
            {
                "name": "v18_pause2_monthly",
                "tp_r": 1.5,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": 4,
                    "consecutive_loss_pause": 2,
                    "monthly_dd_halt": 0.12,
                },
            },
            {
                "name": "v19_r0.004_combo",
                "tp_r": 1.5,
                "equity": {
                    "risk_pct": 0.004,
                    "max_concurrent": 6,
                    "consecutive_loss_pause": 3,
                    "daily_dd_halt": 0.025,
                },
            },
            {
                "name": "v20_tp2_pause3",
                "tp_r": 2.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 4, "consecutive_loss_pause": 3},
            },
            {
                "name": "v21_tp2_conc6_pause3",
                "tp_r": 2.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3},
            },
        ]
    if round_num == 5:
        return [
            {
                "name": "v22_tp2.5",
                "tp_r": 2.5,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3},
            },
            {
                "name": "v23_tp3.0",
                "tp_r": 3.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 3},
            },
            {
                "name": "v24_tp2_pause2_conc6",
                "tp_r": 2.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2},
            },
            {
                "name": "v25_tp2_monthly",
                "tp_r": 2.0,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": 4,
                    "consecutive_loss_pause": 3,
                    "monthly_dd_halt": 0.12,
                },
            },
            {
                "name": "v26_tp2_conc8",
                "tp_r": 2.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 3},
            },
        ]
    if round_num == 6:
        return [
            {
                "name": "v27_tp3_monthly",
                "tp_r": 3.0,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": 6,
                    "consecutive_loss_pause": 3,
                    "monthly_dd_halt": 0.12,
                },
            },
            {
                "name": "v28_tp3_conc8",
                "tp_r": 3.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 3},
            },
            {
                "name": "v29_tp2.5_conc6_monthly",
                "tp_r": 2.5,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": 6,
                    "consecutive_loss_pause": 3,
                    "monthly_dd_halt": 0.12,
                },
            },
            {
                "name": "v30_tp3_pause2",
                "tp_r": 3.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 6, "consecutive_loss_pause": 2},
            },
            {
                "name": "v31_tp3_conc8_pause2",
                "tp_r": 3.0,
                "equity": {"risk_pct": 0.005, "max_concurrent": 8, "consecutive_loss_pause": 2},
            },
        ]
    if round_num == 7:
        # SUPER ELITE — best_so_far hibritleri
        if best_so_far is None:
            best_tp = 3.0
            best_conc = 6
        else:
            best_tp = best_so_far.get("tp_r", 2.0)
            best_conc = best_so_far.get("max_concurrent", 4)
        return [
            {
                "name": "v32_best_pause2",
                "tp_r": best_tp,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": best_conc,
                    "consecutive_loss_pause": 2,
                },
            },
            {
                "name": "v33_best_pause2_monthly",
                "tp_r": best_tp,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": best_conc,
                    "consecutive_loss_pause": 2,
                    "monthly_dd_halt": 0.10,
                },
            },
            {
                "name": "v34_best_risk0.004",
                "tp_r": best_tp,
                "equity": {
                    "risk_pct": 0.004,
                    "max_concurrent": best_conc,
                    "consecutive_loss_pause": 3,
                },
            },
            {
                "name": "v35_best_conc+1_pause2",
                "tp_r": best_tp,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": best_conc + 2,
                    "consecutive_loss_pause": 2,
                },
            },
            {
                "name": "v36_best_ultra_safe",
                "tp_r": best_tp,
                "equity": {
                    "risk_pct": 0.005,
                    "max_concurrent": max(best_conc - 1, 4),
                    "consecutive_loss_pause": 2,
                    "monthly_dd_halt": 0.10,
                },
            },
        ]
    return []


# =====================================================================
# Variant execution
# =====================================================================


def run_variant_for_strategy(
    strategy_module: str,
    strategy_class: str,
    variant_spec: dict,
) -> dict | None:
    """Tek variant koş — strategy + spec → metrikler.

    Crash-safe: tüm exception'lar caught, None döner.
    """
    try:
        from iterate_rsi2_v4 import _equity_with_loss_pause
        from iterate_rsi2_variants import SYMBOLS, _compute_metrics, _exit_with_be, _load_ohlcv

        mod = __import__(f"price_action.strategies.{strategy_module}", fromlist=[strategy_class])
        StrategyClass = getattr(mod, strategy_class)

        from price_action.strategies.base import StrategyManifest

        manifest = StrategyManifest(name=strategy_module, version="auto-iter")
        strategy = StrategyClass(manifest)

        tp_r = variant_spec.get("tp_r", 1.5)
        side_only = variant_spec.get("side_only")

        # OTONOMI-1 (2026-07-07): TF artık variant_spec'ten geliyor —
        # "15m" hardcode'u otonom TF keşfini kilitliyordu (engine zaten
        # TF-parametrik; market.duckdb'de 1h/4h/1d hazır). Default 15m =
        # mevcut davranış birebir korunur.
        tf = variant_spec.get("timeframe", "15m")
        all_trades = []
        for sym in SYMBOLS:
            df = _load_ohlcv(sym, tf)
            if df.empty:
                continue
            try:
                df_feats = strategy.prepare_features(df)
                signals = strategy.generate_signals(df_feats)
            except Exception:
                continue
            df_feats = df_feats.reset_index(drop=True)
            for sig in signals:
                if side_only and sig.direction != side_only:
                    continue
                sig_idx = df_feats.index[df_feats["ts"] == sig.ts]
                if len(sig_idx) == 0:
                    continue
                i0 = sig_idx[0]
                if i0 >= len(df_feats) - 1:
                    continue
                entry = float(df_feats["close"].iloc[i0])
                R, exit_price, exit_offset = _exit_with_be(
                    df_feats,
                    i0,
                    entry,
                    sig.sl_price,
                    tp_r=tp_r,
                    direction=sig.direction,
                    be_protect=False,
                    trail_pct=None,
                )
                all_trades.append(
                    {
                        "entry_ts": sig.ts,
                        "exit_ts": df_feats["ts"].iloc[i0 + exit_offset]
                        if i0 + exit_offset < len(df_feats)
                        else df_feats["ts"].iloc[-1],
                        "entry_price": entry,
                        "R": float(R),
                        "symbol": sym,
                        "side": sig.direction,
                    }
                )

        if not all_trades:
            return {"status": "NO_TRADES"}
        trades_df = pd.DataFrame(all_trades)
        eq_series, final_eq, n_taken = _equity_with_loss_pause(trades_df, **variant_spec["equity"])
        m = _compute_metrics(eq_series, 10_000.0)
        tier = classify_tier(m)
        return {
            "status": "OK",
            "n_trades_raw": len(trades_df),
            "n_taken": n_taken,
            "monthly_roi": m["monthly_roi"],
            "max_dd": m["max_dd"],
            "neg_count": m["neg_count"],
            "total_months": m["total_months"],
            "annualized": m["annualized"],
            "tier": tier,
            "final_equity": final_eq,
            "tp_r": tp_r,
            **variant_spec["equity"],
        }
    except Exception as exc:
        return {"status": "ERROR", "err": str(exc)[:200], "trace": traceback.format_exc()[-500:]}


# =====================================================================
# Telegram notify
# =====================================================================


def notify_telegram_promote(target_id: str, variant: dict, round_num: int) -> None:
    """BEATS_LIVE / SUPER ELITE bulunca Principal'e bildir."""
    try:
        from price_action.orchestrator.notifications import push_critical

        tier = variant.get("tier", "?")
        msg = (
            f"🏆 {tier} iterate sonuç — {target_id}\n"
            f"Round {round_num} / v={variant.get('name','?')}\n"
            f"Aylık ROI: +{variant['monthly_roi']:.2f}%\n"
            f"Max DD:    {variant['max_dd']:.2f}%\n"
            f"Yıllık:    +{variant['annualized']:.0f}%\n"
            f"Neg ay:    {variant['neg_count']}/{variant['total_months']}\n"
            f"Live ref:  aylık +{LIVE_BASELINE['monthly_roi']}% DD {LIVE_BASELINE['max_dd']}%\n"
            f"\nSpec: risk={variant.get('risk_pct')} conc={variant.get('max_concurrent')} "
            f"tp_r={variant.get('tp_r')} pause={variant.get('consecutive_loss_pause')}"
        )
        push_critical(msg, source="iterate_orchestrator")
    except Exception:
        pass


# =====================================================================
# Strategy mapping (hyp_id → strategy module/class)
# =====================================================================

STRATEGY_REGISTRY = {
    "rsi2-extreme-fade": ("rsi2_extreme_fade", "RSI2ExtremeFadeStrategy"),
    "quasimodo-reversal": ("quasimodo_reversal", "QuasimodoReversalStrategy"),
    "bb-continuation": ("bb_band_continuation", "BBBandContinuationStrategy"),
    "bb-extreme-reversal": ("bb_extreme_reversal", "BBExtremeReversalStrategy"),
    "bollinger-fade": ("bollinger_fade_mr", "BollingerFadeMRStrategy"),
    "brooks-db-bull-flag": ("brooks_db_bull_flag", "BrooksDBBullFlagStrategy"),
    "high-tight-flag": ("high_tight_flag", "HighTightFlagStrategy"),
    "inside-day-failure": ("inside_day_failure", "InsideDayFailureStrategy"),
    "liquidity-sweep": ("liquidity_sweep_reversal", "LiquiditySweepReversalStrategy"),
    "range-bo-failure": ("range_bo_failure_mr", "RangeBOFailureMRStrategy"),
    "rsi-extreme-mr": ("rsi_extreme_mr", "RSIExtremeMRStrategy"),
    "three-push-wedge-fade": ("three_push_wedge_fade", "ThreePushWedgeFadeStrategy"),
    "turtle-soup-20day": ("turtle_soup_20d", "TurtleSoup20DStrategy"),
    "vol-d3-bag-holding": ("vsa_bag_holding", "VSABagHoldingStrategy"),
    "vol-d4-weis-wave": ("weis_wave_divergence", "WeisWaveDivergenceStrategy"),
    "vol-z-spike-fade": ("cvd_spike_fade", "CVDSpikeFadeStrategy"),
    "volatility-compression-nr7": ("nr7_breakout_v2", "NR7BreakoutV2Strategy"),
    # OTONOMI-1 (2026-07-07): PROGRAM_V2 AİLE-1 — NOT_EXECUTABLE rafında bekleyen
    # substantive hipotezlerin detektörleri kayda alındı (kod strategies/ altında
    # zaten mevcuttu; kilit yalnızca bu dict'ti).
    "donchian-channel-breakout": ("donchian_breakout", "DonchianBreakoutStrategy"),
}


def resolve_strategy(target_id: str) -> tuple[str, str] | None:
    """Target ID'den strategy module/class çıkar."""
    target_lower = target_id.lower()
    for key, (mod, cls) in STRATEGY_REGISTRY.items():
        if key in target_lower:
            return mod, cls
    return None


# =====================================================================
# Main orchestrator
# =====================================================================


def discover_targets() -> list[dict]:
    """find_promising_to_iterate tracker dosyasından target listesi al."""
    tracker_path = REPO_ROOT / "memory" / "researcher" / "iterate_targets.json"
    if not tracker_path.exists():
        return []
    try:
        data = json.loads(tracker_path.read_text())
        return data.get("candidates", [])
    except json.JSONDecodeError:
        return []


def run_orchestrator(*, max_targets_per_run: int = 2, max_variants_per_round: int = 5) -> dict:
    """Ana entry — bir sonraki round için targets'i koştur.

    max_targets_per_run: token bütçesi kontrol için bir koşumda max kaç target
    max_variants_per_round: round başına denenecek variant cap
    """
    state = load_state()
    state["last_run"] = datetime.now(UTC).isoformat()
    targets = discover_targets()

    summary = {
        "started_at": state["last_run"],
        "targets_in_queue": len(targets),
        "targets_processed": 0,
        "rounds_run": 0,
        "promotes_found": [],
        "errors": [],
    }

    n_processed = 0
    for tgt in targets:
        if n_processed >= max_targets_per_run:
            break
        target_id = tgt["hypothesis_id"]
        ts = get_target_state(state, target_id)

        # Skip if already completed
        if ts["status"] == "completed":
            continue
        if ts["current_round"] >= MAX_ROUND:
            ts["status"] = "completed"
            ts["completed_at"] = datetime.now(UTC).isoformat()
            continue

        # Resolve strategy
        resolved = resolve_strategy(target_id)
        if resolved is None:
            ts["status"] = "failed"
            ts["errors"].append(
                {"ts": datetime.now(UTC).isoformat(), "err": f"No strategy mapping for {target_id}"}
            )
            summary["errors"].append({"target": target_id, "err": "unmapped"})
            continue
        strategy_module, strategy_class = resolved

        # Next round
        next_round = ts["current_round"] + 1
        if ts["started_at"] is None:
            ts["started_at"] = datetime.now(UTC).isoformat()
        ts["status"] = "in_progress"

        # Design variants
        variants = _round_template(next_round, ts.get("best_variant"))
        if not variants:
            ts["errors"].append(
                {"ts": datetime.now(UTC).isoformat(), "err": f"No template for round {next_round}"}
            )
            summary["errors"].append({"target": target_id, "err": "no_template"})
            continue

        # Cap variants for compute control
        variants = variants[:max_variants_per_round]

        # Run each
        round_results = []
        for v in variants:
            spec = dict(v)
            spec["name"] = f"R{next_round}_{v['name']}"
            try:
                result = run_variant_for_strategy(strategy_module, strategy_class, spec)
                if result is None:
                    continue
                result["variant_name"] = spec["name"]
                result["round"] = next_round
                round_results.append(result)
                # Track best
                if result["status"] == "OK":
                    if ts["best_variant"] is None or result.get("monthly_roi", -999) > ts[
                        "best_variant"
                    ].get("monthly_roi", -999):
                        ts["best_variant"] = result
                # Notify if BEATS_LIVE / SUPER_ELITE
                if result.get("tier") in NOTIFY_TIERS:
                    notify_telegram_promote(target_id, result, next_round)
                    summary["promotes_found"].append(
                        {
                            "target": target_id,
                            "round": next_round,
                            "variant": spec["name"],
                            "tier": result["tier"],
                            "roi": result["monthly_roi"],
                            "dd": result["max_dd"],
                        }
                    )
            except Exception as exc:
                ts["errors"].append(
                    {
                        "ts": datetime.now(UTC).isoformat(),
                        "variant": spec["name"],
                        "err": str(exc)[:200],
                    }
                )
                summary["errors"].append(
                    {"target": target_id, "variant": spec["name"], "err": str(exc)[:100]}
                )

        # Update state
        ts["all_variants"].extend(round_results)
        ts["rounds_completed"].append(next_round)
        ts["current_round"] = next_round
        ts["last_round_at"] = datetime.now(UTC).isoformat()

        if next_round >= MAX_ROUND:
            ts["status"] = "completed"
            ts["completed_at"] = datetime.now(UTC).isoformat()

        # Save after each target (idempotent)
        save_state(state)
        summary["targets_processed"] += 1
        summary["rounds_run"] += 1
        n_processed += 1

        # Write per-round JSON for traceability
        out_dir = RESULTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        round_dump = out_dir / f"auto-iterate-{target_id}-R{next_round}.json"
        round_dump.write_text(
            json.dumps(
                {
                    "target": target_id,
                    "round": next_round,
                    "ran_at": ts["last_round_at"],
                    "results": round_results,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    summary["finished_at"] = datetime.now(UTC).isoformat()
    return summary


if __name__ == "__main__":
    s = run_orchestrator(max_targets_per_run=2, max_variants_per_round=5)
    print(json.dumps(s, indent=2, default=str))
