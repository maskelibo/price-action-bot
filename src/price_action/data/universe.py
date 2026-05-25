"""Sembol evreni inşası — configs/symbols.yaml + ccxt market metadata.

`build_universe(mode)` -> list[Instrument]
- all_liquid: borsa marketlerinden filtreler (likidite, leveraged-token hariç, vs).
- top_volume: 24h hacme göre top N.
- manual: yaml'daki manual_list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml

from price_action.contracts import Instrument
from price_action.logging_config import logger
from price_action.settings import get_settings

UniverseMode = Literal["all_liquid", "top_volume", "manual"]

_LEVERAGED_RE = re.compile(r"(\d+(L|S)|UP|DOWN|BULL|BEAR)$", re.IGNORECASE)
_DEFAULT_STABLECOINS: set[str] = {
    "USDT", "USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDD",
    "PYUSD", "USTC", "GUSD", "EURT", "EURS", "EUROC",
}


@dataclass
class UniverseFilters:
    min_avg_volume_usdt_24h: float = 1_000_000.0
    min_listing_age_days: int = 365
    max_zero_volume_days_pct: float = 5.0
    exclude_leveraged_tokens: bool = True
    exclude_stablecoins: bool = True
    exclude_delisted: bool = True


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _coerce_number(value: Any, default: float) -> float:
    """YAML'da '1_000_000' gibi underscore'lu sayıları toleranslı parse et."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("_", "").strip()
    try:
        return float(s)
    except ValueError:
        return default


def _is_leveraged(base: str) -> bool:
    return bool(_LEVERAGED_RE.search(base or ""))


def _is_stablecoin(base: str, extra: set[str] | None = None) -> bool:
    pool = _DEFAULT_STABLECOINS | (extra or set())
    return (base or "").upper() in pool


def _market_type_from_ccxt(market: dict[str, Any]) -> str:
    """ccxt market dict → contracts.market_type."""
    if market.get("spot"):
        return "spot"
    if market.get("linear") and (market.get("swap") or market.get("contract")):
        return "linear_perp"
    if market.get("inverse") and (market.get("swap") or market.get("contract")):
        return "inverse_perp"
    # fallback
    return "spot"


def _passes_filters(
    market: dict[str, Any],
    ticker: dict[str, Any] | None,
    filters: UniverseFilters,
    quote: str,
    venues_market_types: list[str],
) -> bool:
    if not market.get("active", True) and filters.exclude_delisted:
        return False
    base = (market.get("base") or "").upper()
    q = (market.get("quote") or "").upper()
    if quote and q != quote.upper():
        return False
    if filters.exclude_leveraged_tokens and _is_leveraged(base):
        return False
    if filters.exclude_stablecoins and _is_stablecoin(base):
        return False
    mtype = _market_type_from_ccxt(market)
    if venues_market_types and mtype not in venues_market_types:
        return False
    if ticker is not None:
        vol_quote = ticker.get("quoteVolume")
        if vol_quote is None:
            base_vol = ticker.get("baseVolume")
            last = ticker.get("last")
            if base_vol is not None and last is not None:
                vol_quote = float(base_vol) * float(last)
        if vol_quote is None or float(vol_quote) < filters.min_avg_volume_usdt_24h:
            return False
    return True


def _instrument_from_market(
    venue: str,
    market: dict[str, Any],
) -> Instrument:
    info = market.get("info") or {}
    listing_ts = info.get("onboardDate") or info.get("launchTime")
    listing_date = None
    if listing_ts:
        try:
            ms = int(listing_ts)
            if ms > 1e12:  # milisaniye
                listing_date = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            else:
                listing_date = datetime.fromtimestamp(ms, tz=timezone.utc)
        except (TypeError, ValueError):
            listing_date = None
    precision = market.get("precision") or {}
    limits = market.get("limits") or {}
    cost_min = (limits.get("cost") or {}).get("min")
    return Instrument(
        venue=venue,
        symbol=market.get("symbol", ""),
        market_type=_market_type_from_ccxt(market),  # type: ignore[arg-type]
        base=(market.get("base") or "").upper(),
        quote=(market.get("quote") or "").upper(),
        listing_date=listing_date,
        delisting_date=None if market.get("active", True) else datetime.now(timezone.utc),
        tick_size=Decimal(str(precision.get("price"))) if precision.get("price") is not None else None,
        lot_step=Decimal(str(precision.get("amount"))) if precision.get("amount") is not None else None,
        min_notional_usdt=Decimal(str(cost_min)) if cost_min is not None else None,
        is_active=bool(market.get("active", True)),
    )


def build_universe(
    mode: UniverseMode | None = None,
    *,
    config_path: Path | None = None,
    fetcher: "MarketFetcher | None" = None,
) -> list[Instrument]:
    """Sembol evrenini kur.

    Args:
        mode: all_liquid | top_volume | manual. None ise yaml'dan okunur.
        config_path: configs/symbols.yaml; None → settings'tan.
        fetcher: ccxt'i sarmalayan opsiyonel obje (test için inject).
    """
    s = get_settings()
    cfg_path = config_path or (s.configs_dir / "symbols.yaml")
    cfg = _load_yaml(cfg_path)
    universe_cfg = cfg.get("universe", {})
    use_mode: UniverseMode = mode or universe_cfg.get("mode", "all_liquid")  # type: ignore[assignment]

    venues: list[str] = list(universe_cfg.get("venues", []) or [])
    market_types: list[str] = list(universe_cfg.get("market_types", []) or [])
    quote = universe_cfg.get("quote", "USDT")
    raw_filters = universe_cfg.get("filters", {}) or {}
    filters = UniverseFilters(
        min_avg_volume_usdt_24h=_coerce_number(
            raw_filters.get("min_avg_volume_usdt_24h"), 1_000_000.0
        ),
        min_listing_age_days=int(_coerce_number(raw_filters.get("min_listing_age_days"), 365)),
        max_zero_volume_days_pct=_coerce_number(
            raw_filters.get("max_zero_volume_days_pct"), 5.0
        ),
        exclude_leveraged_tokens=bool(raw_filters.get("exclude_leveraged_tokens", True)),
        exclude_stablecoins=bool(raw_filters.get("exclude_stablecoins", True)),
        exclude_delisted=bool(raw_filters.get("exclude_delisted", True)),
    )

    if use_mode == "manual":
        manual_list: list[str] = list(universe_cfg.get("manual_list", []) or [])
        out: list[Instrument] = []
        for sym in manual_list:
            base, q = (sym.split("/") + [""])[:2] if "/" in sym else (sym, quote)
            for venue in venues or ["binance"]:
                out.append(
                    Instrument(
                        venue=venue,
                        symbol=sym,
                        market_type="spot",
                        base=base.upper(),
                        quote=(q or quote).upper(),
                    )
                )
        logger.bind(mode=use_mode, n=len(out)).info("universe.built")
        return out

    # all_liquid / top_volume → fetcher gerekir.
    if fetcher is None:
        fetcher = MarketFetcher(venues=venues)

    instruments: list[Instrument] = []
    for venue in venues:
        try:
            markets = fetcher.load_markets(venue)
            tickers = fetcher.fetch_tickers(venue)
        except Exception as exc:  # pragma: no cover - network path
            logger.bind(venue=venue, err=str(exc)).error("universe.fetch_fail")
            continue
        for sym, market in markets.items():
            ticker = tickers.get(sym)
            if not _passes_filters(market, ticker, filters, quote, market_types):
                continue
            instruments.append(_instrument_from_market(venue, market))

    if use_mode == "top_volume":
        n = int((universe_cfg.get("top_volume") or {}).get("n", 200))
        # hacme göre sırala (varsa)
        def _vol_key(inst: Instrument) -> float:
            t = (fetcher.tickers_cache.get(inst.venue) or {}).get(inst.symbol) if fetcher else None  # type: ignore[union-attr]
            if not t:
                return 0.0
            v = t.get("quoteVolume") or 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        instruments.sort(key=_vol_key, reverse=True)
        instruments = instruments[:n]

    logger.bind(mode=use_mode, n=len(instruments)).info("universe.built")
    return instruments


# ---------------------------------------------------------------------------
# ccxt sarmalayıcı — tests'te mock'lamak için.
# ---------------------------------------------------------------------------
class MarketFetcher:
    """ccxt çağrılarını izole eder; test edilebilirlik için."""

    def __init__(self, venues: list[str] | None = None) -> None:
        self.venues = venues or []
        self.tickers_cache: dict[str, dict[str, Any]] = {}
        self._exchanges: dict[str, Any] = {}

    def _exchange(self, venue: str) -> Any:  # pragma: no cover - import path
        if venue in self._exchanges:
            return self._exchanges[venue]
        import ccxt  # local import

        if not hasattr(ccxt, venue):
            raise ValueError(f"ccxt: bilinmeyen venue {venue}")
        # DQ-04 FIX (SEC54.5): futures endpoint — perp market metadata.
        ex = getattr(ccxt, venue)({"enableRateLimit": True, "options": {"defaultType": "future"}})
        self._exchanges[venue] = ex
        return ex

    def load_markets(self, venue: str) -> dict[str, Any]:  # pragma: no cover
        ex = self._exchange(venue)
        return ex.load_markets()

    def fetch_tickers(self, venue: str) -> dict[str, Any]:  # pragma: no cover
        ex = self._exchange(venue)
        try:
            tickers = ex.fetch_tickers()
        except Exception as exc:
            logger.bind(venue=venue, err=str(exc)).warning("universe.tickers_fail")
            tickers = {}
        self.tickers_cache[venue] = tickers
        return tickers
