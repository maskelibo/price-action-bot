"""P1c Walker — runtime risk gate ve sizing modülü.

5m P1c bot için canlı walker logic. Backtest pipeline'ı
(`/tmp/5m_research/goal2/run_p1.py`) ile **parite zorunlu** —
parity test: `tests/test_p1c_walker_parity.py`.

Tasarım:
1. **Walker mode: additive-pct** (V14 bug fix — compound walker overflow yaşıyordu)
2. **Halt'lar:**
   - Monthly: MTD exit-realized P/L < -2.5% → kalan ayı SKIP
   - 3-loss 12h (Z1c): 3 ardıl loss → 12h halt
   - Rolling 14d DD: son 14g cumulative < -3% → 14g halt
3. **vol_z sizing (M3a):**
   - high (z >= 2): risk 0.7%
   - normal (0 <= z < 2): risk 0.5%
   - low (z < 0): risk 0.3%
4. **BE-protect:** peak_R >= 0.5 → SL'i breakeven'a çek (0R)
5. **Equity sentinel:** 100 < eq < 1e8 her trade sonrası

State persisted: `data/state/p1c_walker_state.json` (append-only event log).
Restart sonrası rebuild edilir.

Public API:
    walker = P1cWalker(config_path=Path)
    decision = walker.evaluate_signal(sig)
    walker.record_trade_outcome(trade_dict)
    halts = walker.check_halts()
    summary = walker.state_summary()
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# State persistence
_STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "state"
_STATE_FILE = _STATE_DIR / "p1c_walker_state.json"


@dataclass
class P1cConfig:
    """Walker config — `configs/risk_phoenix_scalp_5m_p1c.yaml`'dan yüklenir."""

    # Walker
    walker_mode: str = "additive_pct"

    # Monthly halt
    monthly_loss_pct: float = 0.025  # MTD < -2.5%

    # 3-loss halt (Z1c)
    n_losses: int = 3
    halt_hours: int = 12

    # Rolling 14d DD halt
    rolling_window_days: int = 14
    rolling_threshold_pct: float = -0.03
    rolling_halt_days: int = 14

    # vol_z sizing tiers
    vol_z_tiers: list[dict[str, Any]] = field(default_factory=lambda: [
        {"min": 2.0, "max": 999, "risk_pct": 0.007, "label": "high"},
        {"min": 0.0, "max": 2.0, "risk_pct": 0.005, "label": "normal"},
        {"min": -999, "max": 0.0, "risk_pct": 0.003, "label": "low"},
    ])

    # BE-protect
    be_protect_enabled: bool = True
    be_protect_trigger_R: float = 0.5

    # Equity sentinel
    min_equity_usdt: float = 100.0
    max_equity_usdt: float = 1e8

    # Initial capital
    initial_capital: float = 1000.0

    # Strategy filter (P1c W1: drop engulfing_continuation)
    drop_strategies: list[str] = field(default_factory=lambda: ["engulfing_continuation"])

    # Concurrency
    max_concurrent_positions: int = 3
    per_symbol_cap: int = 1

    @classmethod
    def from_yaml(cls, path: Path) -> "P1cConfig":
        """`configs/risk_phoenix_scalp_5m_p1c.yaml`'ı parse et."""
        if yaml is None:
            return cls()  # fallback default

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return cls()

        cfg = cls()

        # P1c runtime section
        p1c = data.get("p1c_runtime", {})
        cfg.walker_mode = p1c.get("walker_mode", cfg.walker_mode)
        cfg.halt_hours = int(p1c.get("three_loss_window_hours", cfg.halt_hours))
        cfg.rolling_window_days = int(p1c.get("rolling_dd_window_days", cfg.rolling_window_days))
        cfg.rolling_halt_days = int(p1c.get("rolling_dd_halt_days", cfg.rolling_halt_days))
        cfg.rolling_threshold_pct = float(p1c.get("rolling_dd_threshold_pct", cfg.rolling_threshold_pct))
        cfg.be_protect_trigger_R = float(p1c.get("be_protect_trigger_R", cfg.be_protect_trigger_R))

        # Drawdown breakers
        dd = data.get("drawdown_breakers", {})
        cfg.monthly_loss_pct = float(dd.get("monthly_loss_pct", cfg.monthly_loss_pct))
        cl_halt = dd.get("consecutive_loss_halt", {})
        if cl_halt.get("enabled"):
            cfg.n_losses = int(cl_halt.get("n_losses", cfg.n_losses))
            cfg.halt_hours = int(cl_halt.get("halt_hours", cfg.halt_hours))
        es = dd.get("equity_sentinel", {})
        cfg.min_equity_usdt = float(es.get("min_equity_usdt", cfg.min_equity_usdt))
        cfg.max_equity_usdt = float(es.get("max_equity_usdt", cfg.max_equity_usdt))

        # Position sizing tiers
        ps = data.get("position_sizing", {})
        if "vol_z_tiers" in ps:
            cfg.vol_z_tiers = ps["vol_z_tiers"]

        # Take profit
        tp = data.get("take_profit", {})
        cfg.be_protect_enabled = bool(tp.get("be_protect_enabled", cfg.be_protect_enabled))

        # Strategy portfolio
        sp = data.get("strategy_portfolio", {})
        if "drop_strategies" in sp:
            cfg.drop_strategies = sp["drop_strategies"]
        cfg.max_concurrent_positions = int(sp.get("max_concurrent_positions", cfg.max_concurrent_positions))
        cfg.per_symbol_cap = int(sp.get("per_symbol_cap", cfg.per_symbol_cap))

        # Capital
        cap = data.get("capital", {})
        cfg.initial_capital = float(cap.get("initial_usdt", cfg.initial_capital))

        return cfg


class P1cWalker:
    """5m P1c risk walker — runtime gate + sizing."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config = P1cConfig.from_yaml(config_path) if config_path else P1cConfig()
        self._state: dict[str, Any] = self._load_or_init_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_or_init_state(self) -> dict[str, Any]:
        if _STATE_FILE.exists():
            try:
                return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "equity_usdt": self.config.initial_capital,
            "trades": [],            # close olmuş trade'lerin listesi
            "last_loss_times": [],   # son N loss timestamp'leri (3-loss halt için)
            "halts": [],             # aktif halt'lar (release_at, reason)
            "open_positions": {},    # symbol → position dict (per_symbol_cap için)
            "mtd_pnl": 0.0,          # month-to-date realized PnL
            "mtd_month": None,       # "YYYY-MM" — ay değişince reset
        }

    def _save_state(self) -> None:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            _STATE_FILE.write_text(json.dumps(self._state, default=str, indent=2), encoding="utf-8")
        except Exception:
            pass

    def state_summary(self) -> dict[str, Any]:
        return {
            "equity": round(self._state["equity_usdt"], 2),
            "n_trades": len(self._state["trades"]),
            "n_open": len(self._state["open_positions"]),
            "n_active_halts": len(self._state["halts"]),
            "mtd_pnl_pct": round(self._mtd_pnl_pct() * 100, 3),
        }

    def _mtd_pnl_pct(self) -> float:
        equity = self._state["equity_usdt"]
        if equity <= 0:
            return 0.0
        return self._state.get("mtd_pnl", 0.0) / max(self.config.initial_capital, 1.0)

    # ------------------------------------------------------------------
    # Halt logic
    # ------------------------------------------------------------------

    def check_halts(self) -> dict[str, Any]:
        """Aktif halt var mı? Returns {halted: bool, reason: str, release_at: ISO}."""
        now = datetime.now(timezone.utc)
        active_halts = []
        for h in self._state.get("halts", []):
            try:
                release = datetime.fromisoformat(h["release_at"])
                if release > now:
                    active_halts.append(h)
            except Exception:
                pass

        # Expired halts'ı temizle
        if len(active_halts) != len(self._state.get("halts", [])):
            self._state["halts"] = active_halts
            self._save_state()

        if active_halts:
            soonest = min(active_halts, key=lambda h: h["release_at"])
            return {
                "halted": True,
                "reason": soonest.get("reason", "?"),
                "release_at": soonest["release_at"],
                "n_active_halts": len(active_halts),
            }

        # Monthly halt check (MTD < threshold)
        self._refresh_mtd()
        if self._mtd_pnl_pct() < -self.config.monthly_loss_pct:
            return {
                "halted": True,
                "reason": f"monthly_dd_breach (MTD={self._mtd_pnl_pct()*100:.2f}%)",
                "release_at": self._end_of_month().isoformat(),
            }

        # Rolling 14d DD check
        rolling_pct = self._rolling_dd_pct()
        if rolling_pct < self.config.rolling_threshold_pct:
            release = (now + timedelta(days=self.config.rolling_halt_days)).isoformat()
            # Self-add halt event
            self._state["halts"].append({
                "reason": f"rolling_14d_dd_breach ({rolling_pct*100:.2f}%)",
                "release_at": release,
                "added_at": now.isoformat(),
            })
            self._save_state()
            return {
                "halted": True,
                "reason": f"rolling_14d_dd_breach ({rolling_pct*100:.2f}%)",
                "release_at": release,
            }

        # Equity sentinel
        eq = self._state["equity_usdt"]
        if eq < self.config.min_equity_usdt or eq > self.config.max_equity_usdt:
            return {
                "halted": True,
                "reason": f"equity_sentinel_breach (eq={eq:.2f}, range=[{self.config.min_equity_usdt}, {self.config.max_equity_usdt}])",
                "release_at": "never",  # manuel müdahale
            }

        return {"halted": False, "reason": "ok"}

    def _refresh_mtd(self) -> None:
        now = datetime.now(timezone.utc)
        month_key = now.strftime("%Y-%m")
        if self._state.get("mtd_month") != month_key:
            # Ay değişti — reset
            self._state["mtd_month"] = month_key
            self._state["mtd_pnl"] = 0.0
            self._save_state()

    def _end_of_month(self) -> datetime:
        now = datetime.now(timezone.utc)
        if now.month == 12:
            return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0)
        return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0)

    def _rolling_dd_pct(self) -> float:
        """Son 14g cumulative realized PnL / initial_capital."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.rolling_window_days)
        cum = 0.0
        for t in self._state.get("trades", []):
            try:
                close_ts = datetime.fromisoformat(t.get("close_ts", ""))
                if close_ts >= cutoff:
                    cum += float(t.get("pnl_usdt", 0))
            except Exception:
                continue
        return cum / max(self.config.initial_capital, 1.0)

    # ------------------------------------------------------------------
    # Signal evaluation (entry decision)
    # ------------------------------------------------------------------

    def evaluate_signal(self, sig: dict[str, Any]) -> dict[str, Any]:
        """Bir sinyali değerlendir — accept/reject + sizing.

        Returns: {accept: bool, reason: str, risk_pct: float, risk_usdt: float, tier: str}
        """
        # 0. Halt check
        halt = self.check_halts()
        if halt.get("halted"):
            return {"accept": False, "reason": f"halted:{halt.get('reason')}", "risk_pct": 0}

        # 1. Strategy drop filter
        strategy = sig.get("strategy", "")
        if strategy in self.config.drop_strategies:
            return {"accept": False, "reason": f"strategy_dropped:{strategy}", "risk_pct": 0}

        # 2. Per-symbol cap
        symbol = sig.get("symbol", "")
        if symbol in self._state.get("open_positions", {}):
            return {"accept": False, "reason": f"per_symbol_cap_breach:{symbol}", "risk_pct": 0}

        # 3. Max concurrent
        n_open = len(self._state.get("open_positions", {}))
        if n_open >= self.config.max_concurrent_positions:
            return {"accept": False, "reason": f"max_concurrent_breach (open={n_open})", "risk_pct": 0}

        # 4. vol_z tier sizing
        vol_z = float(sig.get("vol_z", 0.0))
        tier = self._select_vol_z_tier(vol_z)
        risk_pct = tier["risk_pct"]
        risk_usdt = self._state["equity_usdt"] * risk_pct

        return {
            "accept": True,
            "reason": "ok",
            "risk_pct": risk_pct,
            "risk_usdt": round(risk_usdt, 2),
            "tier": tier.get("label", "?"),
            "vol_z": vol_z,
        }

    def _select_vol_z_tier(self, vol_z: float) -> dict[str, Any]:
        """vol_z değerine göre uygun tier'ı döndür."""
        for tier in self.config.vol_z_tiers:
            tmin = float(tier.get("min", -999))
            tmax = float(tier.get("max", 999))
            if tmin <= vol_z < tmax:
                return tier
        # fallback: normal tier
        return {"risk_pct": 0.005, "label": "fallback_normal"}

    # ------------------------------------------------------------------
    # Trade outcome recording
    # ------------------------------------------------------------------

    def record_trade_outcome(self, trade: dict[str, Any]) -> None:
        """Bir trade kapandı — state'i güncelle.

        Args:
            trade: {symbol, entry_ts, close_ts, pnl_usdt, r_multiple, side, strategy}
        """
        pnl = float(trade.get("pnl_usdt", 0))
        symbol = trade.get("symbol", "")
        close_ts = trade.get("close_ts", datetime.now(timezone.utc).isoformat())

        # Add to trades log
        self._state.setdefault("trades", []).append({
            "symbol": symbol,
            "entry_ts": trade.get("entry_ts", ""),
            "close_ts": close_ts,
            "pnl_usdt": pnl,
            "r_multiple": float(trade.get("r_multiple", 0)),
            "side": trade.get("side", ""),
            "strategy": trade.get("strategy", ""),
        })

        # Update equity (additive-pct mode)
        if self.config.walker_mode == "additive_pct":
            self._state["equity_usdt"] += pnl
        else:
            # compound — but we don't use it (V14 bug)
            self._state["equity_usdt"] *= (1 + pnl / max(self.config.initial_capital, 1))

        # Update MTD
        self._refresh_mtd()
        self._state["mtd_pnl"] = self._state.get("mtd_pnl", 0.0) + pnl

        # Update 3-loss tracker
        if pnl < 0:
            loss_times = self._state.setdefault("last_loss_times", [])
            loss_times.append(close_ts)
            # Keep last N+1
            self._state["last_loss_times"] = loss_times[-(self.config.n_losses + 1):]

            # 3-loss halt check
            if len(loss_times) >= self.config.n_losses:
                recent_losses = loss_times[-self.config.n_losses:]
                try:
                    earliest = datetime.fromisoformat(recent_losses[0])
                    latest = datetime.fromisoformat(recent_losses[-1])
                    window = (latest - earliest).total_seconds() / 3600  # hours
                    if window <= 12:  # 3 loss within any 12h window
                        release = (latest + timedelta(hours=self.config.halt_hours)).isoformat()
                        self._state.setdefault("halts", []).append({
                            "reason": f"3_loss_halt (window={window:.1f}h)",
                            "release_at": release,
                            "added_at": datetime.now(timezone.utc).isoformat(),
                        })
                except Exception:
                    pass

        # Remove from open positions
        if symbol in self._state.get("open_positions", {}):
            del self._state["open_positions"][symbol]

        self._save_state()

    def record_open_position(self, position: dict[str, Any]) -> None:
        """Yeni pozisyon açıldı — open_positions'a ekle."""
        symbol = position.get("symbol", "")
        if symbol:
            self._state.setdefault("open_positions", {})[symbol] = position
            self._save_state()
