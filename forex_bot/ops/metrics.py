"""Prometheus metrics for forex_bot live daemon.

Minimal pb_* metrics; expose /metrics endpoint via prometheus_client.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    _HAS_PROM = True
except ImportError:
    _HAS_PROM = False


if _HAS_PROM:
    pb_signals_emitted_total = Counter("pb_signals_emitted_total", "Forex signals emitted", ["pair", "strategy", "side"])
    pb_orders_total = Counter("pb_orders_total", "Forex orders attempted", ["pair", "side", "outcome"])
    pb_fills_total = Counter("pb_fills_total", "Forex fills", ["pair", "side"])
    pb_rejects_total = Counter("pb_rejects_total", "Forex rejects", ["pair", "rejected_by", "reason"])
    pb_broker_latency_ms = Histogram("pb_broker_latency_ms", "Broker API latency",
                                      ["broker", "operation"], buckets=[50, 100, 200, 500, 1000, 2000, 5000])
    pb_slippage_pips = Histogram("pb_slippage_pips", "Slippage in pips", ["pair"],
                                  buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0])
    pb_equity_usd = Gauge("pb_equity_usd", "Account equity USD")
    pb_open_position_count = Gauge("pb_open_position_count", "Open position count")
    pb_daily_pnl_usd = Gauge("pb_daily_pnl_usd", "Daily realized PnL USD")
    pb_breaker_active = Gauge("pb_breaker_active", "DD breaker active flag (1=blocked)")
else:
    # Stubs if prometheus_client not installed
    class _Stub:
        def labels(self, *args, **kwargs): return self
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass

    pb_signals_emitted_total = _Stub()
    pb_orders_total = _Stub()
    pb_fills_total = _Stub()
    pb_rejects_total = _Stub()
    pb_broker_latency_ms = _Stub()
    pb_slippage_pips = _Stub()
    pb_equity_usd = _Stub()
    pb_open_position_count = _Stub()
    pb_daily_pnl_usd = _Stub()
    pb_breaker_active = _Stub()


def start_metrics_server(port: int = 9094) -> None:
    if _HAS_PROM:
        start_http_server(port)
