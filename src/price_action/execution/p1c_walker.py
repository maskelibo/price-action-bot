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
# ruff: noqa: N806, N815, SIM105  (pre-existing R-domain adlandırma + benign cleanup guard'ları — 2026-07-10)

from __future__ import annotations

import json
import logging as _logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from price_action.runtime_paths import RuntimePaths

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

_P1C_LOG = _logging.getLogger(__name__)


# State persistence
_STATE_DIR = RuntimePaths.from_env(Path(__file__).resolve().parents[3]).data / "state"
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
    vol_z_tiers: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"min": 2.0, "max": 999, "risk_pct": 0.007, "label": "high"},
            {"min": 0.0, "max": 2.0, "risk_pct": 0.005, "label": "normal"},
            {"min": -999, "max": 0.0, "risk_pct": 0.003, "label": "low"},
        ]
    )

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
    def from_yaml(cls, path: Path) -> P1cConfig:
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
        cfg.rolling_threshold_pct = float(
            p1c.get("rolling_dd_threshold_pct", cfg.rolling_threshold_pct)
        )
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
        cfg.max_concurrent_positions = int(
            sp.get("max_concurrent_positions", cfg.max_concurrent_positions)
        )
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
        """State recovery — partial write/corrupt fallback ile.

        FIX 2026-05-28 (Faz 14.27 C2-3): Önceki bug: JSON corruption (partial
        write crash) → tamamen sıfırdan başla → equity + trades KAYIP. Şimdi
        .bak yedek deniyor önce.

        FIX 2026-05-28 (audit-A4): Hem .json hem .bak corrupt VE state file
        zaten varsa (yani daha önce live olmuş bir bot'un state'i bozulmuşsa)
        → initial_capital'a SESSİZ düşmek yerine CRITICAL alert + raise.
        Sessiz $1000 fallback gerçek $5000 equity'yi 5x undersize sizing'e
        yol açıyordu. Şimdi sistem duruyor, operator manuel intervention.

        Yalnızca state file HİÇ yoksa (ilk kez başlatma) initial_capital
        kullan — bu legitime ilk-kurulum case'i.
        """
        state_file = _STATE_FILE
        bak_file = _STATE_FILE.with_suffix(_STATE_FILE.suffix + ".bak")

        # Önce .json sonra .bak — başarılı parse varsa dön
        for path in (state_file, bak_file):
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue  # corrupt, .bak'ı dene

        # State file hiç yok → ilk kurulum, initial_capital ile başla (güvenli)
        if not state_file.exists() and not bak_file.exists():
            return {
                "equity_usdt": self.config.initial_capital,
                "trades": [],
                "last_loss_times": [],
                "halts": [],
                "open_positions": {},
                "mtd_pnl": 0.0,
                "mtd_month": None,
            }

        # State file VAR ama parse edilemiyor → CORRUPT, sessiz reset TEHLİKELİ
        # (önceki equity bilinmiyor, initial_capital'a düşmek 5x undersize riski)
        msg = (
            f"P1C_WALKER_STATE_CORRUPT: hem {state_file.name} hem {bak_file.name} "
            f"parse edilemedi. initial_capital'a sessiz reset RİSKLİ — sistem "
            f"durdurulup manuel kurtarma gerekli. State file mtime: "
            f"{state_file.stat().st_mtime if state_file.exists() else 'N/A'}"
        )
        # Telegram critical alert (best-effort, fail tolerated)
        try:
            from price_action.orchestrator.notifications import push_critical

            push_critical(f"⚠️ P1c walker state CORRUPT — manuel kurtarma şart. {msg}")
        except Exception:
            pass
        raise RuntimeError(msg)

    def _save_state(self) -> None:
        """Atomic write — tempfile + rename, eski state .bak'a backup.

        FIX 2026-05-28 (Faz 14.27 C2-3): Önceki bug: doğrudan write_text →
        partial write crash → JSON corruption. Şimdi: tempfile + os.replace
        (POSIX atomic rename).

        Concurrent writer korunması: fcntl.flock advisory lock (Unix).
        """
        import os
        import tempfile

        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            # Mevcut state'i .bak'a kopyala (corruption recovery için)
            if _STATE_FILE.exists():
                try:
                    bak = _STATE_FILE.with_suffix(_STATE_FILE.suffix + ".bak")
                    bak.write_bytes(_STATE_FILE.read_bytes())
                except Exception as _bak_err:
                    # log-only: corruption-recovery kopyası alınamadı — görünür olsun
                    _P1C_LOG.warning("p1c.state_bak_copy_fail err=%s", str(_bak_err)[:80])

            # Atomic write: tempfile → rename
            data = json.dumps(self._state, default=str, indent=2)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(_STATE_DIR),
                prefix=".p1c_walker_state.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    # Advisory lock (Unix only, no-op on Windows)
                    try:
                        import fcntl

                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except (ImportError, OSError):
                        pass
                    f.write(data)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                # Atomic rename — POSIX guarantee
                os.replace(tmp_path, _STATE_FILE)
            except Exception:
                # Cleanup tempfile on fail
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass  # Save fail tolerated — sonraki tick tekrar dener

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
        now = datetime.now(UTC)
        active_halts = []
        for h in self._state.get("halts", []):
            try:
                release = datetime.fromisoformat(h["release_at"])
                if release > now:
                    active_halts.append(h)
            except Exception as _rel_err:
                # FAIL-CLOSED (2026-07-10 Principal onayı): release_at parse
                # edilemiyorsa halt eskiden SESSİZCE DÜŞÜYORDU (risk-halt
                # fail-open!). Artık: bozuk-kayıtlı halt AKTİF sayılır (elle
                # temizlenene/veri düzelene dek) + görünür log.
                _P1C_LOG.error(
                    "p1c.halt_release_parse_fail_KEPT reason=%s err=%s",
                    h.get("reason", "?"),
                    str(_rel_err)[:80],
                )
                active_halts.append(h)

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
            self._state["halts"].append(
                {
                    "reason": f"rolling_14d_dd_breach ({rolling_pct*100:.2f}%)",
                    "release_at": release,
                    "added_at": now.isoformat(),
                }
            )
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
        now = datetime.now(UTC)
        month_key = now.strftime("%Y-%m")
        if self._state.get("mtd_month") != month_key:
            # Ay değişti — reset
            self._state["mtd_month"] = month_key
            self._state["mtd_pnl"] = 0.0
            self._save_state()

    def _end_of_month(self) -> datetime:
        """Bir sonraki ay'ın 1'i 00:00 UTC döndürür.

        FIX 2026-05-28 (Faz 14.27 C2-1): Önceki sürümde tzinfo yoktu — naive
        datetime döndürüyordu → isoformat() sonra fromisoformat() parse
        edildiğinde tz bilgisi kaybolup halt expire logic kırılıyordu.
        Şimdi: tzinfo=timezone.utc explicit.
        """
        now = datetime.now(UTC)
        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=UTC,
            )
        return now.replace(
            month=now.month + 1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=UTC,
        )

    def _rolling_dd_pct(self) -> float:
        """Son 14g cumulative realized PnL / initial_capital.

        FIX 2026-05-28 (Faz 14.27 C2-3 ek): close_ts naive parse edilirse
        cutoff (tz-aware) ile karşılaştırma TypeError atar (sessizce continue).
        Şimdi: naive parse sonrası UTC varsay.
        """
        cutoff = datetime.now(UTC) - timedelta(days=self.config.rolling_window_days)
        cum = 0.0
        for t in self._state.get("trades", []):
            try:
                close_ts_str = t.get("close_ts", "")
                close_ts = datetime.fromisoformat(close_ts_str.replace("Z", "+00:00"))
                if close_ts.tzinfo is None:
                    close_ts = close_ts.replace(tzinfo=UTC)
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
            return {
                "accept": False,
                "reason": f"max_concurrent_breach (open={n_open})",
                "risk_pct": 0,
            }

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
        close_ts = trade.get("close_ts", datetime.now(UTC).isoformat())

        # Add to trades log
        self._state.setdefault("trades", []).append(
            {
                "symbol": symbol,
                "entry_ts": trade.get("entry_ts", ""),
                "close_ts": close_ts,
                "pnl_usdt": pnl,
                "r_multiple": float(trade.get("r_multiple", 0)),
                "side": trade.get("side", ""),
                "strategy": trade.get("strategy", ""),
            }
        )

        # Update equity (additive-pct mode)
        if self.config.walker_mode == "additive_pct":
            self._state["equity_usdt"] += pnl
        else:
            # compound — but we don't use it (V14 bug)
            self._state["equity_usdt"] *= 1 + pnl / max(self.config.initial_capital, 1)

        # Update MTD
        self._refresh_mtd()
        self._state["mtd_pnl"] = self._state.get("mtd_pnl", 0.0) + pnl

        # Update 3-loss tracker
        # FIX 2026-05-28 (Faz 14.27 C2-2): Kazanç sonrası loss counter reset.
        # Önceki bug: kazanç (pnl > 0) loss_times'ı temizlemiyordu → false
        # positive halt riski (3 kayıp + 1 kazanç + 1 kayıp = 4 entry varsa
        # 4-bar window'da hala 3-loss tetiklenebilirdi).
        if pnl > 0:
            # Kazanç → counter sıfırla
            self._state["last_loss_times"] = []
        elif pnl < 0:
            loss_times = self._state.setdefault("last_loss_times", [])
            loss_times.append(close_ts)
            # Keep last N+1
            self._state["last_loss_times"] = loss_times[-(self.config.n_losses + 1) :]

            # 3-loss halt check
            if len(loss_times) >= self.config.n_losses:
                recent_losses = loss_times[-self.config.n_losses :]
                try:
                    earliest = datetime.fromisoformat(recent_losses[0].replace("Z", "+00:00"))
                    latest = datetime.fromisoformat(recent_losses[-1].replace("Z", "+00:00"))
                    if earliest.tzinfo is None:
                        earliest = earliest.replace(tzinfo=UTC)
                    if latest.tzinfo is None:
                        latest = latest.replace(tzinfo=UTC)
                    window = (latest - earliest).total_seconds() / 3600  # hours
                    if window <= 12:  # 3 loss within any 12h window
                        release = (latest + timedelta(hours=self.config.halt_hours)).isoformat()
                        self._state.setdefault("halts", []).append(
                            {
                                "reason": f"3_loss_halt (window={window:.1f}h)",
                                "release_at": release,
                                "added_at": datetime.now(UTC).isoformat(),
                            }
                        )
                except Exception as _h3_err:
                    # log-only: 3-loss halt hesabı çöktü → halt EKLENEMEDİ;
                    # bilinmeyen hatadan halt uydurmak yanlış-pozitif üretir,
                    # ama artık en azından GÖRÜNÜR (eski: sessiz).
                    _P1C_LOG.error("p1c.3loss_halt_calc_fail err=%s", str(_h3_err)[:120])

        # Remove from open positions
        if symbol in self._state.get("open_positions", {}):
            del self._state["open_positions"][symbol]

        self._save_state()

    def record_open_position(self, position: dict[str, Any]) -> None:
        """Yeni pozisyon açıldı — open_positions'a ekle.

        Position dict required keys: symbol, side, entry_price, sl_price.
        Optional: tp_price, strategy, risk_pct, risk_usdt, tier, vol_z, entry_ts.
        Auto-add: peak_price, peak_R, be_protected (false initially), original_sl_dist
        (orijinal SL mesafesi — BE sonrası R hesabı için lazım).
        """
        symbol = position.get("symbol", "")
        if symbol:
            entry = float(position.get("entry_price", 0))
            sl = float(position.get("sl_price", 0))
            position.setdefault("peak_price", entry)
            position.setdefault("peak_R", 0.0)
            position.setdefault("be_protected", False)
            position.setdefault("original_sl_dist", abs(entry - sl) if entry > 0 and sl > 0 else 0)
            self._state.setdefault("open_positions", {})[symbol] = position
            self._save_state()

    def check_be_protect(self, current_prices: dict[str, float]) -> list[dict[str, Any]]:
        """BE-protect: open positions için peak_R hesabı + SL'i breakeven'a çek.

        Faz 5.3: P1c spec'in temel "kazançları koru" mekanizması.
        Her open position için:
        1. Güncel fiyatı al (current_prices[symbol])
        2. peak_price güncelle (long: max(peak, current), short: min(peak, current))
        3. peak_R hesabı = (peak - entry) / sl_dist (long) | (entry - peak) / sl_dist (short)
        4. Eğer peak_R >= be_protect_trigger_R (0.5) ve henüz BE protected değilse:
           SL'i entry_price'a çek → "be_protected": True

        Returns: BE'ye çekilen position'ların listesi (for logging).
        """
        if not self.config.be_protect_enabled:
            return []

        be_triggered: list[dict[str, Any]] = []
        positions = self._state.get("open_positions", {})

        for symbol, pos in positions.items():
            if pos.get("be_protected", False):
                continue  # Zaten BE'de

            current = current_prices.get(symbol)
            if current is None or current <= 0:
                continue

            entry = float(pos.get("entry_price", 0))
            sl = float(pos.get("sl_price", 0))
            side = pos.get("side", "")

            if entry <= 0 or sl <= 0:
                continue

            sl_dist = abs(entry - sl)
            if sl_dist <= 0:
                continue

            # Peak update + R hesabı
            if side == "long":
                peak = max(float(pos.get("peak_price", entry)), current)
                peak_R = (peak - entry) / sl_dist
            elif side == "short":
                peak = min(float(pos.get("peak_price", entry)), current)
                peak_R = (entry - peak) / sl_dist
            else:
                continue

            pos["peak_price"] = peak
            pos["peak_R"] = peak_R

            # BE-protect trigger
            if peak_R >= self.config.be_protect_trigger_R:
                old_sl = pos["sl_price"]
                pos["sl_price"] = entry  # SL → breakeven
                pos["be_protected"] = True
                be_triggered.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "entry": entry,
                        "old_sl": old_sl,
                        "new_sl": entry,
                        "peak_R": round(peak_R, 3),
                        "current_price": current,
                    }
                )

        if be_triggered or any(pos.get("peak_R", 0) > 0 for pos in positions.values()):
            self._save_state()

        return be_triggered

    def close_position(
        self,
        symbol: str,
        *,
        close_price: float,
        close_ts: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any] | None:
        """Bir pozisyonu kapat — PnL hesabı + record_trade_outcome.

        Args:
            symbol: Kapanacak pozisyon sembolü.
            close_price: Çıkış fiyatı.
            close_ts: ISO timestamp; yoksa now.
            reason: Kapanış sebebi (sl_hit, tp_hit, manual, be_hit, vb.)

        Returns:
            Trade outcome dict (record_trade_outcome'a verilir), veya None.
        """
        from datetime import datetime as _dt

        positions = self._state.get("open_positions", {})
        if symbol not in positions:
            return None

        pos = positions[symbol]
        entry = float(pos.get("entry_price", 0))
        side = pos.get("side", "")
        risk_usdt = float(pos.get("risk_usdt", 0))

        if entry <= 0 or risk_usdt <= 0:
            return None

        # Faz 5.3: BE-protect sonrası sl_price=entry (sl_dist=0) → original_sl_dist kullan
        sl_dist = float(pos.get("original_sl_dist", 0))
        if sl_dist <= 0:
            # Fallback: hesapla (eski position'lar için)
            sl_dist = abs(entry - float(pos.get("sl_price", 0)))
            if sl_dist <= 0:
                sl_dist = entry * 0.01  # %1 fallback (worst case)

        # R-multiple hesabı
        if side == "long":
            r_mult = (close_price - entry) / sl_dist
        elif side == "short":
            r_mult = (entry - close_price) / sl_dist
        else:
            return None

        pnl_usdt = r_mult * risk_usdt

        outcome = {
            "symbol": symbol,
            "side": side,
            "entry_ts": pos.get("entry_ts", ""),
            "close_ts": close_ts or _dt.now(UTC).isoformat(),
            "entry_price": entry,
            "close_price": close_price,
            "pnl_usdt": round(pnl_usdt, 4),
            "r_multiple": round(r_mult, 4),
            "strategy": pos.get("strategy", ""),
            "reason": reason,
            "be_protected": pos.get("be_protected", False),
        }

        # record_trade_outcome positionı otomatik open_positions'tan siler + state günceller
        self.record_trade_outcome(outcome)
        return outcome
