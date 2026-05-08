"""Drawdown breaker — günlük/haftalık/aylık/ardışık kayıp tetikleyicileri.

State JSON dosyasında persist edilir. Postgres opsiyonel (Ops Engineer ekler).
Hard limit: tetikleyici aktifken yeni emir atılmaz; mevcut açıklarda manuel onay
(`flatten_all_on_breaker: false`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from price_action.logging_config import logger
from price_action.settings import get_settings

if TYPE_CHECKING:
    from price_action.risk.sizing import AccountState


@dataclass
class BreakerState:
    """Persisted breaker durumu."""

    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    consecutive_losses: int = 0
    daily_anchor_equity: float = 0.0
    weekly_anchor_equity: float = 0.0
    monthly_anchor_equity: float = 0.0
    last_reset_daily: str = ""
    last_reset_weekly: str = ""
    last_reset_monthly: str = ""
    triggered_daily: bool = False
    triggered_weekly: bool = False
    triggered_monthly: bool = False
    triggered_consecutive: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class DDBreaker:
    """Drawdown breaker state machine.

    Risk YAML'dan eşikleri okur:
      - daily_loss_pct (default 5%)
      - weekly_loss_pct (default 10%)
      - monthly_loss_pct (default 15%)
      - consecutive_losses (default 6)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        state_path: Path | None = None,
    ) -> None:
        cfg = config or {}
        self.daily_pct = float(cfg.get("daily_loss_pct", 0.05))
        self.weekly_pct = float(cfg.get("weekly_loss_pct", 0.10))
        self.monthly_pct = float(cfg.get("monthly_loss_pct", 0.15))
        self.max_consec = int(cfg.get("consecutive_losses", 6))

        s = get_settings()
        self.state_path: Path = (
            Path(state_path) if state_path else s.logs_dir / "risk" / "breaker_state.json"
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        self._log = logger.bind(component="dd_breaker")

    # ----- persistence -----
    def _load(self) -> BreakerState:
        if not self.state_path.exists():
            return BreakerState()
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return BreakerState(**data)
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).warning("breaker.load_fail")
            return BreakerState()

    def _save(self) -> None:
        try:
            with self.state_path.open("w", encoding="utf-8") as f:
                json.dump(self.state.to_json(), f, default=str, indent=2)
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).error("breaker.save_fail")

    def reset(self) -> None:
        self.state = BreakerState()
        self._save()

    # ----- core -----
    def update(self, account_state: AccountState) -> dict[str, bool]:
        """Hesap durumuna göre tetiklemeleri günceller, snapshot döner."""
        equity = account_state.equity_usdt
        now = datetime.now(timezone.utc)
        # Anchor'ları başlat
        if self.state.daily_anchor_equity == 0:
            self.state.daily_anchor_equity = equity
        if self.state.weekly_anchor_equity == 0:
            self.state.weekly_anchor_equity = equity
        if self.state.monthly_anchor_equity == 0:
            self.state.monthly_anchor_equity = equity

        # Reset kuralları (UTC)
        today = now.date().isoformat()
        if self.state.last_reset_daily != today:
            self.state.last_reset_daily = today
            self.state.daily_anchor_equity = equity
            self.state.triggered_daily = False
        # ISO week
        iso_week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        if self.state.last_reset_weekly != iso_week:
            self.state.last_reset_weekly = iso_week
            self.state.weekly_anchor_equity = equity
            self.state.triggered_weekly = False
        ym = f"{now.year}-{now.month:02d}"
        if self.state.last_reset_monthly != ym:
            self.state.last_reset_monthly = ym
            self.state.monthly_anchor_equity = equity
            self.state.triggered_monthly = False

        # P&L hesapla
        self.state.daily_pnl = equity - self.state.daily_anchor_equity
        self.state.weekly_pnl = equity - self.state.weekly_anchor_equity
        self.state.monthly_pnl = equity - self.state.monthly_anchor_equity
        self.state.consecutive_losses = account_state.consecutive_losses

        # Tetikleyici kontrolleri
        # Neden: risk.yaml drawdown_breakers — bu eşikler insan principal tarafından konur
        # ve algoritma tarafından bypass edilemez.
        self.state.triggered_daily = (
            self.state.daily_anchor_equity > 0
            and -self.state.daily_pnl / self.state.daily_anchor_equity >= self.daily_pct
        )
        self.state.triggered_weekly = (
            self.state.weekly_anchor_equity > 0
            and -self.state.weekly_pnl / self.state.weekly_anchor_equity >= self.weekly_pct
        )
        self.state.triggered_monthly = (
            self.state.monthly_anchor_equity > 0
            and -self.state.monthly_pnl / self.state.monthly_anchor_equity >= self.monthly_pct
        )
        self.state.triggered_consecutive = (
            self.state.consecutive_losses >= self.max_consec
        )
        self._save()
        return self.snapshot_dict()

    def snapshot(self, account_state: AccountState) -> dict[str, bool]:
        return self.update(account_state)

    def snapshot_dict(self) -> dict[str, bool]:
        return {
            "daily": self.state.triggered_daily,
            "weekly": self.state.triggered_weekly,
            "monthly": self.state.triggered_monthly,
            "consecutive": self.state.triggered_consecutive,
        }

    @property
    def any_triggered(self) -> bool:
        return any(self.snapshot_dict().values())
