"""SEC26.B-2 — Live RiskOfficer wiring for BTC capitulation regime filter.

Backtest engine (lab.py) zaten `regime_filter.btc_capitulation_halt_enabled`
flag'ini okuyup `compute_btc_capitulation_halt()` ile bir date->bool calendar
kuruyor ve replay'de yeni pozisyon açmıyor (yıllık min pencere +%3 -> +%19.8,
6x; SEC10 bulgusu). AMA live `RiskOfficer.evaluate()` ayrı bir mekanizma
kullanmadıkça bu halt'u TANIMAYACAK -> backtest/live parity KIRIK.

Bu modül backtest assumption'unu live'a port eder:

  RegimeFilter(cfg).is_capitulation(ts) -> bool

Sticky halt mantığı + causal hesap (T günü kararı T-1 verisine bakar)
`price_action.backtest.regime.compute_btc_capitulation_halt` içinde yapılır
(SEC16 LOOK-AHEAD FIX zaten orada). Burada onu lazy-load edip ts.date()
ile sorguluyoruz.

Kullanım pattern'i F&G short-skip ile parallel (sizing.py'da):
  - YAML alt_data.fng_short_skip_enabled flag'i lab.py funding+F&G calendar
    döndürüyor, RiskOfficer onu okuyup `evaluate()` icinde direkt reject.
  - Aynı şekilde regime_filter.btc_capitulation_halt_enabled flag'i bu modulu
    aktif eder, RiskOfficer evaluate() içinde `is_capitulation(signal.ts)`
    True -> Reject(reason="regime_capitulation_halt").

KISITLAR:
- Causal: T günü kararı T-1 close-of-day verisiyle (regime.py shift(1) zaten yapar)
- Conservative on missing data: BTC data yoksa veto YAPMA (F&G ile aynı pattern,
  false-negative kabul). Live'da kısa süreli bir BTC veri kesintisi tüm trade'i
  bloke etmemeli.
- Bidirectional: long + short hepsi reject (sec10 bulgusu — capitulation hem
  long'lar için riskli (continuation bear) hem short'lar için riskli (short
  squeeze rebound))
- Backward compat: enabled=False (veya YAML'da regime_filter key yok) -> no-op.

SEC54.6d — Per-strategy regime conditional filter (live wiring).

Backtest (sec54_6d_regime_filter_replay.py) 4 filter'ın causal t-1 BTC daily
feature lookup ile birlikte uygulandığında +%1935 annual / 8 neg ay (mandate 5/5)
ürettiğini kanıtladı. Bu modül o filter logic'ini live'a port eder:

  RegimeFilter.evaluate_strategy_regime_filter(strategy, side, ts, btc_features)
    -> (allow: bool, reason: str | None)

KISITLAR:
- Causal-paranoid: BTCFeatures.ts = t-1 daily close. Signal ts → lookup_date =
  ts.date() - timedelta(days=1). Asla ts.date() veya gelecek gün kullanma.
- Fail-safe: stale features (>max_age_hours) veya missing data → ALLOW
  (false-negative kabul, false-positive değil).
- Backward compat: regime_filter_per_strategy.enabled=False → no-op, byte-identical.
- 1d Phoenix v2.0.4 DOKUNULMAZ: risk_phoenix_v204.yaml bu block'u içermez,
  enabled=False default ile tamamen no-op.
"""
from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from price_action.logging_config import logger


class RegimeFilter:
    """BTC capitulation halt — date-keyed calendar lookup.

    Calendar lazy-build edilir (constructor anında compute_btc_capitulation_halt
    çağrılır). Production-runtime'da BTC OHLCV verisinin available olduğu varsayılır;
    eğer load fail olursa calendar boş kalır ve filter no-op (False döner) hale gelir
    — conservative-on-missing-data tasarımı.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        # YAML key: regime_filter.btc_capitulation_halt_enabled (lab.py ile aynı)
        self.enabled: bool = bool(cfg.get("btc_capitulation_halt_enabled", False))
        # Parametreler — lab.py'deki _lazy_build_btc_halt ile aynı default'lar
        self.atr_pct_threshold: float = float(cfg.get("atr_pct_threshold", 6.0))
        self.ema200_streak_threshold: int = int(cfg.get("ema200_streak_days", 10))
        self.dd_90d_threshold: float = float(cfg.get("dd_90d_threshold_pct", -25.0))
        self.resume_atr_threshold: float = float(cfg.get("resume_atr_threshold", 4.0))
        self.resume_streak_days: int = int(cfg.get("resume_streak_days", 5))

        self._log = logger.bind(component="regime_filter")
        self._calendar: dict[_date, bool] = {}

        if not self.enabled:
            self._log.bind(enabled=False).info("regime_filter.disabled")
            return

        # Lazy build calendar (BTC OHLCV gerekli) — conservative on failure
        try:
            from price_action.backtest.regime import (
                compute_btc_capitulation_halt,
            )
            cal = compute_btc_capitulation_halt(
                atr_threshold=self.atr_pct_threshold,
                ema200_streak_threshold=self.ema200_streak_threshold,
                dd_90d_threshold=self.dd_90d_threshold,
                resume_atr_threshold=self.resume_atr_threshold,
                resume_streak_days=self.resume_streak_days,
            )
            # Filtre: sadece True olan günleri tut (compact lookup)
            self._calendar = {d: True for d, halt in cal.items() if halt}
            self._log.bind(
                enabled=True,
                halt_days=len(self._calendar),
                total_days=len(cal),
                atr_thr=self.atr_pct_threshold,
                ema200_streak=self.ema200_streak_threshold,
                dd_90d_thr=self.dd_90d_threshold,
            ).info("regime_filter.loaded")
        except Exception as exc:  # pragma: no cover (data-load defensive)
            # Conservative: BTC data yoksa veto YAPMA (no-op).
            self._calendar = {}
            self._log.bind(err=str(exc)).warning("regime_filter.load_fail")

    def is_capitulation(self, ts: datetime | _date) -> bool:
        """T zamanında (ts) capitulation halt aktif mi?

        Args:
            ts: signal timestamp (datetime) veya date. Calendar date-keyed.

        Returns:
            True -> halt aktif, sinyal reject edilmeli.
            False -> halt yok, sinyal sizing'e devam.

        Causal: calendar'ın kendisi T günü için T-1 verisine baktığından
        burada ek shift gerekmez (compute_btc_capitulation_halt SEC16 fix).
        Conservative: data yoksa False döner.
        """
        if not self.enabled:
            return False
        if not self._calendar:
            return False  # conservative: data yoksa veto yapma
        d = ts.date() if isinstance(ts, datetime) else ts
        return bool(self._calendar.get(d, False))



# =====================================================================
# SEC54.6d — BTCFeatures dataclass (cached daily, causal t-1)
# =====================================================================

@dataclass
class BTCFeatures:
    """BTC daily regime features snapshot (t-1 causal lookup).

    Tüm alanlar T-1 daily close'dan hesaplanır. Live'da
    `scripts/regime_features_refresh.py` 0:01 UTC'de günceller.

    Birim notları (pre-reg §10.A ile tutarlı):
      - atr_pct_30d: yüzde (örn 3.96 = %3.96)
      - return_30d:  yüzde (örn -10.5 = -%10.5)
      - return_30d_abs_pct: abs(return_30d) yüzde
      - ema200_distance_pct: (close - ema200) / ema200 * 100
      - above_ema200: close >= ema200
      - fng_value: 0-100 skala
      - realized_vol_7d_annualized: yüzde (örn 85.6 = %85.6 annualized)
      - ts: t-1 daily close date (causal anchor)
      - fetched_at: datetime bu snapshot alındığında (staleness check için)
    """

    ts: _date                         # t-1 daily close (CAUSAL)
    atr_pct_30d: float                # BTC ATR% 30-day average
    return_30d: float                 # BTC 30g return (percent)
    return_30d_abs_pct: float         # abs(return_30d)
    ema200_distance_pct: float        # (close-ema200)/ema200 * 100
    above_ema200: bool                # close >= ema200
    fng_value: float                  # Fear & Greed 0-100
    realized_vol_7d_annualized: float # % annualized realized vol
    fetched_at: datetime              # staleness timestamp


# =====================================================================
# SEC54.6d — Per-strategy regime filter
# =====================================================================

# Strateji isim eşlemesi: Signal.pattern_id prefix → strateji adı.
# lab.py pool'da strategy kolonu şu strateji adlarını kullanıyor; live'da
# Signal.pattern_id bu prefix'lerle başlıyor.
_STRATEGY_PATTERN_PREFIX: dict[str, str] = {
    "anchored_vwap_reversal": ("avwap_long_reversal", "avwap_short_reversal"),
    "brooks_failed_breakout": ("brooks_failed_breakout",),
    "vsa_climax_test": ("vsa_climax_test",),
    "engulfing_continuation": ("engulfing_continuation", "engulfing_bull", "engulfing_bear"),
}


def _pattern_to_strategy(pattern_id: str) -> str | None:
    """Signal.pattern_id -> strateji adı. Eşleşme yoksa None."""
    for strategy, prefixes in _STRATEGY_PATTERN_PREFIX.items():
        for pfx in prefixes:
            if pattern_id.startswith(pfx):
                return strategy
    return None


class PerStrategyRegimeFilter:
    """SEC54.6d — 4 per-strategy regime conditional filter.

    YAML `regime_filter_per_strategy` block'undan konfigürasyon okur.
    Backtest SEC54.6d PASS sonuçları:
      Annual +%1935, neg 8/61, mandate 5/5 (vs baseline +%1283, neg 9/61).

    Filter listesi (pre-reg §1):
      F1: anchored_vwap_reversal + BOTH sides
          BTC ATR% < 3.0% AND |return_30d| < 3% → SKIP (range rejim)
      F2: brooks_failed_breakout + SHORT only
          above_ema200 AND return_30d > +5% → SKIP (strong bull)
      F3: vsa_climax_test + LONG only
          fng < 15 AND return_30d < -10% → SKIP (deep bear capitulation)
      F4: engulfing_continuation + BOTH sides
          realized_vol_7d_ann > 100% → SKIP (extreme vol)

    Fail-safe: stale features (>max_age_hours) veya missing data → ALLOW.
    Backward compat: enabled=False → no-op.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        self.enabled: bool = bool(cfg.get("enabled", False))
        self.max_age_hours: float = float(cfg.get("features_max_age_hours", 24))
        self._log = logger.bind(component="per_strategy_regime_filter")

        # Thresholds from YAML filters block (with safe defaults matching pre-reg)
        filters_cfg = cfg.get("filters", {}) or {}

        f1 = filters_cfg.get("F1_avwap_range", {}) or {}
        self.f1_atr_pct_lt: float = float(f1.get("btc_atr_pct_lt", 3.0))
        self.f1_ret30_abs_lt: float = float(f1.get("btc_return_30d_abs_lt_pct", 3.0))

        f2 = filters_cfg.get("F2_brooks_fb_bull", {}) or {}
        self.f2_ema200_above: bool = bool(f2.get("btc_ema200_above", True))
        self.f2_ret30_gt: float = float(f2.get("btc_return_30d_gt_pct", 5.0))

        f3 = filters_cfg.get("F3_vsa_bear", {}) or {}
        self.f3_fng_lt: float = float(f3.get("btc_fng_lt", 15.0))
        self.f3_ret30_lt: float = float(f3.get("btc_return_30d_lt_pct", -10.0))

        f4 = filters_cfg.get("F4_engulfing_high_vol", {}) or {}
        self.f4_vol7d_ann_gt: float = float(f4.get("btc_realized_vol_7d_annualized_gt_pct", 100.0))

        if self.enabled:
            self._log.bind(
                f1_atr_lt=self.f1_atr_pct_lt,
                f1_ret30_abs_lt=self.f1_ret30_abs_lt,
                f2_ret30_gt=self.f2_ret30_gt,
                f3_fng_lt=self.f3_fng_lt,
                f3_ret30_lt=self.f3_ret30_lt,
                f4_vol7d_gt=self.f4_vol7d_ann_gt,
            ).info("per_strategy_regime_filter.loaded")

    def _is_stale(self, features: BTCFeatures) -> bool:
        """Features staleness check — stale → fail-safe ALLOW."""
        age_hours = (
            datetime.now(timezone.utc) - features.fetched_at
        ).total_seconds() / 3600
        return age_hours > self.max_age_hours

    def evaluate_strategy_regime_filter(
        self,
        strategy: str,
        side: Literal["long", "short", "LONG", "SHORT"],
        ts: datetime,
        btc_features: BTCFeatures | None,
    ) -> tuple[bool, str | None]:
        """Per-strategy regime filter evaluation.

        Args:
            strategy: strateji adı (Signal.pattern_id'dan türetilmiş veya direkt).
            side: "long" veya "short" (case-insensitive).
            ts: signal timestamp (15m bar close, t). Features lookup t-1.
            btc_features: BTCFeatures snapshot. None → fail-safe ALLOW.

        Returns:
            (allow, reason):
              allow=True  → sinyal geçti, devam et.
              allow=False → sinyal reddedilmeli; reason='F1'/'F2'/'F3'/'F4'.

        Causal guarantee: btc_features.ts MUST be ts.date() - timedelta(days=1).
        Bu kontrolü çağıran `_load_regime_features()` garanti eder.

        Fail-safe: features None, stale veya F&G missing → ALLOW.
        """
        if not self.enabled:
            return True, None

        if btc_features is None:
            self._log.debug("per_strategy_regime_filter.no_features.allow")
            return True, None

        if self._is_stale(btc_features):
            self._log.bind(
                fetched_at=str(btc_features.fetched_at),
                max_age_h=self.max_age_hours,
            ).warning("per_strategy_regime_filter.stale_features.allow")
            return True, None

        side_l = side.lower()

        # Strategy name: direct match or via pattern_id prefix resolution
        strat = _pattern_to_strategy(strategy) or strategy

        # ----------------------------------------------------------------
        # F1: anchored_vwap_reversal — BOTH sides — range rejim skip
        # Condition: BTC ATR%_30d < threshold AND |return_30d| < threshold
        # Backtest contribution: -1 neg ay, +56pp annual (F1 alone)
        # ----------------------------------------------------------------
        if strat == "anchored_vwap_reversal":
            f1_range = (
                btc_features.atr_pct_30d < self.f1_atr_pct_lt
                and btc_features.return_30d_abs_pct < self.f1_ret30_abs_lt
            )
            if f1_range:
                self._log.bind(
                    strategy=strat,
                    side=side_l,
                    atr_pct=btc_features.atr_pct_30d,
                    ret30_abs=btc_features.return_30d_abs_pct,
                    filter="F1",
                ).debug("per_strategy_regime_filter.reject")
                return False, "F1_avwap_range"

        # ----------------------------------------------------------------
        # F2: brooks_failed_breakout — SHORT only — strong bull skip
        # Condition: above_ema200 AND return_30d > +5%
        # Backtest contribution: +1 neg ay (worsened) but +602pp annual
        # (alpha from correctly skipping failed short setups in strong bull)
        # ----------------------------------------------------------------
        elif strat == "brooks_failed_breakout":
            if side_l == "short":
                f2_bull = (
                    btc_features.above_ema200
                    and btc_features.return_30d > self.f2_ret30_gt
                )
                if f2_bull:
                    self._log.bind(
                        strategy=strat,
                        side=side_l,
                        above_ema200=btc_features.above_ema200,
                        ret30=btc_features.return_30d,
                        filter="F2",
                    ).debug("per_strategy_regime_filter.reject")
                    return False, "F2_brooks_fb_bull"

        # ----------------------------------------------------------------
        # F3: vsa_climax_test — LONG only — deep bear capitulation skip
        # Condition: fng < 15 AND return_30d < -10%
        # Backtest contribution: -1 neg ay, +114pp annual
        # ----------------------------------------------------------------
        elif strat == "vsa_climax_test":
            if side_l == "long":
                # Fail-safe: if F&G data missing (fng_value sentinel -1) → ALLOW
                if btc_features.fng_value < 0:
                    self._log.debug("per_strategy_regime_filter.fng_missing.allow")
                    return True, None
                f3_bear = (
                    btc_features.fng_value < self.f3_fng_lt
                    and btc_features.return_30d < self.f3_ret30_lt
                )
                if f3_bear:
                    self._log.bind(
                        strategy=strat,
                        side=side_l,
                        fng=btc_features.fng_value,
                        ret30=btc_features.return_30d,
                        filter="F3",
                    ).debug("per_strategy_regime_filter.reject")
                    return False, "F3_vsa_bear"

        # ----------------------------------------------------------------
        # F4: engulfing_continuation — BOTH sides — extreme vol skip
        # Condition: realized_vol_7d_annualized > 100%
        # Backtest contribution: null alone but neutral in combo
        # ----------------------------------------------------------------
        elif strat == "engulfing_continuation":
            f4_highvol = btc_features.realized_vol_7d_annualized > self.f4_vol7d_ann_gt
            if f4_highvol:
                self._log.bind(
                    strategy=strat,
                    side=side_l,
                    vol7d=btc_features.realized_vol_7d_annualized,
                    filter="F4",
                ).debug("per_strategy_regime_filter.reject")
                return False, "F4_engulfing_high_vol"

        return True, None



# =====================================================================
# SEC58.HIGH-3 — Regime cache staleness tiers
# =====================================================================

class RegimeCacheStatus(enum.Enum):
    """Staleness tier of the regime features parquet cache.

    Tiers:
      FRESH       — age < warn_hours          → ALLOW, no alarm
      WARN        — warn_hours <= age < reject_hours → ALLOW + WARN log + Telegram
      REJECT      — reject_hours <= age < hard_reject_hours → REJECT all signals
      HARD_REJECT — age >= hard_reject_hours  → REJECT all signals + critical alarm
      MISSING     — parquet file not found / empty → behaviour per strict_mode

    Grace buffer (grace_minutes, default 30): thresholds expanded by this amount
    so a cron that runs 5-30 min late does NOT trigger the next tier.
    This keeps the boundary sharp for real outages (hours) not scheduling jitter.
    """

    FRESH = "fresh"
    WARN = "warn"
    REJECT = "reject"
    HARD_REJECT = "hard_reject"
    MISSING = "missing"


@dataclass
class CacheFreshnessConfig:
    """Config-driven staleness thresholds (from YAML cache_freshness block).

    YAML path: regime_filter_per_strategy.cache_freshness

    All hour values are MINIMUM age before a tier activates.  The grace_minutes
    buffer is added to each threshold so a cron that is slightly late does not
    immediately jump to the next tier.

    Example YAML:
      regime_filter_per_strategy:
        enabled: true
        cache_freshness:
          warn_hours: 24            # default
          reject_hours: 48          # default
          hard_reject_hours: 168    # 7 days default
          grace_minutes: 30         # default — cron jitter buffer
          strict_mode: true         # default — MISSING → MISSING (not ALLOW)

    strict_mode=False (env PA_REGIME_CACHE_STRICT=0) → old behaviour (ALLOW on missing).
    """

    warn_hours: float = 24.0
    reject_hours: float = 48.0
    hard_reject_hours: float = 168.0  # 7 days
    grace_minutes: float = 30.0       # added to each threshold to absorb cron jitter
    strict_mode: bool = True          # MISSING → REJECT when True; ALLOW when False

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any] | None) -> CacheFreshnessConfig:
        """Load from YAML block. Falls back to safe defaults."""
        cfg = cfg or {}
        strict = bool(
            os.environ.get("PA_REGIME_CACHE_STRICT", "1") not in ("0", "false", "False")
            and cfg.get("strict_mode", True)
        )
        return cls(
            warn_hours=float(cfg.get("warn_hours", 24.0)),
            reject_hours=float(cfg.get("reject_hours", 48.0)),
            hard_reject_hours=float(cfg.get("hard_reject_hours", 168.0)),
            grace_minutes=float(cfg.get("grace_minutes", 30.0)),
            strict_mode=strict,
        )

    def classify(self, age_hours: float) -> RegimeCacheStatus:
        """Classify a cache age (in hours) into a freshness tier.

        Grace buffer is applied: tier activates at (threshold + grace_minutes/60).
        This means a cron that runs up to grace_minutes late stays in the
        previous (less severe) tier.
        """
        grace_h = self.grace_minutes / 60.0
        if age_hours < self.warn_hours + grace_h:
            return RegimeCacheStatus.FRESH
        if age_hours < self.reject_hours + grace_h:
            return RegimeCacheStatus.WARN
        if age_hours < self.hard_reject_hours + grace_h:
            return RegimeCacheStatus.REJECT
        return RegimeCacheStatus.HARD_REJECT

__all__ = ["RegimeFilter", "BTCFeatures", "PerStrategyRegimeFilter", "RegimeCacheStatus", "CacheFreshnessConfig"]
