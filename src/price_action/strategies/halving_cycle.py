"""BTC Halving Döngüsü — Makro Faz Modülü.

Bu modül engulfing veya herhangi bir stratejiyi *değiştirmez*; sadece
sinyallerin risk büyüklüğünü halving döngüsü fazına göre ölçeklendirir.

Halving tarihleri (sabit, geçmişe dair public knowledge — lookahead YOK):
  2012-11-28, 2016-07-09, 2020-05-11, 2024-04-19
  2028-04-15 (tahmini — blok zamanı henüz kesinleşmedi, ±2 ay tolerans)

Faz tanımları (post-halving geçen süreye göre):
  Phase A: 0-12 ay   → Aggressive  (size_factor=1.0)
  Phase B: 12-30 ay  → Defensive   (size_factor=0.5)
  Phase C: 30-45 ay  → Moderate    (size_factor=0.75)
  Phase D: 45-48 ay  → Pre-halving accumulation (size_factor=1.0)

Kullanım:
  from price_action.strategies.halving_cycle import (
      compute_halving_phase,
      phase_to_size_factor,
      apply_halving_phase_sizing,
      HalvingCycleEngulfingStrategy,
  )

UYARI — İstatistiksel sınır:
  4 halving × 4 faz = 16 global sample.
  Bu hipotez istatistiksel kanıt üretemez; narrative-fit riski yüksek.
  Backtest sonuçları DEFER veya dikkatli PROMOTE için kullanılmalıdır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Literal

import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

#: Onaylanmış ve tahmini halving tarihleri.
#: Sadece geçmiş tarihler kesindir; 2028 tahmini ±2 ay toleranslıdır.
HALVING_DATES: list[date] = [
    date(2012, 11, 28),   # Block 210,000
    date(2016, 7,  9),    # Block 420,000
    date(2020, 5,  11),   # Block 630,000
    date(2024, 4,  19),   # Block 840,000
    date(2028, 4,  15),   # Block 1,050,000 — tahmini
]

#: Faz geçiş noktaları (aylar, post-halving).
_PHASE_BOUNDS_MONTHS: list[tuple[int, int, str]] = [
    (0,  12, "A"),   # 0-12 ay: post-halving bull window
    (12, 30, "B"),   # 12-30 ay: mid-cycle range/bear
    (30, 45, "C"),   # 30-45 ay: erken pre-halving accumulation
    (45, 48, "D"),   # 45-48 ay: yaklaşan halving, son toplanma
]

#: Size factor her faz için.
_PHASE_SIZE_FACTORS: dict[str, float] = {
    "A": 1.00,   # aggressive
    "B": 0.50,   # defensive
    "C": 0.75,   # moderate
    "D": 1.00,   # aggressive yeniden
}

HalvingPhase = Literal["A", "B", "C", "D"]

# ---------------------------------------------------------------------------
# Yardımcı: ay farkı hesabı (float, 30.4375 gün/ay)
# ---------------------------------------------------------------------------

_DAYS_PER_MONTH: float = 365.25 / 12.0  # 30.4375


def _months_since(d_from: date, d_to: date) -> float:
    """İki tarih arasındaki gün farkını aya çevirir."""
    delta_days = (d_to - d_from).days
    return delta_days / _DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# Ana API
# ---------------------------------------------------------------------------

def compute_halving_phase(ts: datetime | pd.Timestamp | date) -> HalvingPhase | None:
    """Verilen zaman damgası için halving döngüsü fazını döndürür.

    Lookahead-free: yalnızca `ts`'den önceki halving tarihlerine bakılır.
    Gelecekteki (tahmini) 2028 halvingine `ts` geçildiğinde o da dahil edilir.

    Args:
        ts: Herhangi bir datetime / Timestamp / date.
            Timezone-aware veya naive kabul edilir.

    Returns:
        HalvingPhase ("A", "B", "C", "D") veya None (hiçbir halving
        henüz geçmediyse — 2012 öncesi).

    Example:
        >>> from datetime import datetime
        >>> compute_halving_phase(datetime(2024, 6, 1))
        'A'
        >>> compute_halving_phase(datetime(2022, 1, 1))
        'B'
    """
    # Normalize to date
    if isinstance(ts, (datetime, pd.Timestamp)):
        ts_date = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
    elif isinstance(ts, date):
        ts_date = ts
    else:
        raise TypeError(f"ts must be datetime, Timestamp, or date; got {type(ts)}")

    # En son ts'den önce veya ts'ye eşit halving'i bul
    past_halvings = [h for h in HALVING_DATES if h <= ts_date]
    if not past_halvings:
        return None  # 2012-11-28 öncesi — halving henüz olmamış

    last_halving = max(past_halvings)
    months_elapsed = _months_since(last_halving, ts_date)

    for (lo, hi, phase) in _PHASE_BOUNDS_MONTHS:
        if lo <= months_elapsed < hi:
            return phase  # type: ignore[return-value]

    # 48 ay sonrasında (döngünün ötesi) — bir sonraki halving yaklaşıyor
    # Pratik olarak bu Phase D'nin uzantısı veya bir sonraki Phase A başlangıcı
    # Bir sonraki halving'in 48 ay öncesinden itibaren Phase D gibi davranır
    return "D"


def phase_to_size_factor(phase: HalvingPhase | None) -> float:
    """Faz için pozisyon boyutu faktörünü döndürür.

    Args:
        phase: "A", "B", "C", "D" veya None.

    Returns:
        float — 0.5 (defensive) ile 1.0 (aggressive) arasında.
        None için 1.0 döner (nötr — halving öncesi dönem).
    """
    if phase is None:
        return 1.0
    return _PHASE_SIZE_FACTORS.get(phase, 1.0)


def apply_halving_phase_sizing(
    signals: list[Signal],
    base_risk: float = 0.01,
) -> list[Signal]:
    """Signal listesindeki suggested_size_atr'ı halving fazına göre ölçeklendirir.

    Bu fonksiyon engulfing_continuation.py'yi değiştirmez; sinyal listesine
    post-hoc uygulanan bir filtredir.

    Args:
        signals: Herhangi bir stratejiden gelen Signal listesi.
        base_risk: Temel risk oranı (0.01 = %1). Metadata'ya kaydedilir.

    Returns:
        Yeni Signal listesi — `suggested_size_atr` ve `metadata` güncellenmiş.
        Orijinal sinyaller değiştirilmez (immutable Pydantic model kopyalanır).
    """
    result: list[Signal] = []
    for sig in signals:
        phase = compute_halving_phase(sig.ts)
        factor = phase_to_size_factor(phase)
        scaled_size = float(sig.suggested_size_atr) * factor
        effective_risk = base_risk * factor

        new_meta = dict(sig.metadata or {})
        new_meta.update({
            "halving_phase": phase,
            "halving_size_factor": factor,
            "halving_effective_risk": effective_risk,
        })

        new_sig = sig.model_copy(update={
            "suggested_size_atr": scaled_size,
            "metadata": new_meta,
        })
        result.append(new_sig)

    phase_counts = {
        str(p) if p is not None else "none": sum(
            1 for s in result if s.metadata.get("halving_phase") == p
        )
        for p in ("A", "B", "C", "D", None)
    }
    logger.info(
        "halving_phase_sizing.applied",
        n_signals=len(result),
        phases=phase_counts,
    )
    return result


# ---------------------------------------------------------------------------
# DataFrame yardımcısı — toplu faz hesabı
# ---------------------------------------------------------------------------

def add_halving_phase_column(df: pd.DataFrame, ts_col: str = "ts") -> pd.DataFrame:
    """DataFrame'e 'halving_phase' ve 'halving_size_factor' sütunları ekler.

    Lookahead-free: her satır için yalnızca o satırın ts bilgisi kullanılır.
    Halving tarihleri sabittir (geçmiş = public knowledge, gelecek = tahmini).

    Args:
        df: ts_col içeren DataFrame.
        ts_col: Zaman damgası sütununun adı.

    Returns:
        Yeni sütunlar eklenmiş kopya DataFrame.
    """
    df = df.copy()
    phases = df[ts_col].apply(compute_halving_phase)
    df["halving_phase"] = phases
    df["halving_size_factor"] = phases.apply(phase_to_size_factor)
    return df


# ---------------------------------------------------------------------------
# Wrapper: HalvingCycleEngulfingStrategy
# ---------------------------------------------------------------------------

class HalvingCycleEngulfingStrategy:
    """EngulfingContinuationStrategy üzerine halving-phase sizing filtresi.

    Bu sınıf EngulfingContinuationStrategy'yi *miras almaz*, kapsüller.
    `generate_signals` çağrısının sonucuna `apply_halving_phase_sizing`
    uygulayarak döndürür.

    Mevcut engulfing_continuation.py dosyasına dokunulmaz.

    Kullanım:
        from price_action.strategies.engulfing_continuation import (
            EngulfingContinuationStrategy, _default_manifest
        )
        from price_action.strategies.halving_cycle import HalvingCycleEngulfingStrategy

        eng_strategy = EngulfingContinuationStrategy(_default_manifest())
        halving_strategy = HalvingCycleEngulfingStrategy(eng_strategy, base_risk=0.01)

        df_feats = halving_strategy.prepare_features(df)
        signals = halving_strategy.generate_signals(df_feats)
    """

    def __init__(self, engulfing_strategy, base_risk: float = 0.01) -> None:
        """
        Args:
            engulfing_strategy: EngulfingContinuationStrategy instance.
            base_risk: Temel risk oranı (Phase A için tam risk).
        """
        self._inner = engulfing_strategy
        self.base_risk = base_risk
        self.name = f"{engulfing_strategy.name}+halving_cycle"

    @property
    def manifest(self):
        return self._inner.manifest

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Inner strategy feature'larını + halving sütunlarını ekler."""
        df = self._inner.prepare_features(df)
        df = add_halving_phase_column(df)
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Inner strategy sinyalleri üretir, halving sizing uygular."""
        raw_signals = self._inner.generate_signals(df)
        sized_signals = apply_halving_phase_sizing(raw_signals, base_risk=self.base_risk)
        return sized_signals
