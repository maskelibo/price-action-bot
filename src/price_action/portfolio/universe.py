"""Symbol universe filtreleri.

Data Engineering tarafından sağlanan `Instrument` listesini risk + data quality
filtrelerinden geçirir.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from price_action.contracts import Instrument
from price_action.logging_config import logger

_LEVERAGED_TOKEN_TAGS = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")
_STABLECOIN_BASES = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP", "USDE"}


def _is_leveraged(symbol: str) -> bool:
    upper = symbol.upper()
    base = upper.split("/")[0] if "/" in upper else upper
    return any(tag in base for tag in _LEVERAGED_TOKEN_TAGS)


def _is_stablecoin(symbol: str) -> bool:
    base = symbol.upper().split("/")[0] if "/" in symbol else symbol.upper()
    return base in _STABLECOIN_BASES


def apply_filters(
    instruments: Iterable[Instrument],
    *,
    risk_config: dict[str, Any] | None = None,
    data_quality: dict[str, dict[str, Any]] | None = None,
    extra_excludes: Iterable[str] = (),
) -> list[Instrument]:
    """Filtreleri uygula. Reddedilenleri loglar.

    `data_quality` opsiyonel: {symbol: {"zero_volume_days_pct": float, "ok": bool, ...}}
    """
    risk_config = risk_config or {}
    data_quality = data_quality or {}
    excludes = {s.upper() for s in extra_excludes}

    out: list[Instrument] = []
    rejected: list[tuple[str, str]] = []
    for inst in instruments:
        if not inst.is_active:
            rejected.append((inst.symbol, "inactive"))
            continue
        if inst.symbol.upper() in excludes:
            rejected.append((inst.symbol, "excluded"))
            continue
        if _is_leveraged(inst.symbol):
            rejected.append((inst.symbol, "leveraged_token"))
            continue
        if _is_stablecoin(inst.symbol):
            rejected.append((inst.symbol, "stablecoin"))
            continue
        # Quote filtresi (USDT default)
        if inst.quote and inst.quote.upper() not in {"USDT"}:
            rejected.append((inst.symbol, f"quote!=USDT ({inst.quote})"))
            continue
        # Data quality
        dq = data_quality.get(inst.symbol)
        if dq is not None:
            if dq.get("ok") is False:
                rejected.append((inst.symbol, f"data_quality:{dq.get('reason', '?')}"))
                continue
            zvd = dq.get("zero_volume_days_pct")
            if zvd is not None and zvd > 0.05:
                rejected.append((inst.symbol, f"zero_volume_days_pct={zvd:.3f}"))
                continue
        out.append(inst)
    logger.bind(kept=len(out), rejected=len(rejected)).info("portfolio.universe.filter")
    return out
