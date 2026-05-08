"""Prometheus metric tanımları — TÜM uygulamada tek noktadan.

Diğer modüller (örn. `agents/base.py`) buradan import eder. Bu modül asla
`prometheus_client.start_http_server` çağırmaz; expose'u FastAPI
`/metrics` endpoint'i yapar.

Idempotent: Modül birden çok kez yeniden yüklenirse (testlerde reload),
mevcut metric'ler `REGISTRY`'den toplanır, duplicate hatası atılmaz.
"""
from __future__ import annotations

from typing import Any

from prometheus_client import (
    REGISTRY as _DEFAULT_REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

# Default global registry kullanılır, sadece testlerde özel registry verilebilir.
REGISTRY: CollectorRegistry | None = None  # None → prometheus_client default


def _get_or_create(metric_cls: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    """Idempotent metric kaydı: mevcutsa al, yoksa oluştur."""
    existing = getattr(_DEFAULT_REGISTRY, "_names_to_collectors", {}).get(name)
    if existing is not None:
        return existing
    try:
        return metric_cls(name, *args, **kwargs)
    except ValueError:
        # Yarış durumu: araya başka modül girdiyse mevcut olanı dön.
        return _DEFAULT_REGISTRY._names_to_collectors[name]  # noqa: SLF001


# =====================================================================
# Counter'lar
# =====================================================================

orders_total = _get_or_create(
    Counter,
    "pa_orders_total",
    "Toplam emir sayısı (durum bazında).",
    labelnames=("status",),  # filled | partial | rejected | canceled
)

signals_emitted_total = _get_or_create(
    Counter,
    "pa_signals_emitted_total",
    "Üretilen sinyal sayısı (strateji/sembol/yön).",
    labelnames=("strategy", "symbol", "direction"),
)

# Labels: (agent, model, type) — type ∈ {"input","output"} input/output ayrımı için.
llm_tokens_total = _get_or_create(
    Counter,
    "pa_llm_tokens_total",
    "LLM agent'ların kullandığı toplam token (input+output ayrı).",
    labelnames=("agent", "model", "type"),
)

llm_calls_total = _get_or_create(
    Counter,
    "pa_llm_calls_total",
    "LLM çağrı sayısı.",
    labelnames=("agent", "model", "status"),
)

# =====================================================================
# Histogram'lar
# =====================================================================

slippage_bps = _get_or_create(
    Histogram,
    "pa_slippage_bps",
    "Fill slippage (bps) — execution telemetrisi.",
    buckets=(0.5, 1, 2, 5, 10, 20, 50, 100, 250, 500),
)

ingest_lag_seconds = _get_or_create(
    Histogram,
    "pa_ingest_lag_seconds",
    "OHLCV ingest gecikmesi (saniye).",
    labelnames=("venue", "timeframe"),
    buckets=(1, 5, 10, 30, 60, 300, 900, 3600),
)

# =====================================================================
# Gauge'lar
# =====================================================================

breaker_active = _get_or_create(
    Gauge,
    "pa_breaker_active",
    "Aktif drawdown breaker (1=aktif, 0=pasif).",
    labelnames=("level",),  # daily | weekly | monthly | consecutive
)

open_positions_count = _get_or_create(
    Gauge,
    "pa_open_positions_count",
    "Anlık açık pozisyon sayısı.",
)

equity_usdt = _get_or_create(
    Gauge,
    "pa_equity_usdt",
    "Güncel hesap özsermayesi (USDT).",
)


def reset_for_tests() -> None:
    """Test için sayaçları sıfırla (default registry'de kalan değerleri silmez,
    sadece label kombinasyonlarını yeniden alır)."""
    # Counter / Histogram'ı tam reset etmek prometheus_client'ta resmi değil;
    # testlerde yeni labels açma şeklinde kullanırız.
    pass
