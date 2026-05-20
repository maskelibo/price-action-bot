"""Position sizing + RiskOfficer karar motoru.

Tüm hard limit yorumları `agents/risk_officer.md` ve `configs/risk.yaml`'den geliyor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from price_action.contracts import (
    Position,
    Reject,
    RiskedOrder,
    Signal,
    TPLevel,
    stable_hash,
)
from price_action.logging_config import logger
from price_action.risk.breaker import DDBreaker
from price_action.risk.gates import (
    concentration_gate,
    correlation_gate,
    leverage_gate,
    liquidity_gate,
)
from price_action.risk.regime_filter import BTCFeatures, CacheFreshnessConfig, PerStrategyRegimeFilter, RegimeCacheStatus, RegimeFilter


# =====================================================================
# Sizing primitives
# =====================================================================

def fixed_fractional(equity: float, risk_pct: float, sl_distance_pct: float) -> float:
    """Fixed fractional sizing.

    Risk yaml'daki `risk_per_trade` (default %1) — sermayenin sabit oranı SL'ye
    kadar risk edilir. Quantity döner (notional değil); çağıran round_step uygular.
    """
    if equity <= 0 or risk_pct <= 0 or sl_distance_pct <= 0:
        return 0.0
    risk_dollar = equity * risk_pct
    # quantity = risk_dollar / (price * sl_distance_pct) — fakat burada price yok
    # bu yüzden notional bazlı kullanılır; çağıran price ile böler.
    notional_at_risk = risk_dollar / sl_distance_pct
    return float(notional_at_risk)


def kelly_capped(
    win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.25
) -> float:
    """Kelly fraction = W - (1-W)/R.

    `cap` ile sınırlanır (default 0.25 — Risk YAML).
    Negatif Kelly → 0 (edge yok).
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    R = avg_win / avg_loss
    if R <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / R
    if f <= 0:
        return 0.0
    return float(min(f, cap))


def atr_normalized_size(
    atr: float, equity: float, risk_pct: float, atr_multiplier_for_sl: float
) -> float:
    """ATR-bazlı sizing: SL = k * ATR; quantity = (equity*risk) / (k*ATR).

    Yani SL'in dolar değeri eşittir risk bütçesine.
    """
    if atr <= 0 or equity <= 0 or risk_pct <= 0 or atr_multiplier_for_sl <= 0:
        return 0.0
    risk_dollar = equity * risk_pct
    sl_dist_dollar = atr_multiplier_for_sl * atr
    qty = risk_dollar / sl_dist_dollar
    return float(qty)


# =====================================================================
# Account state
# =====================================================================

@dataclass
class AccountState:
    """Risk ve Portfolio için hafif hesap durumu snapshot'ı."""

    equity_usdt: float
    free_margin_usdt: float
    open_positions: list[Position] = field(default_factory=list)
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    realized_pnl_month: float = 0.0
    consecutive_losses: int = 0
    last_update: datetime = field(default_factory=_utcnow)

    @property
    def total_open_notional(self) -> float:
        return sum(p.quantity * p.current_price for p in self.open_positions)

    @property
    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.open_positions}


# =====================================================================
# Risk Officer
# =====================================================================

class _RiskConfig(BaseModel):
    """Risk YAML'ın strict olmayan modeli."""
    model_config = ConfigDict(extra="allow")

    position_sizing: dict[str, Any] = Field(default_factory=dict)
    stop_loss: dict[str, Any] = Field(default_factory=dict)
    take_profit: dict[str, Any] = Field(default_factory=dict)
    leverage: dict[str, Any] = Field(default_factory=dict)
    drawdown_breakers: dict[str, Any] = Field(default_factory=dict)
    correlation_gate: dict[str, Any] = Field(default_factory=dict)
    concentration_limits: dict[str, Any] = Field(default_factory=dict)
    liquidity_gate: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    emergency: dict[str, Any] = Field(default_factory=dict)
    live_mode_enabled: bool = False


class RiskOfficer:
    """Deterministik risk karar motoru.

    Decision flow `agents/risk_officer.md`'de — herhangi bir adım reject ise dur.
    Hard limit'ler bypass edilemez; CEO bile yapamaz.
    """

    def __init__(
        self,
        config: dict[str, Any] | _RiskConfig,
        breaker: DDBreaker | None = None,
    ) -> None:
        if isinstance(config, dict):
            self.config = _RiskConfig.model_validate(config)
        else:
            self.config = config
        self.breaker = breaker or DDBreaker(self.config.drawdown_breakers)
        self._log = logger.bind(component="risk_officer")

        # v0.9.6 P3.9 FIX + v0.9.7 F&G: Live alt-data filters.
        # Backtest replay (lab.py) bu filtreleri zaten kullaniyor. Live RiskOfficer
        # da ayni filtreyi okuyor ki backtest ile live ayni karari versin.
        # YAML alt_data block'undan lazy-load. Funding VEYA F&G aktifse yukle.
        self._alt_data_long_skip: dict = {}
        self._alt_data_short_skip: dict = {}
        cfg_dict = self.config.model_dump() if hasattr(self.config, "model_dump") else {}
        alt_cfg = cfg_dict.get("alt_data", {}) or {}
        any_filter_on = (
            alt_cfg.get("funding_filter_enabled", False)
            or alt_cfg.get("fng_short_skip_enabled", False)
        )
        if any_filter_on:
            try:
                # Reuse lab.py helper (single source-of-truth, funding+F&G union)
                from price_action.backtest.lab import _lazy_build_funding_filters
                ls, ss = _lazy_build_funding_filters(alt_cfg)
                self._alt_data_long_skip = ls or {}
                self._alt_data_short_skip = ss or {}
                self._log.bind(
                    long_skip_n=len(self._alt_data_long_skip),
                    short_skip_n=len(self._alt_data_short_skip),
                    funding=alt_cfg.get("funding_filter_enabled", False),
                    fng=alt_cfg.get("fng_short_skip_enabled", False),
                ).info("risk.alt_data.loaded")
            except Exception as exc:
                self._log.bind(err=str(exc)).warning("risk.alt_data.load_fail")

        # SEC26.B-2: Live regime filter (BTC capitulation halt).
        # Backtest replay (lab.py) `btc_halt_calendar` overlay yapıyor; live
        # RiskOfficer aynı calendar'ı kullanır ki backtest/live parity korunsun.
        # YAML regime_filter block'undan lazy-load (compute_btc_capitulation_halt
        # SEC16 LOOK-AHEAD FIX zaten causal — T günü kararı T-1 verisine bakar).
        regime_cfg = cfg_dict.get("regime_filter", {}) or {}
        self.regime_filter: RegimeFilter = RegimeFilter(regime_cfg)

        # SEC54.6d: Per-strategy regime filter (live wiring).
        # YAML regime_filter_per_strategy block'undan lazy-load.
        # enabled=False (default) → no-op, 1d Phoenix v2.0.4 etkilenmez.
        per_strat_cfg = cfg_dict.get("regime_filter_per_strategy", {}) or {}
        self.per_strategy_regime_filter: PerStrategyRegimeFilter = PerStrategyRegimeFilter(per_strat_cfg)
        # Features cache: None → fail-safe ALLOW
        self._regime_features_cache: BTCFeatures | None = None
        self._regime_features_path: str = str(
            per_strat_cfg.get("features_path", "data/regime_features_latest.parquet")
        )
        # SEC58.HIGH-3: Cache freshness config (config-driven thresholds).
        # PA_REGIME_CACHE_STRICT=0 → legacy ALLOW behaviour on missing/stale cache.
        freshness_cfg = per_strat_cfg.get("cache_freshness", {}) or {}
        self._freshness_cfg: CacheFreshnessConfig = CacheFreshnessConfig.from_cfg(freshness_cfg)

        if per_strat_cfg.get("enabled", False):
            self._regime_features_cache, _init_status = self._load_regime_features()
            if _init_status not in (RegimeCacheStatus.FRESH, RegimeCacheStatus.WARN):
                self._log.bind(
                    status=_init_status.value,
                    path=self._regime_features_path,
                ).warning("risk.regime_features.init_status_degraded")

    @classmethod
    def from_yaml(cls, path: str | Path, breaker: DDBreaker | None = None) -> RiskOfficer:
        with Path(path).open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(raw or {}, breaker=breaker)

    # ----- SEC54.6d: regime features loader (SEC58.HIGH-3 staleness tiers) -----
    def _load_regime_features(
        self,
    ) -> tuple[BTCFeatures | None, RegimeCacheStatus]:
        """Load BTCFeatures from parquet cache with staleness classification.

        SEC58.HIGH-3 FIX: previous version returned None on any failure ->
        downstream fail-safe ALLOW silently bypassed the capitulation filter.

        Now returns (features, status) where status drives the decision:
          FRESH       -> ALLOW + no alarm
          WARN        -> ALLOW + WARN log + Telegram
          REJECT      -> REJECT all signals (cron broken 24-48h)
          HARD_REJECT -> REJECT + critical alarm (cron broken >48h)
          MISSING     -> REJECT (strict_mode=True) or ALLOW (strict_mode=False)

        Grace buffer (freshness_cfg.grace_minutes, default 30min) prevents
        a cron that runs a few minutes late from jumping to the next tier.

        Causal guarantee: parquet stores t-1 daily close features written
        by scripts/regime_features_refresh.py at 00:01 UTC daily.

        Returns:
            (BTCFeatures | None, RegimeCacheStatus)
        """
        try:
            import pandas as pd
            from datetime import timezone as _tz

            p = Path(self._regime_features_path)
            if not p.exists():
                self._log.bind(path=str(p)).warning(
                    "regime_features.file_missing"
                )
                status = (
                    RegimeCacheStatus.REJECT
                    if self._freshness_cfg.strict_mode
                    else RegimeCacheStatus.MISSING
                )
                return None, status
            df = pd.read_parquet(p)
            if df.empty:
                self._log.bind(path=str(p)).warning(
                    "regime_features.file_empty"
                )
                status = (
                    RegimeCacheStatus.REJECT
                    if self._freshness_cfg.strict_mode
                    else RegimeCacheStatus.MISSING
                )
                return None, status
            # Latest row (most recently written)
            row = df.iloc[-1]
            fetched_at_raw = row.get("fetched_at", None)
            if fetched_at_raw is None:
                # No fetched_at column: treat as just-loaded (assume fresh)
                fetched_at = datetime.now(_tz.utc)
            elif hasattr(fetched_at_raw, "to_pydatetime"):
                fetched_at = fetched_at_raw.to_pydatetime()
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=_tz.utc)
            else:
                fetched_at = datetime.now(_tz.utc)

            # Classify staleness
            age_hours = (datetime.now(_tz.utc) - fetched_at).total_seconds() / 3600.0
            status = self._freshness_cfg.classify(age_hours)

            if status == RegimeCacheStatus.WARN:
                self._log.bind(
                    age_hours=round(age_hours, 2),
                    warn_threshold=self._freshness_cfg.warn_hours,
                    path=str(p),
                ).warning("regime_features.stale.warn")
                # Telegram alert (throttled — import lazily to avoid circular import)
                try:
                    from price_action.ops import get_telegram_throttle
                    get_telegram_throttle().send_throttled(
                        alert_type="regime_cache_stale_warn",
                        message=(
                            f"WARN: regime features cache is {age_hours:.1f}h old "
                            f"(threshold {self._freshness_cfg.warn_hours}h). "
                            f"Check scripts/regime_features_refresh.py cron."
                        ),
                        level="WARNING",
                    )
                except Exception:
                    pass  # Telegram down -- log already above

            elif status in (RegimeCacheStatus.REJECT, RegimeCacheStatus.HARD_REJECT):
                self._log.bind(
                    age_hours=round(age_hours, 2),
                    status=status.value,
                    path=str(p),
                ).error("regime_features.stale.reject")
                try:
                    from price_action.ops import get_telegram_throttle
                    lvl = "CRITICAL" if status == RegimeCacheStatus.HARD_REJECT else "ERROR"
                    get_telegram_throttle().send_throttled(
                        alert_type="regime_cache_stale_reject",
                        message=(
                            f"{lvl}: regime features cache {age_hours:.1f}h old -- "
                            f"all signals REJECTED until cache refreshes. "
                            f"Path: {p}"
                        ),
                        level=lvl,
                    )
                except Exception:
                    pass
                return None, status

            ts_raw = row.get("ts", None)
            if ts_raw is None:
                return None, RegimeCacheStatus.MISSING
            if hasattr(ts_raw, "date"):
                ts_date = ts_raw.date()
            else:
                from datetime import date as _date
                ts_date = _date.fromisoformat(str(ts_raw))

            features = BTCFeatures(
                ts=ts_date,
                atr_pct_30d=float(row.get("atr_pct_30d", 0.0)),
                return_30d=float(row.get("return_30d", 0.0)),
                return_30d_abs_pct=float(row.get("return_30d_abs_pct", 0.0)),
                ema200_distance_pct=float(row.get("ema200_distance_pct", 0.0)),
                above_ema200=bool(row.get("above_ema200", True)),
                fng_value=float(row.get("fng_value", -1.0)),  # -1 = missing (fail-safe)
                realized_vol_7d_annualized=float(row.get("realized_vol_7d_annualized", 0.0)),
                fetched_at=fetched_at,
            )
            return features, status

        except Exception as exc:  # pragma: no cover (data-load defensive)
            self._log.bind(err=str(exc)).warning("regime_features.load_exception")
            # Exception during load: treat as MISSING
            miss_status = (
                RegimeCacheStatus.REJECT
                if self._freshness_cfg.strict_mode
                else RegimeCacheStatus.MISSING
            )
            return None, miss_status

    # ----- core -----
    def evaluate(
        self,
        signal: Signal,
        account_state: AccountState,
        *,
        market_price: float | None = None,
        atr: float | None = None,
        returns_df: Any = None,  # pandas.DataFrame (her sembol bir kolon, daily returns)
        order_book_depth_usdt: float | None = None,
        minute_volume_usdt: float | None = None,
        category_map: dict[str, str] | None = None,
    ) -> RiskedOrder | Reject:
        """Tek sinyal için decision flow."""
        cfg = self.config

        # 1) Breaker check
        # Neden: agents/risk_officer.md - "Breaker tetiklendi → REJECT"
        breaker_status = self.breaker.snapshot(account_state)
        if any(breaker_status.values()):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="dd_breaker_active",
                detail={"breakers": breaker_status},
            )
        # 1.B) SEC26.B-1: SIDE-CONDITIONAL DD BREAKER (lab.py parity)
        # Backtest engine `lab.py` side-bazlı monthly DD halt uyguluyor
        # (monthly_loss_pct_long=0.15, monthly_loss_pct_short=0.05). Live'da
        # da DDBreaker bunu okuyup, side için ayrı bloke ediyor — long
        # halt'ta short trade'e izin var (ve tersi).
        # check_side: hem combined-halt hem side-halt kontrol eder.
        if not self.breaker.check_side(signal.direction, signal.ts):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="dd_breaker_side_cond",
                detail={
                    "side": signal.direction,
                    "blocked_long_until": self.breaker.state.blocked_long_until,
                    "blocked_short_until": self.breaker.state.blocked_short_until,
                    "blocked_combined_until": self.breaker.state.blocked_combined_until,
                },
            )

        # 1.5) v0.9.6 P3.9 FIX: Alt-data funding filter (signal-day causal).
        # Backtest replay (lab.py) ile parity icin: long sinyal + long-skip gunu = REJECT.
        # Sebep: T 00:00 BTC funding > +0.0001 => overheated long crowd, contrarian skip.
        # Aktif olmasi icin: YAML alt_data.funding_filter_enabled: true
        sig_date = signal.ts.date()
        if signal.direction == "long" and self._alt_data_long_skip.get(sig_date, False):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="alt_data_funding_filter",
                detail={"side": "long", "date": str(sig_date), "rationale": "overheated_long_funding"},
            )
        if signal.direction == "short" and self._alt_data_short_skip.get(sig_date, False):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="alt_data_funding_filter",
                detail={"side": "short", "date": str(sig_date), "rationale": "overshort_squeeze_funding"},
            )

        # 1.6) SEC26.B-2: BTC capitulation regime halt (live wiring).
        # Backtest engine (lab.py) bu halt'u uygulayarak yıllık min pencereyi
        # +%3 -> +%19.8 (6x) çıkarıyor (SEC10 bulgusu). Live RiskOfficer aynı
        # calendar'ı kullanmazsa backtest/live parity kırık -> CRITICAL BLOCKER.
        # Halt bidirectional (long ve short hepsi reject) — capitulation
        # rejiminde new exposure açma.
        if self.regime_filter.is_capitulation(signal.ts):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="regime_capitulation_halt",
                detail={
                    "side": signal.direction,
                    "date": str(sig_date),
                    "rationale": "btc_capitulation_atr_pct_ema200_dd90d",
                },
            )

        # 1.8) SEC54.6d: Per-strategy regime filter (live wiring).
        # SEC58.HIGH-3 FIX: cache staleness now fail-closed (REJECT on stale cache).
        # Previously: _load_regime_features() -> None -> ALLOW on any failure.
        # Now: returns (features, status); REJECT/HARD_REJECT statuses block signal.
        #
        # Backtest sec54_6d_regime_filter_replay.py: 4 filter combo annual +%1935,
        # neg 8/61, mandate 5/5 (vs baseline +%1283, neg 9/61).
        # enabled=False -> immediate no-op (1d Phoenix v2.0.4 unaffected).
        if self.per_strategy_regime_filter.enabled:
            btc_features, cache_status = self._load_regime_features()

            # SEC58.HIGH-3: Fail-closed on stale/missing cache.
            # REJECT and HARD_REJECT mean cron has not refreshed for >24h/48h.
            # The capitulation halt filter (our strongest filter) would be silently
            # disabled if we ALLOW here -- hidden alpha loss + risk exposure.
            # PA_REGIME_CACHE_STRICT=0 restores legacy ALLOW behaviour.
            if cache_status in (RegimeCacheStatus.REJECT, RegimeCacheStatus.HARD_REJECT):
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="regime_cache_stale",
                    detail={
                        "cache_status": cache_status.value,
                        "path": self._regime_features_path,
                        "date": str(sig_date),
                        "rationale": (
                            "regime_features parquet stale or missing; "
                            "check scripts/regime_features_refresh.py cron"
                        ),
                    },
                )
            elif cache_status == RegimeCacheStatus.MISSING and self._freshness_cfg.strict_mode:
                # strict_mode=True (default): MISSING -> REJECT
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="regime_cache_missing",
                    detail={
                        "cache_status": cache_status.value,
                        "path": self._regime_features_path,
                        "date": str(sig_date),
                        "rationale": (
                            "regime_features parquet not found; "
                            "run scripts/regime_features_refresh.py first"
                        ),
                    },
                )

            allow_strat, filter_reason = self.per_strategy_regime_filter.evaluate_strategy_regime_filter(
                strategy=signal.pattern_id,
                side=signal.direction,
                ts=signal.ts,
                btc_features=btc_features,
            )
            if not allow_strat:
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason=f"regime_filter_{filter_reason}",
                    detail={
                        "side": signal.direction,
                        "pattern_id": signal.pattern_id,
                        "filter": filter_reason,
                        "date": str(sig_date),
                    },
                )
        # 2) Sermaye check
        # Neden: free margin yoksa giriş yok
        if account_state.free_margin_usdt <= 0:
            return Reject(
                signal=signal, rejected_by="risk", reason="insufficient_free_margin"
            )

        # 3) Pozisyon limiti
        # Neden: risk.yaml concentration_limits.max_open_positions (default 8)
        max_open = int(cfg.concentration_limits.get("max_open_positions", 8))
        if len(account_state.open_positions) >= max_open:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="max_open_positions_reached",
                detail={"current": len(account_state.open_positions), "max": max_open},
            )

        # 4) Likidite check
        # Neden: agents/risk_officer.md "Order/1m_volume ≤ %1?"
        max_v = float(cfg.liquidity_gate.get("max_order_to_minute_volume", 0.01))
        min_book = float(cfg.liquidity_gate.get("min_book_depth_usdt", 100_000))
        # Provisional notional — sizing aşamasında hassaslaşır.
        liq_ok, liq_reason = liquidity_gate(
            order_notional_usdt=account_state.equity_usdt
            * float(cfg.position_sizing.get("risk_per_trade", 0.01))
            * 50,  # provisional 50x kabaca yeterli; size hesabından sonra net check
            minute_volume_usdt=minute_volume_usdt,
            book_depth_usdt=order_book_depth_usdt,
            max_order_to_minute_volume=max_v,
            min_book_depth_usdt=min_book,
        )
        if not liq_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="liquidity_gate",
                detail={"why": liq_reason},
            )

        # 5) Sizing — fixed_fractional / atr_normalized
        # Neden: risk.yaml position_sizing.method
        risk_pct = float(cfg.position_sizing.get("risk_per_trade", 0.01))
        method = str(cfg.position_sizing.get("method", "fixed_fractional"))
        price = float(market_price if market_price is not None else _entry_price(signal))
        sl_dist_dollar = abs(price - signal.sl_price)
        if sl_dist_dollar <= 0:
            return Reject(signal=signal, rejected_by="risk", reason="invalid_sl_distance")

        if method == "atr_normalized" and atr is not None:
            atr_mult = float(cfg.stop_loss.get("atr_multiplier", 2.0))
            quantity = atr_normalized_size(atr, account_state.equity_usdt, risk_pct, atr_mult)
        else:
            sl_pct = sl_dist_dollar / price
            notional_at_risk = fixed_fractional(account_state.equity_usdt, risk_pct, sl_pct)
            quantity = notional_at_risk / price if price > 0 else 0.0

        # v0.9.2: notional cap per equity — geniş SL trade'lerde oversize'a karşı kalkan.
        # 5y backtest: yillik %64 -> %97, DD -%75 -> -%59. Wide-SL anomalileri otomatik kirpilir.
        notional = quantity * price
        max_notional_pct = float(cfg.position_sizing.get("max_notional_pct_equity", 0.0))
        if max_notional_pct > 0 and notional > account_state.equity_usdt * max_notional_pct:
            cap = account_state.equity_usdt * max_notional_pct
            quantity *= cap / notional if notional > 0 else 0.0
            notional = quantity * price

        # SEC58 FIX: Concentration-aware secondary cap (prevents concentration_gate paradox).
        # Sorun: max_notional_pct_equity (ornek: 0.30) > max_per_symbol_pct (ornek: 0.15) ise
        # sizing 0 pozisyonla bile concentration_gate'i gecemez.
        # Cozum: notional'i max_per_symbol_pct sinirina ayni sembol pozisyonu dusulerek klip.
        # Bu adim concentration_gate reddetmeden once sizing'i uyumlu kilar.
        # Backtest etkisi: yoktur (backtest.lab.py bu cap'i uygulamiyordu — ancak
        # backtest icin concentration_gate da uygulanmiyordu — live parity oruntusu).
        sym_cap_for_sizing = float(cfg.concentration_limits.get("max_per_symbol_pct", 0.0))
        if sym_cap_for_sizing > 0 and account_state.equity_usdt > 0:
            same_sym_notional = sum(
                p.quantity * p.current_price
                for p in account_state.open_positions
                if p.symbol == signal.symbol
            )
            sym_headroom = account_state.equity_usdt * sym_cap_for_sizing - same_sym_notional
            if sym_headroom <= 0:
                # No headroom at all — concentration_gate will reject cleanly.
                pass
            elif notional > sym_headroom:
                # Clip: size down to fit within headroom.
                _notional_before = notional
                quantity *= sym_headroom / notional
                notional = quantity * price
                self._log.bind(
                    symbol=signal.symbol,
                    headroom=round(sym_headroom, 2),
                    notional_before=round(_notional_before, 2),
                    notional_after=round(notional, 2),
                ).debug("risk.sizing.conc_cap_applied")

        # min notional
        min_notional = float(cfg.position_sizing.get("min_quantity_usdt", 20))
        if notional < min_notional:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="below_min_notional",
                detail={"notional": notional, "min": min_notional},
            )

        # 6) Kaldıraç check
        # Neden: risk.yaml leverage.max_portfolio_notional_x_equity (default 4)
        max_x = float(cfg.leverage.get("max_portfolio_notional_x_equity", 4))
        max_per_sym_lev = float(cfg.leverage.get("max_leverage_per_symbol", 3))
        lev_ok, lev_reason, leverage_used = leverage_gate(
            new_notional=notional,
            existing_notional=account_state.total_open_notional,
            equity=account_state.equity_usdt,
            max_portfolio_x=max_x,
            per_symbol_leverage=max_per_sym_lev,
        )
        if not lev_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="leverage_gate",
                detail={"why": lev_reason},
            )

        # 7) Konsantrasyon check
        # Neden: max_per_symbol_pct, max_per_category_pct
        sym_cap = float(cfg.concentration_limits.get("max_per_symbol_pct", 0.20))
        cat_cap = float(cfg.concentration_limits.get("max_per_category_pct", 0.40))
        conc_ok, conc_reason = concentration_gate(
            symbol=signal.symbol,
            new_notional=notional,
            equity=account_state.equity_usdt,
            open_positions=account_state.open_positions,
            max_per_symbol_pct=sym_cap,
            max_per_category_pct=cat_cap,
            category_map=category_map or {},
        )
        if not conc_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="concentration_gate",
                detail={"why": conc_reason},
            )

        # 8) Korelasyon check
        # Neden: yüksek korelasyon = gizli konsantrasyon. > 0.7 → size yarı; > 0.9 REJECT.
        corr_factor = 1.0
        if cfg.correlation_gate.get("enabled", True):
            max_corr = float(cfg.correlation_gate.get("max_pairwise_corr", 0.7))
            hard_block = float(cfg.correlation_gate.get("hard_block_at", 0.9))
            reduction = float(cfg.correlation_gate.get("reduction_factor", 0.5))
            allow, corr_factor = correlation_gate(
                symbol=signal.symbol,
                open_positions=account_state.open_positions,
                returns_df=returns_df,
                max_corr=max_corr,
                hard_block_at=hard_block,
                reduction_factor=reduction,
            )
            if not allow:
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="correlation_gate_hard_block",
                    detail={"corr_factor": corr_factor},
                )
            if corr_factor < 1.0:
                quantity *= corr_factor
                notional = quantity * price

        # 9) SL final — atr/structural daha sıkısı kazanır
        sl_price = signal.sl_price  # signal layer'ı zaten ATR/structural max'i yapmış kabul

        # 10) TP — partial close planı: 1R'da %50 kapat, kalan trail
        primary_R = float(cfg.take_profit.get("primary_R", 2.0))
        partial_R = float(cfg.take_profit.get("partial_close_at_R", 1.0))
        side = signal.direction
        sl_dist = abs(price - sl_price)
        if side == "long":
            tp1 = price + partial_R * sl_dist
            tp2 = price + primary_R * sl_dist
        else:
            tp1 = price - partial_R * sl_dist
            tp2 = price - primary_R * sl_dist
        tp_levels = [
            TPLevel(price=tp1, fraction=0.5),
            TPLevel(price=tp2, fraction=0.5),
        ]

        # 11) Margin safety — likidasyon mesafesi >= 50%
        # Neden: risk.yaml leverage.margin_safety_ratio (0.5)
        margin_safety = float(cfg.leverage.get("margin_safety_ratio", 0.5))
        # Cross margin yaklaşık model: liq_dist_pct ≈ 1/leverage. SL_pct ≤ liq_dist*margin_safety.
        if leverage_used > 0:
            liq_dist_pct = 1.0 / leverage_used
            sl_pct_check = sl_dist / price if price > 0 else 1.0
            if sl_pct_check > liq_dist_pct * margin_safety:
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="margin_safety_violation",
                    detail={
                        "sl_pct": sl_pct_check,
                        "max_sl_pct": liq_dist_pct * margin_safety,
                    },
                )

        # 12) Final stamp — manifest hash
        risked = RiskedOrder(
            signal=signal,
            quantity=quantity,
            notional_usdt=notional,
            leverage=leverage_used,
            sl_price=sl_price,
            tp_levels=tp_levels,
            margin_used=notional / max(leverage_used, 1.0),
            risk_budget_consumed=risk_pct,
            breakers_status=breaker_status,
            correlation_factor=corr_factor,
            manifest_hash=stable_hash(
                {
                    "sig_fp": signal.fingerprint(),
                    "config": cfg.model_dump(),
                    "qty": round(quantity, 8),
                }
            ),
        )
        self._log.bind(
            symbol=signal.symbol,
            qty=quantity,
            notional=notional,
            leverage=leverage_used,
            corr=corr_factor,
        ).info("risk.evaluate.accept")
        return risked


def _entry_price(signal: Signal) -> float:
    """Signal'da explicit `entry_price` yoksa SL ve TP arası referansla yaklaşık.

    Backtest çağıranı genelde `market_price` parametresini geçer; bu yardımcı
    yalnızca emergency fallback'tır.
    """
    md = signal.metadata or {}
    if "entry_price" in md:
        try:
            return float(md["entry_price"])  # type: ignore[arg-type]
        except Exception:
            pass
    # tp ile sl ortalaması iyi bir tahmin değildir — sl/tp arası giriş daha yakın olur.
    if signal.direction == "long":
        return float(signal.sl_price + 0.5 * (signal.tp_price - signal.sl_price) / 3)
    return float(signal.sl_price - 0.5 * (signal.sl_price - signal.tp_price) / 3)


__all__ = [
    "AccountState",
    "RiskOfficer",
    "atr_normalized_size",
    "fixed_fractional",
    "kelly_capped",
]
