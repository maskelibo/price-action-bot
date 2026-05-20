"""Drawdown breaker with persistent state + side-conditional DD support."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BreakerConfig:
    daily_loss_pct: float = 0.05
    weekly_loss_pct: float = 0.10
    monthly_loss_pct: float = 0.15
    consecutive_losses: int = 4
    pause_days: int = 3
    # Side-conditional DD (long/short separate halt)
    monthly_loss_pct_long: float = 0.15
    monthly_loss_pct_short: float = 0.15


@dataclass
class BreakerState:
    blocked_until: Optional[str] = None       # ISO timestamp
    blocked_long_until: Optional[str] = None
    blocked_short_until: Optional[str] = None
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    monthly_pnl_long: float = 0.0
    monthly_pnl_short: float = 0.0
    last_reset_day: Optional[str] = None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".breaker_", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class DDBreaker:
    def __init__(self, cfg: BreakerConfig, state_path: Optional[Path] = None):
        """state_path=None → in-memory (no persist). Live daemon passes data/forex/breaker_state.json."""
        self.cfg = cfg
        self.state_path = Path(state_path) if state_path else None
        self.state = self._load()

    def _load(self) -> BreakerState:
        if self.state_path is None or not self.state_path.exists():
            return BreakerState()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return BreakerState(**data)
        except Exception as e:
            logger.warning("breaker state load failed: %s; starting fresh", e)
            return BreakerState()

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            _atomic_write(self.state_path, json.dumps(asdict(self.state), indent=2))
        except Exception as e:
            logger.exception("breaker state save failed: %s", e)

    def _parse_until(self, val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    def update(self, equity_usd: float, daily_pnl: float, weekly_pnl: float, monthly_pnl: float,
               consecutive_losses: int, now: datetime,
               monthly_pnl_long: float = 0.0, monthly_pnl_short: float = 0.0) -> tuple[bool, str]:
        self.state.daily_pnl = daily_pnl
        self.state.weekly_pnl = weekly_pnl
        self.state.monthly_pnl = monthly_pnl
        self.state.monthly_pnl_long = monthly_pnl_long
        self.state.monthly_pnl_short = monthly_pnl_short
        self.state.consecutive_losses = consecutive_losses

        blocked_until = self._parse_until(self.state.blocked_until)
        if blocked_until is not None and now < blocked_until:
            return True, "breaker_active"
        # Expire reset
        if blocked_until is not None and now >= blocked_until:
            self.state.blocked_until = None

        if equity_usd <= 0:
            return True, "zero_equity"
        if daily_pnl / equity_usd <= -self.cfg.daily_loss_pct:
            self.state.blocked_until = (now + timedelta(days=1)).isoformat()
            self._save()
            return True, "daily_dd"
        if weekly_pnl / equity_usd <= -self.cfg.weekly_loss_pct:
            self.state.blocked_until = (now + timedelta(days=self.cfg.pause_days)).isoformat()
            self._save()
            return True, "weekly_dd"
        if monthly_pnl / equity_usd <= -self.cfg.monthly_loss_pct:
            self.state.blocked_until = (now + timedelta(days=self.cfg.pause_days * 2)).isoformat()
            self._save()
            return True, "monthly_dd"
        if consecutive_losses >= self.cfg.consecutive_losses:
            self.state.blocked_until = (now + timedelta(days=self.cfg.pause_days)).isoformat()
            self._save()
            return True, "consecutive_losses"

        # Side-conditional checks (only block specific side)
        if monthly_pnl_long / equity_usd <= -self.cfg.monthly_loss_pct_long:
            self.state.blocked_long_until = (now + timedelta(days=self.cfg.pause_days)).isoformat()
        if monthly_pnl_short / equity_usd <= -self.cfg.monthly_loss_pct_short:
            self.state.blocked_short_until = (now + timedelta(days=self.cfg.pause_days)).isoformat()

        self._save()
        return False, ""

    def check_side(self, side: str, now: datetime) -> tuple[bool, str]:
        """Per-side block check."""
        if side == "long":
            until = self._parse_until(self.state.blocked_long_until)
            if until and now < until:
                return True, "side_long_dd"
        elif side == "short":
            until = self._parse_until(self.state.blocked_short_until)
            if until and now < until:
                return True, "side_short_dd"
        return False, ""
