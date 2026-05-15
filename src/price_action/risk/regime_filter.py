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
"""
from __future__ import annotations

from datetime import date as _date, datetime
from typing import Any

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


__all__ = ["RegimeFilter"]
