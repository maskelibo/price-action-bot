"""Tek-kaynaklı eşik sabitler.

FIX 2026-05-28 (audit-Y2): Strategy audit "parameter snooping" iddiası
yarı-doğru çıktı — sl_pct_min'in büyük çoğunluğu zaten yaml config'den
okunuyordu (futures_daemon.py:1135, lab.py:491, adapter.py). Ama **default
değer**ler birden fazla yerde tekrarlanıyordu (lab.py:336=0.025,
provenance.py:117=0.025, researcher_15m_*.py=0.025). Bu modül o default'ları
tek noktaya alır; yaml override yine en üst öncelik.

Kullanım:
    from price_action._thresholds import WIDESTOP_SL_PCT_DEFAULT
    sl_pct_threshold = WIDESTOP_SL_PCT_DEFAULT  # 0.025

Eşik değiştirmek istenirse: BU dosyayı değiştir + tüm bağımlı yerler
otomatik güncellensin. Ya da PA_<NAME> env var ile runtime override.
"""
from __future__ import annotations

import os

# --- Wide-stop deploy threshold ----------------------------------------------
# v2 15m deploy candidate: sl_pct ≥ 2.5% sinyalleri kabul, daha dar olanları
# WIDESTOP_REJECT. configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml ile
# eşleşir (execution.sl_pct_min: 0.025). Default override edilebilir:
#   PA_WIDESTOP_SL_PCT=0.030 python ...
def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


WIDESTOP_SL_PCT_DEFAULT: float = _env_float("PA_WIDESTOP_SL_PCT", 0.025)

# --- P1c 5m sl threshold -----------------------------------------------------
# Memory'deki karar: P1c sl=%3 değişmez (sl=%2 ROI yarıdan az, Drop1 OOS bozar).
# Yaml override yine en yüksek öncelik (configs/risk_phoenix_scalp_5m_p1c.yaml).
P1C_SL_PCT_DEFAULT: float = _env_float("PA_P1C_SL_PCT", 0.030)

# --- Safe-mode fallback (config load fail) -----------------------------------
# 15m daemon config load fail'de sl_pct_min=1.0 → tüm sinyaller reject.
# "Hiçbir trade olmasın"dan emin olmak için %100. Override etme.
SAFE_MODE_SL_PCT: float = 1.0


__all__ = [
    "WIDESTOP_SL_PCT_DEFAULT",
    "P1C_SL_PCT_DEFAULT",
    "SAFE_MODE_SL_PCT",
]
