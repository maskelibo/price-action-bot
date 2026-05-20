"""Drawdown breaker — günlük/haftalık/aylık/ardışık kayıp tetikleyicileri.

State JSON dosyasında persist edilir. Postgres opsiyonel (Ops Engineer ekler).
Hard limit: tetikleyici aktifken yeni emir atılmaz; mevcut açıklarda manuel onay
(`flatten_all_on_breaker: false`).

SEC26.B-1: Side-conditional monthly DD eklendi (backtest lab.py parity).
  - `monthly_loss_pct_long` ve `monthly_loss_pct_short` ayrı eşikler.
  - Side-bazlı realized PnL tracking (ay başından beri).
  - `check_side(side, ts)` ile long/short ayrı bloke edilir.
  - Backward-compat: side-cond key'leri yoksa combined-only davranış.

SEC-S1: Regime-conditional daily DD (BTC ATR% percentile).
  - `daily_loss_pct_regime_aware: false` (default) → sabit eşik (backward-compat).
  - `true` → BTC ATR% persantil calendar'dan dinamik eşik (volatile rejimde gevşek).
  - `_get_dynamic_daily_threshold(ts)` helper ile live'da da aynı mantık.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from price_action.logging_config import logger
from price_action.settings import get_settings

if TYPE_CHECKING:
    from price_action.risk.sizing import AccountState


@dataclass
class BreakerState:
    """Persisted breaker durumu.

    SEC26.B-1: side-conditional alanlar eklendi (default 0/None — backward compat
    eski state dosyaları için).
    """

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
    # SEC26.B-1: side-conditional monthly DD
    monthly_pnl_long: float = 0.0
    monthly_pnl_short: float = 0.0
    triggered_monthly_long: bool = False
    triggered_monthly_short: bool = False
    # ISO datetime string ("2026-06-15T00:00:00+00:00") veya boş string (None yerine —
    # JSON ile uyumlu). Aktif değilse "" tutulur.
    blocked_long_until: str = ""
    blocked_short_until: str = ""
    blocked_combined_until: str = ""
    # SEC26.B-3: Consecutive-loss cool-down expiry (lab.py parity).
    # Lab.py: counter >= N -> cool_until = now + pause_days, counter reset to 0.
    # Burada: triggered_consecutive=True iken until set edilir; süre dolunca
    # update() içinde otomatik clear (counter halen >= N olabilir; manuel reset
    # de mümkün). Backward-compat: "" = pasif veya eski state.
    blocked_consecutive_until: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _parse_iso(s: str) -> datetime | None:
    """ISO string -> tz-aware datetime; empty/invalid -> None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _fmt_iso(dt: datetime | None) -> str:
    """datetime -> ISO string; None -> ''."""
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat()


class DDBreaker:
    """Drawdown breaker state machine.

    Risk YAML'dan eşikleri okur:
      - daily_loss_pct (default 5%)
      - weekly_loss_pct (default 10%)
      - monthly_loss_pct (default 15%) — combined breaker
      - consecutive_losses (default 6)
      - monthly_loss_pct_long (default None — combined-only)  [SEC26.B-1]
      - monthly_loss_pct_short (default None — combined-only) [SEC26.B-1]
      - monthly_halt_days (default 30)                        [SEC26.B-1]
      - daily_halt_days (default 1)                           [SEC26.B-1]
      - weekly_halt_days (default 7)                          [SEC26.B-1]
      - consecutive_loss_pause_days (default 5)               [SEC26.B-3]
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
        # SEC26.B-1: side-conditional monthly DD
        # None → side-cond pasif (combined-only). Float → side eşiği aktif.
        ml = cfg.get("monthly_loss_pct_long")
        ms = cfg.get("monthly_loss_pct_short")
        self.monthly_pct_long: float | None = float(ml) if ml is not None else None
        self.monthly_pct_short: float | None = float(ms) if ms is not None else None
        # Halt süreleri (lab.py ile parity)
        self.monthly_halt_days = int(cfg.get("monthly_halt_days", 30))
        self.daily_halt_days = int(cfg.get("daily_halt_days", 1))
        self.weekly_halt_days = int(cfg.get("weekly_halt_days", 7))
        # SEC26.B-3: consecutive-loss cool-down period (lab.py parity, default 5g)
        # SEC-SCALP-B1: float cast — scalper preset'ler için sub-day pause
        # (15m: 1.0g, 5m: 0.5g, 1m: 0.25g). int() casti 0.5/0.25'i 0'a yuvarlayarak
        # cool-down'u sessizce devre dışı bırakıyordu (5m/1m live blocker).
        self.consec_pause_days = float(cfg.get("consecutive_loss_pause_days", 5))
        # SEC-S1: Regime-conditional daily DD (lab.py parity için live DDBreaker'da da)
        self.daily_dd_regime_aware: bool = bool(cfg.get("daily_loss_pct_regime_aware", False))
        self.daily_dd_volatile_multiplier: float = float(cfg.get("daily_loss_pct_volatile_multiplier", 2.0))
        self.regime_percentile_low: float = float(cfg.get("regime_percentile_low", 60)) / 100.0
        self.regime_percentile_high: float = float(cfg.get("regime_percentile_high", 90)) / 100.0
        # Pre-built calendar (date -> float persantil [0.0, 1.0]). None → conservative no-op.
        self._btc_atr_percentile_calendar: dict | None = None
        if self.daily_dd_regime_aware:
            self._btc_atr_percentile_calendar = self._load_atr_percentile_calendar(cfg)

        s = get_settings()
        self.state_path: Path = (
            Path(state_path) if state_path else s.logs_dir / "risk" / "breaker_state.json"
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        self._lock = threading.RLock()  # SEC58 CRIT-3: concurrency guard
        self._log = logger.bind(component="dd_breaker")

    # ----- SEC-S1: regime-conditional daily DD -----
    @staticmethod
    def _load_atr_percentile_calendar(cfg: dict) -> dict | None:
        """BTC ATR% persantil calendar'ı lazy-load et.

        Conservative: hata durumunda None döner (feature no-op olur).
        Calendar: date -> float [0.0, 1.0].
        """
        try:
            from price_action.backtest.regime import compute_btc_atr_pct_percentile_calendar
            rolling_window = int(cfg.get("regime_percentile_window", 252))
            return compute_btc_atr_pct_percentile_calendar(period=14, rolling_window=rolling_window)
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).warning("breaker.atr_percentile_calendar_load_fail")
            return None

    def _get_dynamic_daily_threshold(self, ts: datetime) -> float:
        """Verilen timestamp için efektif günlük DD eşiğini hesapla (SEC-S1).

        `daily_dd_regime_aware=False` → sabit `self.daily_pct`.
        `True` → BTC ATR% persantili → linear blend:
          pct <= percentile_low  → self.daily_pct (normal rejim)
          pct >= percentile_high → self.daily_pct × volatile_multiplier
          aralığı               → smooth linear blend
        Calendar yoksa veya tarih bulunamazsa → sabit daily_pct (conservative).

        Args:
            ts: datetime (genellikle now veya trade entry time)

        Returns:
            float — efektif eşik (örn 0.03 normal, 0.06 volatile)
        """
        if not self.daily_dd_regime_aware:
            return self.daily_pct

        cal = self._btc_atr_percentile_calendar
        if cal is None:
            return self.daily_pct

        d = ts.date() if isinstance(ts, datetime) else ts
        pct = cal.get(d)
        if pct is None:
            return self.daily_pct  # conservative

        lo = self.regime_percentile_low
        hi = self.regime_percentile_high
        base = self.daily_pct
        volatile = self.daily_pct * self.daily_dd_volatile_multiplier

        if pct <= lo:
            return base
        if pct >= hi:
            return volatile
        blend = (pct - lo) / (hi - lo)
        return base + blend * (volatile - base)

    # ----- persistence -----
    def _load(self) -> BreakerState:
        if not self.state_path.exists():
            return BreakerState()
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Forward-compat: eski state dosyalarında SEC26.B-1 alanları olmayabilir
            # — BreakerState default değerleri ile doldur.
            valid_keys = set(BreakerState.__dataclass_fields__.keys())
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return BreakerState(**filtered)
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).warning("breaker.load_fail")
            return BreakerState()

    def _save(self) -> None:
        """Atomically persist state using tempfile + os.replace (SEC58 CRIT-3).

        Writes to a sibling tempfile then renames — prevents partial/corrupt
        JSON if the process is killed mid-write.  Called only from within the
        _lock-protected update() / reset() paths, so no additional lock here.
        """
        try:
            dir_ = str(self.state_path.parent)
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.state.to_json(), f, default=str, indent=2)
                os.replace(tmp_path, str(self.state_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:  # pragma: no cover
            logger.bind(err=str(exc)).error("breaker.save_fail")

    def reset(self) -> None:
        with self._lock:  # SEC58 CRIT-3
            self.state = BreakerState()
            self._save()

    # ----- core -----
    def update(
        self,
        account_state: AccountState,
        *,
        side: str | None = None,
        pnl_realized: float = 0.0,
        now: datetime | None = None,
    ) -> dict[str, bool]:
        """Hesap durumuna göre tetiklemeleri günceller, snapshot döner.

        SEC26.B-1: side ve pnl_realized opsiyonel.
          - side=None → backward-compat (combined-only update).
          - side='long' veya 'short' + pnl_realized: side-bazlı PnL tracking
            yapılır, side-cond breaker eşikleri kontrol edilir.

        `now` parametresi test/determinizm için injectable (default UTC now).
        """
        with self._lock:  # SEC58 CRIT-3: transactional reset + save
            equity = account_state.equity_usdt
            now = now or datetime.now(timezone.utc)
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
                # SEC26.B-1: side-bazlı pnl ve trigger flag'leri ayda reset
                self.state.monthly_pnl_long = 0.0
                self.state.monthly_pnl_short = 0.0
                self.state.triggered_monthly_long = False
                self.state.triggered_monthly_short = False
                # NOT: blocked_*_until ay başında otomatik resetlenmez — halt süresi
                # ay sınırını geçebilir; sadece süre dolunca aktif olmaz.

            # P&L hesapla (combined).
            # SEC26.B-4: daily_pnl artık realized-only (futures_trades_closed SUM),
            # equity-delta yerine. Açık pozisyon unrealized swings daily_pnl'i
            # kirletmesin → DD breaker erken/yanlış tetiklenmesin.
            # account_state.realized_pnl_today bu pencereyi taşır (build_*_account_state
            # `realized_pnl_today_futures()` → TradeJournal.get_realized_pnl_today).
            # Weekly/monthly hala equity-delta (kapsadığı pencere geniş, mark-to-market
            # gürültüsü bir günlük etkisinin küçük katmanı; lab.py parity ile uyumlu).
            self.state.daily_pnl = float(account_state.realized_pnl_today)
            self.state.weekly_pnl = equity - self.state.weekly_anchor_equity
            self.state.monthly_pnl = equity - self.state.monthly_anchor_equity
            self.state.consecutive_losses = account_state.consecutive_losses

            # SEC26.B-1: side-bazlı realized PnL feed (closed trade event)
            if side is not None and pnl_realized != 0.0:
                side_l = side.lower()
                if side_l == "long":
                    self.state.monthly_pnl_long += float(pnl_realized)
                elif side_l == "short":
                    self.state.monthly_pnl_short += float(pnl_realized)

            # Tetikleyici kontrolleri
            # Neden: risk.yaml drawdown_breakers — bu eşikler insan principal tarafından konur
            # ve algoritma tarafından bypass edilemez.
            # SEC-S1: Regime-conditional daily DD (volatile rejimde gevşek eşik).
            _eff_daily_pct = self._get_dynamic_daily_threshold(now)
            self.state.triggered_daily = (
                self.state.daily_anchor_equity > 0
                and -self.state.daily_pnl / self.state.daily_anchor_equity >= _eff_daily_pct
            )
            self.state.triggered_weekly = (
                self.state.weekly_anchor_equity > 0
                and -self.state.weekly_pnl / self.state.weekly_anchor_equity >= self.weekly_pct
            )
            self.state.triggered_monthly = (
                self.state.monthly_anchor_equity > 0
                and -self.state.monthly_pnl / self.state.monthly_anchor_equity >= self.monthly_pct
            )
            # SEC26.B-3: Consecutive-loss cool-down semantik (lab.py parity).
            # Lab.py: counter >= N -> cool_until = now + pause_days, counter reset.
            # Burada: cool-down aktif iken trigger=True; süre dolunca auto-clear.
            # Counter source: account_state.consecutive_losses (journal query).
            cool_until_dt = _parse_iso(self.state.blocked_consecutive_until)
            if cool_until_dt is not None and now >= cool_until_dt:
                # Cool-down süresi doldu -> auto-clear
                self.state.blocked_consecutive_until = ""
                self.state.triggered_consecutive = False
                cool_until_dt = None
            if cool_until_dt is not None:
                # Cool-down halen aktif (now < expiry)
                self.state.triggered_consecutive = True
            elif self.state.consecutive_losses >= self.max_consec:
                # Yeni tetikleme: cool-down başlat
                self.state.blocked_consecutive_until = _fmt_iso(
                    now + timedelta(days=self.consec_pause_days)
                )
                self.state.triggered_consecutive = True
            else:
                # Eşik altında ve cool-down yok -> idle
                self.state.triggered_consecutive = False

            # SEC26.B-1: side-cond eşik check
            # lab.py mantığı: long_loss_pct = -monthly_long_pnl / monthly_anchor (if pnl<0).
            if (
                self.monthly_pct_long is not None
                and self.state.monthly_anchor_equity > 0
                and self.state.monthly_pnl_long < 0
            ):
                long_loss_pct = -self.state.monthly_pnl_long / self.state.monthly_anchor_equity
                if long_loss_pct >= self.monthly_pct_long:
                    if not self.state.triggered_monthly_long:
                        # İlk tetiklemede halt süresini ayarla
                        self.state.blocked_long_until = _fmt_iso(
                            now + timedelta(days=self.monthly_halt_days)
                        )
                    self.state.triggered_monthly_long = True
            if (
                self.monthly_pct_short is not None
                and self.state.monthly_anchor_equity > 0
                and self.state.monthly_pnl_short < 0
            ):
                short_loss_pct = -self.state.monthly_pnl_short / self.state.monthly_anchor_equity
                if short_loss_pct >= self.monthly_pct_short:
                    if not self.state.triggered_monthly_short:
                        self.state.blocked_short_until = _fmt_iso(
                            now + timedelta(days=self.monthly_halt_days)
                        )
                    self.state.triggered_monthly_short = True

            # Combined daily/weekly/monthly tetiklemeleri için blocked_combined_until
            # (yumuşak yardımcı — RiskOfficer mevcut behavior'u snapshot any() ile zaten reject).
            if self.state.triggered_daily:
                self.state.blocked_combined_until = _fmt_iso(
                    now + timedelta(days=self.daily_halt_days)
                )
            elif self.state.triggered_weekly:
                self.state.blocked_combined_until = _fmt_iso(
                    now + timedelta(days=self.weekly_halt_days)
                )
            elif self.state.triggered_monthly:
                self.state.blocked_combined_until = _fmt_iso(
                    now + timedelta(days=self.monthly_halt_days)
                )

            self._save()

            # SEC26.C-2: Send throttled alarms for triggers
            self._send_trigger_alarms()

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

    # ----- SEC26.B-1: side-conditional API -----
    def check_side(self, side: str, ts: datetime | None = None) -> bool:
        """Verilen side için yeni emir izinli mi? True = izin, False = REJECT.

        Side-cond key yoksa (monthly_pct_long/short None) sadece combined breakers
        kontrol edilir (backward-compat).

        Halt süre kontrolü: blocked_<side>_until > ts ise bloke.
        Eğer triggered flag aktif ama until tarihi geçmişse → halt süresi doldu,
        flag yumuşatılır (auto-recovery; lab.py'de bloke geçici, ay reset'inde
        tamamen siliniyor).

        ts=None → şimdi (UTC).
        """
        ts = ts or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        side_l = (side or "").lower()

        # Combined halt — herhangi bir combined breaker aktifse her iki side bloke.
        blocked_comb = _parse_iso(self.state.blocked_combined_until)
        if blocked_comb is not None and ts < blocked_comb:
            return False
        # Combined trigger flag'leri snapshot tarafından update edildi ama until
        # parse edilemiyorsa flag'e da bak (savunmacı).
        if self.state.triggered_daily or self.state.triggered_weekly or self.state.triggered_monthly:
            return False
        if self.state.triggered_consecutive:
            return False

        # Side-cond halt
        if side_l == "long":
            blk = _parse_iso(self.state.blocked_long_until)
            if blk is not None and ts < blk:
                return False
        elif side_l == "short":
            blk = _parse_iso(self.state.blocked_short_until)
            if blk is not None and ts < blk:
                return False

        return True

    def record_realized_pnl(
        self,
        account_state: AccountState,
        *,
        side: str,
        pnl_realized: float,
        now: datetime | None = None,
    ) -> dict[str, bool]:
        """Kapanan trade event hook — side-bazlı PnL state'i günceller.

        Daemon/execution_chief kapatılan trade için bu fonksiyonu çağırır:
          breaker.record_realized_pnl(acct, side="long", pnl_realized=-25.0)

        Çağrı sonrası snapshot döner; side breaker tetiklendiyse log üretir.
        """
        snap = self.update(
            account_state,
            side=side,
            pnl_realized=pnl_realized,
            now=now,
        )
        if side.lower() == "long" and self.state.triggered_monthly_long:
            self._log.bind(
                pnl=pnl_realized,
                monthly_long_pnl=self.state.monthly_pnl_long,
                threshold=self.monthly_pct_long,
                blocked_until=self.state.blocked_long_until,
            ).warning("breaker.monthly_long.triggered")
        if side.lower() == "short" and self.state.triggered_monthly_short:
            self._log.bind(
                pnl=pnl_realized,
                monthly_short_pnl=self.state.monthly_pnl_short,
                threshold=self.monthly_pct_short,
                blocked_until=self.state.blocked_short_until,
            ).warning("breaker.monthly_short.triggered")
        return snap

    def _send_trigger_alarms(self) -> None:
        """Send throttled Telegram alarms for active triggers (SEC26.C-2)."""
        try:
            from price_action.ops import get_telegram_throttle

            throttle = get_telegram_throttle()

            if self.state.triggered_daily:
                daily_loss_pct = (
                    -self.state.daily_pnl / self.state.daily_anchor_equity * 100
                    if self.state.daily_anchor_equity > 0
                    else 0
                )
                throttle.send_throttled(
                    "daily_dd_halt",
                    f"Daily DD breaker triggered: {daily_loss_pct:.1f}% loss (threshold {self.daily_pct*100:.0f}%)",
                    level="CRITICAL",
                )
            if self.state.triggered_weekly:
                weekly_loss_pct = (
                    -self.state.weekly_pnl / self.state.weekly_anchor_equity * 100
                    if self.state.weekly_anchor_equity > 0
                    else 0
                )
                throttle.send_throttled(
                    "weekly_dd_halt",
                    f"Weekly DD breaker triggered: {weekly_loss_pct:.1f}% loss (threshold {self.weekly_pct*100:.0f}%)",
                    level="CRITICAL",
                )
            if self.state.triggered_monthly:
                monthly_loss_pct = (
                    -self.state.monthly_pnl / self.state.monthly_anchor_equity * 100
                    if self.state.monthly_anchor_equity > 0
                    else 0
                )
                throttle.send_throttled(
                    "monthly_dd_halt",
                    f"Monthly DD breaker triggered: {monthly_loss_pct:.1f}% loss (threshold {self.monthly_pct*100:.0f}%)",
                    level="CRITICAL",
                )
            if self.state.triggered_consecutive:
                throttle.send_throttled(
                    "consecutive_losses_halt",
                    f"Consecutive losses breaker triggered: {self.state.consecutive_losses} consecutive (threshold {self.max_consec})",
                    level="CRITICAL",
                )
            if self.state.triggered_monthly_long:
                long_loss_pct = (
                    -self.state.monthly_pnl_long / self.state.monthly_anchor_equity * 100
                    if self.state.monthly_anchor_equity > 0
                    else 0
                )
                throttle.send_throttled(
                    "monthly_dd_long_halt",
                    f"Monthly long DD breaker triggered: {long_loss_pct:.1f}% loss (threshold {self.monthly_pct_long*100:.0f}%)",
                    level="CRITICAL",
                )
            if self.state.triggered_monthly_short:
                short_loss_pct = (
                    -self.state.monthly_pnl_short / self.state.monthly_anchor_equity * 100
                    if self.state.monthly_anchor_equity > 0
                    else 0
                )
                throttle.send_throttled(
                    "monthly_dd_short_halt",
                    f"Monthly short DD breaker triggered: {short_loss_pct:.1f}% loss (threshold {self.monthly_pct_short*100:.0f}%)",
                    level="CRITICAL",
                )
        except Exception:
            # Fail-safe: alarm send failure should not crash breaker logic
            pass
