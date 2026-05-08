"""Strateji ABC + manifest doğrulaması.

Strateji manifestoları YAML dosyaları olarak `configs/strategies/` altında tutulur.
Researcher aday üretir, insan + Lab onayıyla aktif edilir.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from price_action.contracts import Signal, stable_hash
from price_action.logging_config import logger


# =====================================================================
# Manifest schema
# =====================================================================

class _PatternCfg(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    enabled: bool = True
    weight: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)


class _SwingCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    fractal_n: int = 2


class _SRCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    lookback_bars: int = 200
    cluster_atr_multiplier: float = 0.5
    min_touches: int = 2
    max_age_bars: int = 180


class _StructureCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    swing: _SwingCfg = Field(default_factory=_SwingCfg)
    support_resistance: _SRCfg = Field(default_factory=_SRCfg)
    require_proximity_to_sr_atr: float = 1.0


class _FiltersCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    atr_min_pct: float = 0.0
    volume_zscore_min: float = 0.0
    min_distance_to_sr_atr: float = 0.0


class _ConfluenceCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    method: str = "weighted_sum"
    min_score: float = 1.0
    bonus_if_at_sr: float = 0.0


class _SignalsCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    patterns: list[_PatternCfg] = Field(default_factory=list)
    structure: _StructureCfg = Field(default_factory=_StructureCfg)
    filters: _FiltersCfg = Field(default_factory=_FiltersCfg)
    confluence: _ConfluenceCfg = Field(default_factory=_ConfluenceCfg)


class _TrendFilterCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str = "ema"
    period: int = 50
    required: bool = True


class _TimeframesCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    decision: str = "1d"
    trend_filter: str | None = "1w"
    refinement: str | None = None


class _ExecutionCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    decision_after_close: bool = True
    entry_type: str = "post_only_limit"
    limit_offset_atr: float = 0.0
    invalidation_after_bars: int = 1


class _BacktestCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    warmup_bars: int = 250
    fees: dict[str, float] = Field(
        default_factory=lambda: {"taker": 0.00075, "maker": -0.00010}
    )
    slippage_bps: float = 5.0
    initial_capital_usdt: float = 10_000.0


class StrategyManifest(BaseModel):
    """YAML manifest -> doğrulanmış model."""

    model_config = ConfigDict(extra="allow", frozen=False)

    name: str
    version: str = "0.0.1"
    description: str = ""
    universe: dict[str, Any] = Field(default_factory=dict)
    timeframes: _TimeframesCfg = Field(default_factory=_TimeframesCfg)
    trend_filter: _TrendFilterCfg = Field(default_factory=_TrendFilterCfg)
    signals: _SignalsCfg = Field(default_factory=_SignalsCfg)
    risk: dict[str, Any] = Field(default_factory=dict)
    execution: _ExecutionCfg = Field(default_factory=_ExecutionCfg)
    backtest: _BacktestCfg = Field(default_factory=_BacktestCfg)
    walk_forward: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_lower(cls, v: str) -> str:
        return v.strip().lower().replace(" ", "_")

    def hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


def _normalize_yaml_double_colon(text: str) -> str:
    """`key: subkey: value` gibi tek-satırlık iç-içe notasyonu çift kolon
    yerine düzgün indent yapısına çevirir.

    Yalnızca güvenli, şüpheli durumda no-op.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        # Yorum satırı/boş satır
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        # `key: subkey: value` (3 token) ?
        # Naive: iki ':' var ve ikincisi quoted değil
        if stripped.count(":") >= 2 and ":" in stripped:
            # ilk iki kolonun pozisyonu
            i1 = stripped.find(":")
            i2 = stripped.find(":", i1 + 1)
            head = stripped[:i1].strip()
            mid = stripped[i1 + 1 : i2].strip()
            tail = stripped[i2 + 1 :].strip()
            if head and mid and tail and " " not in head and " " not in mid:
                out.append(f"{indent}{head}:")
                out.append(f"{indent}  {mid}: {tail}")
                continue
        out.append(line)
    return "\n".join(out)


# =====================================================================
# Strategy ABC
# =====================================================================

class Strategy(ABC):
    """Tüm stratejilerin temel sınıfı."""

    def __init__(self, manifest: StrategyManifest) -> None:
        self.manifest = manifest
        self.name = manifest.name
        self.version = manifest.version
        self._log = logger.bind(strategy=self.name, version=self.version)

    # ----- factory -----
    @classmethod
    def load_from_yaml(cls, path: str | Path) -> Strategy:
        """YAML manifest oku, manifest'i validate et, alt sınıfa devret."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Strategy manifest yok: {p}")
        text = p.read_text(encoding="utf-8")
        # YAML'da ara sıra `start: relative_years_ago: 3` gibi non-standart notasyon var.
        # Tek-satır iki kolonlu deyimleri stringify edip tolere ediyoruz.
        text = _normalize_yaml_double_colon(text)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            logger.bind(path=str(p), err=str(exc)).error("manifest.yaml_parse_fail")
            raise
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest dict bekleniyor, alındı: {type(raw)!r}")

        # `start` artık dict (relative_years_ago) veya None olabilir;
        # StrategyManifest extra="allow" olduğundan kabul edilir, ama backtest
        # alanını da tip uyumsuzluğuna sokmamak için None'a sıkıştırıyoruz.
        if "backtest" in raw and isinstance(raw["backtest"].get("start"), dict):
            raw["backtest"]["_start_rel"] = raw["backtest"]["start"]
            raw["backtest"]["start"] = None

        manifest = StrategyManifest.model_validate(raw)

        # cls=Strategy ise concrete alt sınıf gerekir.
        if cls is Strategy:
            from price_action.strategies.classic_pa import ClassicPriceActionStrategy

            return ClassicPriceActionStrategy(manifest)
        return cls(manifest)  # type: ignore[call-arg]

    # ----- API -----
    @abstractmethod
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLCV df üzerinde özellikler ekle (EMA, ATR, S/R, swing'ler vs.)."""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Hazırlanmış df'ten `Signal` listesi üret. Lookahead yasak."""

    # ----- helpers -----
    def emit_signal(
        self,
        *,
        ts: datetime,
        venue: str,
        symbol: str,
        timeframe: str,
        direction: str,
        pattern_id: str,
        confluence_score: float,
        sl_price: float,
        tp_price: float,
        suggested_size_atr: float,
        metadata: dict[str, Any] | None = None,
    ) -> Signal:
        """Manifest hash'iyle Signal üret."""
        sig = Signal(
            ts=ts,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,  # type: ignore[arg-type]
            direction=direction,  # type: ignore[arg-type]
            pattern_id=pattern_id,
            confluence_score=confluence_score,
            sl_price=sl_price,
            tp_price=tp_price,
            suggested_size_atr=suggested_size_atr,
            metadata=metadata or {},
            manifest_hash=self.manifest.hash(),
        )
        return sig
