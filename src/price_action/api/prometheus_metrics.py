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

# =====================================================================
# Scalper-Spesifik Metrics (15m, 5m, 1m intraday)
# =====================================================================

scalp_fill_rate = _get_or_create(
    Gauge,
    "pa_scalp_fill_rate",
    "Intraday fill rate (maker/post-only) — TF-scaled.",
    labelnames=("timeframe", "symbol"),
)

scalp_slippage_bps = _get_or_create(
    Histogram,
    "pa_scalp_slippage_bps",
    "Scalper fill slippage (bps) — TF-specific buckets.",
    labelnames=("timeframe", "symbol", "side"),
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 50, 75, 100),
)

scalp_fee_burn_usdt_per_hour = _get_or_create(
    Gauge,
    "pa_scalp_fee_burn_usdt_per_hour",
    "Fee erosion (USDT/hour) — TF + symbol.",
    labelnames=("timeframe", "symbol"),
)

scalp_trade_count_per_hour = _get_or_create(
    Counter,
    "pa_scalp_trade_count_per_hour",
    "Trades executed per hour (scalper).",
    labelnames=("timeframe", "strategy"),
)

scalp_hold_time_minutes = _get_or_create(
    Histogram,
    "pa_scalp_hold_time_minutes",
    "Median hold time per trade (minutes).",
    labelnames=("timeframe", "strategy"),
    buckets=(1, 2, 5, 10, 15, 30, 60, 120, 240),
)

scalp_post_only_cancel_rate = _get_or_create(
    Gauge,
    "pa_scalp_post_only_cancel_rate",
    "Post-only order timeout + cancel rate (0-100%).",
    labelnames=("timeframe",),
)

scalp_drawdown_bps = _get_or_create(
    Gauge,
    "pa_scalp_drawdown_bps",
    "Current drawdown (basis points) — TF + level.",
    labelnames=("timeframe", "level"),  # level: daily, weekly, monthly
)

scalp_breaker_active = _get_or_create(
    Gauge,
    "pa_scalp_breaker_active",
    "Drawdown breaker status (1=halted, 0=trading).",
    labelnames=("timeframe", "level"),
)

# SEC54.6d — Per-strategy regime filter features staleness
regime_features_age_minutes = _get_or_create(
    Gauge,
    "pa_regime_features_age_minutes",
    "BTC regime features parquet yaşı (dakika) — staleness monitor. >60 = uyarı.",
)


# =====================================================================
# 15m Daemon Loop Telemetry (SEC54.4)
# =====================================================================

scan_latency_seconds = _get_or_create(
    Histogram,
    "pa_scan_latency_seconds",
    "Signal scan suresi (saniye) — bar-close sonrasi tarama.",
    labelnames=("tf",),
    buckets=(1, 2, 5, 10, 15, 20, 30, 60, 120, 300),
)

signal_to_order_latency_seconds = _get_or_create(
    Histogram,
    "pa_signal_to_order_latency_seconds",
    "Sinyal alimindaki order submit suresi (saniye).",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30),
)

missed_bars_total = _get_or_create(
    Counter,
    "pa_missed_bars_total",
    "Kaçırılan bar sayısı (processing aşıldı, sonraki bar başladı).",
    labelnames=("tf",),
)

# DQ-02 (SEC54.5): Stale signal reject sayacı — her TF için ayrı.
stale_signal_reject_total = _get_or_create(
    Counter,
    "pa_stale_signal_reject_total",
    "Reddedilen stale sinyal sayısı (max_age aşıldı).",
    labelnames=("tf",),
)

position_monitor_duration_seconds = _get_or_create(
    Histogram,
    "pa_position_monitor_duration_seconds",
    "Position monitor döngüsü suresi (saniye) — pyramid trigger detection dahil.",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)


def reset_for_tests() -> None:
    """Test için sayaçları sıfırla (default registry'de kalan değerleri silmez,
    sadece label kombinasyonlarını yeniden alır)."""
    # Counter / Histogram'ı tam reset etmek prometheus_client'ta resmi değil;
    # testlerde yeni labels açma şeklinde kullanırız.
    pass
