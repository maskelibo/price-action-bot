"""Config adapter — normalize 3 schemas to canonical CanonicalRiskConfig.

LIVE RiskOfficer canonical schema (sizing.py + breaker.py okur):
  position_sizing:
    risk_per_trade: float
    backtest_risk_pct: float  (lab.py için yedek)
  concentration_limits:
    max_open_positions: int
    max_per_symbol_pct: float
    max_per_category_pct: float
  drawdown_breakers:
    daily_loss_pct: float
    weekly_loss_pct: float
    monthly_loss_pct: float
    consecutive_losses: int
    consecutive_loss_pause_days: float
  execution:
    sl_pct_min: float

3 input schema → 1 canonical normalize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CanonicalRiskConfig:
    """Tek doğru schema — hem lab hem live okur."""

    # position_sizing
    risk_per_trade: float = 0.005
    backtest_risk_pct: float = 0.005

    # concentration_limits
    max_open_positions: int = 8
    max_per_symbol_pct: float = 0.20
    max_per_category_pct: float = 0.40

    # drawdown_breakers
    daily_loss_pct: float = 0.04
    weekly_loss_pct: float = 0.08
    monthly_loss_pct: float = 0.15
    consecutive_losses: int = 5
    consecutive_loss_pause_days: float = 1.0

    # execution
    sl_pct_min: float = 0.0
    tp_r: float | None = None  # backtest engine için (live hardcoded 1R/1.5R)

    # legacy/extra
    backtest_only_keys: dict[str, Any] = field(default_factory=dict)


def from_backtest_flat(cfg: Any) -> CanonicalRiskConfig:
    """lab.py flat schema → canonical.

    Args:
        cfg: dict veya BacktestConfig dataclass with attributes:
             risk_pct, max_concurrent, consecutive_loss_pause, ...
    """
    def _g(name: str, default: Any) -> Any:
        if isinstance(cfg, dict):
            return cfg.get(name, default)
        return getattr(cfg, name, default)

    risk_pct = float(_g("risk_pct", 0.005))
    return CanonicalRiskConfig(
        risk_per_trade=risk_pct,
        backtest_risk_pct=risk_pct,
        max_open_positions=int(_g("max_concurrent", 8)),
        consecutive_losses=int(_g("consecutive_loss_pause", 5)),
        consecutive_loss_pause_days=float(_g("pause_days", 1.0)),
        daily_loss_pct=float(_g("daily_dd_halt", 0.04)),
        monthly_loss_pct=float(_g("monthly_dd_halt", 0.15)),
        sl_pct_min=float(_g("sl_pct_min", 0.0)),
        tp_r=_g("tp_r", None),
    )


def from_iterate_equity(equity: dict[str, Any], tp_r: float | None = None) -> CanonicalRiskConfig:
    """iterate_orchestrator nested schema (equity dict) → canonical."""
    return CanonicalRiskConfig(
        risk_per_trade=float(equity.get("risk_pct", 0.005)),
        backtest_risk_pct=float(equity.get("risk_pct", 0.005)),
        max_open_positions=int(equity.get("max_concurrent", 8)),
        consecutive_losses=int(equity.get("consecutive_loss_pause", 5)),
        consecutive_loss_pause_days=float(equity.get("pause_days", 1.0)),
        daily_loss_pct=float(equity.get("daily_dd_halt", 0.04)),
        monthly_loss_pct=float(equity.get("monthly_dd_halt", 0.15)),
        sl_pct_min=float(equity.get("sl_pct_min", 0.0)),
        tp_r=tp_r,
    )


def from_live_yaml(yaml_path: Path | str | dict[str, Any]) -> CanonicalRiskConfig:
    """LIVE YAML (canonical schema) → canonical (validate + structured).

    Eksik kategoriler default ile doldurulur.
    """
    if isinstance(yaml_path, dict):
        cfg = yaml_path
    else:
        import yaml
        cfg = yaml.safe_load(Path(yaml_path).read_text()) or {}

    ps = cfg.get("position_sizing", {}) or {}
    cl = cfg.get("concentration_limits", {}) or {}
    db = cfg.get("drawdown_breakers", {}) or {}
    ex = cfg.get("execution", {}) or {}

    # backtest-only key'ler (raporlama için tut)
    backtest_only = {}
    sp = cfg.get("strategy_portfolio", {}) or {}
    if sp.get("consecutive_loss_pause_n") is not None:
        backtest_only["strategy_portfolio.consecutive_loss_pause_n"] = sp["consecutive_loss_pause_n"]
    if sp.get("max_concurrent_positions") is not None:
        backtest_only["strategy_portfolio.max_concurrent_positions"] = sp["max_concurrent_positions"]
    if ex.get("tp_r") is not None:
        backtest_only["execution.tp_r"] = ex["tp_r"]

    return CanonicalRiskConfig(
        risk_per_trade=float(ps.get("risk_per_trade", 0.005)),
        backtest_risk_pct=float(ps.get("backtest_risk_pct", ps.get("risk_per_trade", 0.005))),
        max_open_positions=int(cl.get("max_open_positions", 8)),
        max_per_symbol_pct=float(cl.get("max_per_symbol_pct", 0.20)),
        max_per_category_pct=float(cl.get("max_per_category_pct", 0.40)),
        daily_loss_pct=float(db.get("daily_loss_pct", 0.04)),
        weekly_loss_pct=float(db.get("weekly_loss_pct", 0.08)),
        monthly_loss_pct=float(db.get("monthly_loss_pct", 0.15)),
        consecutive_losses=int(db.get("consecutive_losses", 5)),
        consecutive_loss_pause_days=float(db.get("consecutive_loss_pause_days", 1.0)),
        sl_pct_min=float(ex.get("sl_pct_min", 0.0)),
        tp_r=ex.get("tp_r"),
        backtest_only_keys=backtest_only,
    )


def to_live_yaml_dict(canonical: CanonicalRiskConfig) -> dict[str, Any]:
    """Canonical → LIVE YAML schema dict (dump için)."""
    return {
        "position_sizing": {
            "risk_per_trade": canonical.risk_per_trade,
            "backtest_risk_pct": canonical.backtest_risk_pct,
        },
        "concentration_limits": {
            "max_open_positions": canonical.max_open_positions,
            "max_per_symbol_pct": canonical.max_per_symbol_pct,
            "max_per_category_pct": canonical.max_per_category_pct,
        },
        "drawdown_breakers": {
            "daily_loss_pct": canonical.daily_loss_pct,
            "weekly_loss_pct": canonical.weekly_loss_pct,
            "monthly_loss_pct": canonical.monthly_loss_pct,
            "consecutive_losses": canonical.consecutive_losses,
            "consecutive_loss_pause_days": canonical.consecutive_loss_pause_days,
        },
        "execution": {
            "sl_pct_min": canonical.sl_pct_min,
            **({"tp_r": canonical.tp_r} if canonical.tp_r is not None else {}),
        },
    }


def validate_canonical(canonical: CanonicalRiskConfig) -> list[str]:
    """Canonical config sanity check. Empty list → all OK; else error messages."""
    errors: list[str] = []
    if not (0 < canonical.risk_per_trade <= 0.05):
        errors.append(f"risk_per_trade {canonical.risk_per_trade} out of (0, 0.05]")
    if canonical.max_open_positions < 1:
        errors.append(f"max_open_positions {canonical.max_open_positions} < 1")
    if canonical.consecutive_losses < 1:
        errors.append(f"consecutive_losses {canonical.consecutive_losses} < 1")
    if not (0 < canonical.daily_loss_pct <= 0.10):
        errors.append(f"daily_loss_pct {canonical.daily_loss_pct} out of (0, 0.10]")
    if canonical.backtest_only_keys:
        # Warning, not error — backtest-only keys present
        errors.append(
            f"WARNING: backtest-only keys present (LIVE bot ignores): "
            f"{list(canonical.backtest_only_keys.keys())}"
        )
    return errors
