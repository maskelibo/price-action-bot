"""Hipotez için canlı-bot-eşdeğeri gerçek backtest.

Faz 14.20 (2026-05-27): Önceki sweep cell R-multiple replay 'sharpe 22'
gibi yapay sayılar üretiyordu (DD halt yok, portfolio cap yok, sadece
trade ortalaması). Canlı bot ise `production_replay()` kullanıyor:
gerçek $ equity simülasyonu + daily/weekly/monthly DD halt + slot
concurrency cap + side concentration limit + per-symbol cap.

Bu modül hipotez param'ını alır, mevcut canlı config'i baz alıp
override yapar, production_replay'i çağırır, Principal dilinde
metrik döner:
  - aylık ROI mean/median
  - negatif ay sayısı (X / N)
  - max DD (compound equity)
  - annualized compound return
  - OOS pencere (son 1.5y) ayrı raporlanır
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from price_action.backtest.lab import (
    ProductionConfig,
    ReplayResult,
    production_replay,
)
from price_action.logging_config import logger

REPO_ROOT = Path(__file__).resolve().parents[3]

# bot_id → (pool_path, base_config_yaml, default_sl_pct_base)
BOT_BACKTEST_MAP = {
    "vsa_climax_test": (
        "data/sec53_15m_pool_v11_vsa2_top4.pkl",
        "configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml",
        0.030,
    ),
    "brooks_failed_breakout": (
        "data/sec53_15m_pool_v11.pkl",
        "configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml",  # genel widestop config
        0.025,
    ),
    "anchored_vwap_reversal": (
        "data/sec53_5m_pool_v11_vm20.pkl",
        "configs/risk_phoenix_scalp_5m_p1c.yaml",
        0.025,
    ),
    "engulfing_continuation": (
        "data/sec53_15m_pool_v11.pkl",
        "configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml",
        0.025,
    ),
}


@dataclass
class RealisticBacktestResult:
    """Live-bot-eşdeğeri backtest çıktısı, Principal dilinde."""
    hypothesis_id: str
    base_strategy: str
    config_label: str
    sl_pct_threshold: float
    risk_pct: float
    # Aggregate (5y span)
    final_equity: float
    initial_capital: float
    total_return_pct: float
    annualized_compound_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    n_trades: int
    avg_R: float
    # Aylık metrikler
    monthly_roi_pct_mean: float
    monthly_roi_pct_median: float
    monthly_neg_count: int
    monthly_total_count: int
    worst_month_pct: float
    best_month_pct: float
    # OOS (son ~1.5y)
    oos_window_months: int
    oos_monthly_roi_pct_mean: float
    oos_monthly_neg_count: int
    oos_total_return_pct: float
    oos_max_drawdown_pct: float
    # Meta
    period_years: float
    pool_path: str
    config_path: str


def _compute_monthly_from_equity(
    eq_curve: list[float],
    entry_ts: list[Any],
    initial_capital: float,
) -> tuple[pd.DataFrame, float]:
    """Equity curve + entry_ts → aylık aggregate DataFrame.

    Equity curve length = len(trades) + 1 (initial). Bir trade'in
    entry_ts'i o trade kapandıktan sonraki equity[i+1]'e karşılık gelir.

    Returns:
        (df_monthly with cols [month, equity_end, monthly_ret],
         period_years)
    """
    if not eq_curve or not entry_ts or len(eq_curve) < 2:
        return pd.DataFrame(columns=["month", "equity_end", "monthly_ret"]), 0.0

    # Trade sayısı: len(eq_curve) - 1. entry_ts uzunluğu eşleşmeli.
    n_trades = len(eq_curve) - 1
    if len(entry_ts) != n_trades:
        # Eşleşmezse erken kes
        n_trades = min(n_trades, len(entry_ts))

    timestamps = pd.to_datetime(entry_ts[:n_trades], utc=True)
    equity_after_trade = eq_curve[1 : n_trades + 1]
    if len(equity_after_trade) == 0:
        return pd.DataFrame(columns=["month", "equity_end", "monthly_ret"]), 0.0

    df = pd.DataFrame({"ts": timestamps, "equity": equity_after_trade})
    df["month"] = df["ts"].dt.to_period("M")
    # Ay sonunda equity = ayın son trade'inin equity'si
    monthly_equity = df.groupby("month")["equity"].last().to_frame("equity_end").reset_index()
    # Aylık return = equity_end[i] / equity_end[i-1] - 1
    monthly_equity["prev_equity"] = monthly_equity["equity_end"].shift(1, fill_value=initial_capital)
    monthly_equity["monthly_ret"] = (
        monthly_equity["equity_end"] / monthly_equity["prev_equity"] - 1.0
    )
    monthly_equity = monthly_equity[["month", "equity_end", "monthly_ret"]]
    # Period years
    if len(timestamps) >= 2:
        span_sec = (timestamps.max() - timestamps.min()).total_seconds()
        period_years = max(span_sec / (365.25 * 86400), 1e-6)
    else:
        period_years = 0.0
    return monthly_equity, period_years


def run_realistic_backtest(
    hypothesis_id: str,
    base_strategy: str,
    *,
    sl_pct_threshold: float | None = None,
    risk_pct_override: float | None = None,
    bot_map: dict | None = None,
) -> RealisticBacktestResult | None:
    """Hipotez param'ı için canlı-bot-eşdeğeri backtest.

    Args:
        hypothesis_id: yazılacak result için kimlik
        base_strategy: 'vsa_climax_test' | 'brooks_failed_breakout' | ...
        sl_pct_threshold: override (None → config default)
        risk_pct_override: override (None → config default)
        bot_map: test için override mapping

    Returns:
        RealisticBacktestResult veya None (data yoksa)
    """
    bmap = bot_map or BOT_BACKTEST_MAP
    if base_strategy not in bmap:
        logger.warning(
            "realistic_bt.unknown_strategy",
            extra={"strategy": base_strategy},
        )
        return None
    pool_rel, cfg_rel, default_sl = bmap[base_strategy]
    pool_path = REPO_ROOT / pool_rel
    cfg_path = REPO_ROOT / cfg_rel
    if not pool_path.exists():
        logger.warning("realistic_bt.pool_missing", extra={"path": str(pool_path)})
        return None
    if not cfg_path.exists():
        logger.warning("realistic_bt.cfg_missing", extra={"path": str(cfg_path)})
        return None

    # Load + filter pool
    import pickle
    with pool_path.open("rb") as f:
        raw_pool = pickle.load(f)
    df = pd.DataFrame(raw_pool)
    df["sl_pct_calc"] = (df["initial_sl"] - df["entry_price"]).abs() / df["entry_price"]
    sl_thr = sl_pct_threshold if sl_pct_threshold is not None else default_sl
    df_filt = df[
        (df["strategy"] == base_strategy) & (df["sl_pct_calc"] >= sl_thr)
    ].copy()
    # entry_ts'ye göre sırala (production_replay buna güvenir)
    df_filt = df_filt.sort_values("entry_ts").reset_index(drop=True)
    trades = df_filt.to_dict("records")
    if not trades:
        logger.warning(
            "realistic_bt.no_trades_after_filter",
            extra={"strategy": base_strategy, "sl_thr": sl_thr},
        )
        return None

    # Config + override (ProductionConfig frozen dataclass → replace ile)
    from dataclasses import replace
    cfg = ProductionConfig.from_yaml(cfg_path)
    overrides: dict[str, Any] = {}
    if risk_pct_override is not None:
        overrides["risk_pct"] = float(risk_pct_override)
    # sl_pct_min cfg'de zaten widestop ayarlı; explicit threshold ile çelişmesin
    overrides["sl_pct_min"] = max(cfg.sl_pct_min, sl_thr)
    cfg = replace(cfg, **overrides)

    # Replay
    result = production_replay(trades, cfg)
    if result is None:
        logger.warning("realistic_bt.replay_returned_none", extra={"strategy": base_strategy})
        return None

    # Faz 14.20: production_replay artık process edilen trade'lerin exit_ts'ini
    # döndürüyor (entry_ts_list field'ında). Daily halt vs ile atlanan trade'ler
    # bu listede YOK → aylık aggregation gerçek.
    processed_ts = result.entry_ts_list or []
    if not processed_ts:
        # Fallback: input entry_ts'lerin ilk N'i (eski davranış)
        processed_ts = df_filt["entry_ts"].tolist()
    monthly_df, period_years = _compute_monthly_from_equity(
        result.equity_curve or [], processed_ts, cfg.initial_capital
    )
    if monthly_df.empty:
        logger.warning("realistic_bt.no_monthly_data", extra={"strategy": base_strategy})
        return None

    # Aggregate
    mret = monthly_df["monthly_ret"]
    monthly_roi_mean = float(mret.mean() * 100)
    monthly_roi_median = float(mret.median() * 100)
    neg_count = int((mret < 0).sum())
    total_months = int(len(mret))
    worst_month = float(mret.min() * 100)
    best_month = float(mret.max() * 100)

    # OOS pencere: son 18 ay (~1.5y)
    oos_window = 18
    if total_months > oos_window:
        oos_mret = mret.iloc[-oos_window:]
        oos_monthly_mean = float(oos_mret.mean() * 100)
        oos_neg = int((oos_mret < 0).sum())
        oos_equity_start = float(
            monthly_df.iloc[-oos_window - 1]["equity_end"]
        ) if total_months > oos_window else cfg.initial_capital
        oos_equity_end = float(monthly_df.iloc[-1]["equity_end"])
        oos_total_return = (oos_equity_end / oos_equity_start - 1.0) * 100
        # OOS DD
        oos_eq = monthly_df.iloc[-oos_window:]["equity_end"].values
        oos_peak = np.maximum.accumulate(oos_eq)
        oos_dd_series = (oos_eq - oos_peak) / oos_peak
        oos_max_dd = float(oos_dd_series.min() * 100)
    else:
        oos_monthly_mean = monthly_roi_mean
        oos_neg = neg_count
        oos_total_return = result.total_return * 100
        oos_max_dd = result.max_drawdown * 100

    return RealisticBacktestResult(
        hypothesis_id=hypothesis_id,
        base_strategy=base_strategy,
        config_label=result.config_label,
        sl_pct_threshold=float(sl_thr),
        risk_pct=float(cfg.risk_pct),
        final_equity=float(result.final_equity),
        initial_capital=float(result.initial_capital),
        total_return_pct=float(result.total_return * 100),
        annualized_compound_pct=float(
            result.annualized(period_years) * 100 if period_years > 0 else 0
        ),
        max_drawdown_pct=float(result.max_drawdown * 100),
        win_rate_pct=float(result.win_rate * 100),
        n_trades=int(result.trades),
        avg_R=float(result.avg_r),
        monthly_roi_pct_mean=monthly_roi_mean,
        monthly_roi_pct_median=monthly_roi_median,
        monthly_neg_count=neg_count,
        monthly_total_count=total_months,
        worst_month_pct=worst_month,
        best_month_pct=best_month,
        oos_window_months=oos_window,
        oos_monthly_roi_pct_mean=oos_monthly_mean,
        oos_monthly_neg_count=oos_neg,
        oos_total_return_pct=float(oos_total_return),
        oos_max_drawdown_pct=float(oos_max_dd),
        period_years=float(period_years),
        pool_path=str(pool_path),
        config_path=str(cfg_path),
    )


def write_result_json(
    out_dir: Path,
    result: RealisticBacktestResult,
) -> Path:
    """Sonucu JSON dosyaya yaz."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{result.hypothesis_id}.realistic.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": asdict(result),
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out_path


def format_principal_summary(r: RealisticBacktestResult) -> str:
    """Live bot header formatına benzer Principal-friendly özet."""
    return (
        f"=== {r.hypothesis_id} ({r.base_strategy}) ===\n"
        f"  Config: {r.config_label}  sl_pct>={r.sl_pct_threshold:.4f}  risk={r.risk_pct:.4f}\n"
        f"  --- 5y backtest ---\n"
        f"  Aylık ROI (mean): {r.monthly_roi_pct_mean:+.2f}%  (median {r.monthly_roi_pct_median:+.2f}%)\n"
        f"  Negatif ay: {r.monthly_neg_count}/{r.monthly_total_count}  "
        f"(worst {r.worst_month_pct:+.2f}%  best {r.best_month_pct:+.2f}%)\n"
        f"  Max DD (compound): {r.max_drawdown_pct:+.2f}%\n"
        f"  Yıllık (compound): {r.annualized_compound_pct:+.2f}%\n"
        f"  Trades: {r.n_trades}  WR: {r.win_rate_pct:.1f}%  avg R: {r.avg_R:+.3f}\n"
        f"  --- OOS (son ~1.5y, 18 ay) ---\n"
        f"  OOS aylık ROI: {r.oos_monthly_roi_pct_mean:+.2f}%  neg ay: {r.oos_monthly_neg_count}/{r.oos_window_months}\n"
        f"  OOS toplam ret: {r.oos_total_return_pct:+.2f}%  OOS DD: {r.oos_max_drawdown_pct:+.2f}%"
    )


if __name__ == "__main__":
    import sys
    # Manuel test — vsa wide-stop (canlı bot config)
    result = run_realistic_backtest(
        hypothesis_id="live-bot-baseline-vsa-widestop",
        base_strategy="vsa_climax_test",
        sl_pct_threshold=0.025,
    )
    if result is None:
        print("Backtest fail")
        sys.exit(1)
    print(format_principal_summary(result))
    out_dir = REPO_ROOT / "memory" / "researcher" / "realistic_backtest_results"
    out_path = write_result_json(out_dir, result)
    print()
    print(f"Yazıldı: {out_path}")
