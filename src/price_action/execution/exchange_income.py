"""fetch_realized_income — kapanan trade'in GERÇEK realized PnL'ini borsa income'ından.

CT-EXE-02 remediation (2026-06-15): journal realized_pnl'i lokal
``(exit-entry)*qty`` ile yazılıyordu → fee/funding atlanıyor + JOURNAL_HEAL yolu
hiç PnL yazmıyordu (kayıplar gizleniyordu, AF-EXE-20260531-001). Tek kaynak-doğru
PnL = borsa ``fapiPrivateGetIncome`` toplamı (REALIZED_PNL + COMMISSION + FUNDING_FEE)
— ölçüm kuralıyla (memory pnl-reporting-format) birebir aynı.

Best-effort sözleşmesi: hata / boş pencere → ``None`` döner; caller ASLA bu yüzden
kapanışı bloklamaz, ``None`` ise eski davranışına (lokal hesap / PnL atlama) düşer.
Bu modül exchange-agnostic değil (ccxt binance fapi çağrısı yapar) — bu yüzden
``trade_journal`` içine değil ayrı modüle konuldu (journal saf kalır).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Net realized = bu üç income tipinin toplamı (işaretli: COMMISSION negatif,
# REALIZED_PNL/FUNDING_FEE ±). Ölçüm kuralıyla aynı küme.
_INCOME_TYPES: tuple[str, ...] = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")


def to_symbol_id(symbol: str) -> str:
    """ccxt sembol ("AVAX/USDT:USDT" | "AVAX/USDT") → Binance fapi id ("AVAXUSDT")."""
    return (
        str(symbol)
        .replace("/USDT:USDT", "USDT")
        .replace("/USDT", "USDT")
        .replace("/", "")
    )


def fetch_realized_income(
    exchange: Any,
    symbol: str,
    start_ms: int | None,
    end_ms: int | None = None,
) -> float | None:
    """Sembol için [start_ms, end_ms] penceresinde NET realized income (USDT).

    REALIZED_PNL + COMMISSION + FUNDING_FEE toplamı. Pencere kapalı bir trade'in
    ts_open→ts_close aralığı olmalı (çakışan trade penceresi → yanlış atıf riski).

    Returns:
        float  → o pencerede en az bir ilgili income satırı bulundu (toplam, ± olabilir)
        None   → API hatası VEYA hiç ilgili income satırı yok (caller eski davranışa düşer)
    """
    try:
        params: dict[str, Any] = {"symbol": to_symbol_id(symbol), "limit": 1000}
        if start_ms:
            params["startTime"] = int(start_ms)
        if end_ms:
            params["endTime"] = int(end_ms)
        rows = exchange.fapiPrivateGetIncome(params) or []
        total = 0.0
        found = False
        for r in rows:
            if str(r.get("incomeType", "")).upper() in _INCOME_TYPES:
                total += float(r.get("income", 0) or 0.0)
                found = True
        if not found:
            return None
        return total
    except Exception as exc:  # pragma: no cover — borsa hatası, best-effort
        logger.warning(
            "exchange_income.fetch_fail",
            extra={"symbol": str(symbol), "err": str(exc)[:200]},
        )
        return None
