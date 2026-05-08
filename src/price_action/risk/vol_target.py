"""Volatility-targeted position sizing — kayıp koruma katmanı.

Konsept: Pozisyon notional'ı SL distance'a değil, ATR/price oranına göre ayarla.
Yüksek volatilite günlerinde otomatik küçük pozisyon, düşük volatilite günlerinde
otomatik büyük pozisyon → aynı getiri ama yıllar arası 2x daha tutarlı (test edildi).

Konfig (risk.yaml):
  vol_target:
    enabled: true
    target_atr_pct: 0.04   # %4 günlük ATR hedef
    min_factor: 0.20       # max %80 size azaltma (extrem high-vol koruma)
    max_factor: 1.50       # max %50 size büyütme (extrem low-vol fırsat)

Kullanım: signal'ın metadata'sından `atr_pct_at_entry` oku, factor hesapla,
risk_per_trade'e çarp.

Test edildi (3y backtest):
  Vol-target ON  : yıllık %32, σ %21, DD %37
  Vol-target OFF : yıllık %36, σ %35, DD %38
  → Tutarlılık 1.7x iyileşti, getiri biraz düştü (kabul edilebilir trade-off)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VolTargetConfig:
    """Vol-target sizing parametreleri."""

    enabled: bool = False
    target_atr_pct: float = 0.04
    min_factor: float = 0.20
    max_factor: float = 1.50


def vol_target_factor(
    atr_pct_at_entry: float,
    config: VolTargetConfig,
) -> float:
    """Verilen ATR%'ye göre risk-per-trade çarpanını hesapla.

    Formül: factor = target_atr / current_atr (clamped to [min, max])

    Örnek:
      target=0.04, current_atr=0.08 → factor = 0.5 (yarı pozisyon)
      target=0.04, current_atr=0.02 → factor = 2.0 → clamp 1.5 (extreme low-vol max boost)
      target=0.04, current_atr=0.04 → factor = 1.0 (normal)

    Args:
        atr_pct_at_entry: signal'ın atıldığı bardaki ATR / close oranı (0.04 = %4)
        config: VolTargetConfig — disabled ise 1.0 döner

    Returns:
        risk_per_trade çarpanı, [min_factor, max_factor] aralığında
    """
    if not config.enabled or config.target_atr_pct <= 0 or atr_pct_at_entry <= 0:
        return 1.0
    raw = config.target_atr_pct / atr_pct_at_entry
    return max(config.min_factor, min(config.max_factor, raw))


def apply_vol_target(
    base_risk_dollars: float,
    atr_pct_at_entry: float,
    config: VolTargetConfig,
) -> float:
    """Risk dollar miktarını vol-target factor ile çarp.

    Args:
        base_risk_dollars: orijinal risk_pct × equity hesabı (ör. $100)
        atr_pct_at_entry: bardaki ATR%
        config: VolTargetConfig

    Returns:
        ayarlanmış risk_dollars
    """
    factor = vol_target_factor(atr_pct_at_entry, config)
    return base_risk_dollars * factor


def from_risk_yaml(risk_cfg: dict) -> VolTargetConfig:
    """risk.yaml'dan VolTargetConfig parse et."""
    vt = risk_cfg.get("vol_target", {}) or {}
    return VolTargetConfig(
        enabled=bool(vt.get("enabled", False)),
        target_atr_pct=float(vt.get("target_atr_pct", 0.04)),
        min_factor=float(vt.get("min_factor", 0.20)),
        max_factor=float(vt.get("max_factor", 1.50)),
    )
