"""Per-symbol realistic slippage model.

Live Binance orderbook'tan spread ve derinlik-ağırlıklı fiyat etkisi hesaplar.
Backtest engine'e symbol_slippage_map olarak iletilir.

Kullanım:
    from price_action.backtest.slippage import build_slippage_map, SlippageModel

    slip_map = build_slippage_map(SYMBOLS)          # live API çağrısı
    model    = SlippageModel(slip_map)
    bps      = model.get_bps("BTC/USDT", notional=5000)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Sabitler — kategori bazlı fallback (API erişilemezse)
# ---------------------------------------------------------------------------

# Binance USDT pair → tahmini spread bps (mid - best_bid bps)
# Kaynak: piyasa bilgisi + literatür
FALLBACK_SLIPPAGE_BPS: Dict[str, float] = {
    # Large-cap  (piyasa derinliği yüksek)
    "BTC/USDT":  5.0,
    "ETH/USDT":  6.0,
    "BNB/USDT":  8.0,
    "SOL/USDT": 10.0,
    # Mid-cap
    "XRP/USDT": 12.0,
    "ADA/USDT": 15.0,
    "AVAX/USDT":14.0,
    # Small-cap (geniş spread, sığ defter)
    "DOGE/USDT":20.0,
    "LINK/USDT":22.0,
    "DOT/USDT": 18.0,
}

# Notional eşiklerine göre derinlik çarpanı ($1K baseline = 1.0x)
# Daha büyük emir → daha fazla market impact
NOTIONAL_MULTIPLIER: List[tuple[float, float]] = [
    (1_000,  1.0),
    (5_000,  1.4),
    (10_000, 1.8),
]


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------

@dataclass
class OrderBookSnapshot:
    """Tek anlık orderbook ölçümü."""
    symbol: str
    timestamp: float                         # Unix epoch (s)
    best_bid: float
    best_ask: float
    mid_price: float
    spread_bps: float                        # (ask - bid) / mid * 10_000
    depth_impact: Dict[int, float]           # notional → slippage_bps
    raw_bids: List[tuple[float, float]]      # [(price, qty), ...]
    raw_asks: List[tuple[float, float]]

    @property
    def half_spread_bps(self) -> float:
        """Tek taraf maliyet tahmini."""
        return self.spread_bps / 2.0


@dataclass
class SlippageModel:
    """Per-symbol slippage lookup.

    symbol_slippage_map: {symbol: bps_at_1K} — build_slippage_map() çıktısı
    notional: hangi emir büyüklüğünde bakılacak (varsayılan $5K = production lot)
    """
    symbol_slippage_map: Dict[str, float] = field(default_factory=dict)
    default_bps: float = 10.0               # Bilinmeyen semboller için
    notional: float = 5_000.0              # Referans emir büyüklüğü

    def get_bps(self, symbol: str, notional: Optional[float] = None) -> float:
        """Sembol + notional için slippage bps döndür."""
        base = self.symbol_slippage_map.get(symbol, self.default_bps)
        n = notional if notional is not None else self.notional
        multiplier = _notional_multiplier(n)
        return base * multiplier

    def summary(self) -> List[dict]:
        """Tüm sembollerin $1K/$5K/$10K slippage tablosu."""
        rows = []
        for sym, bps_1k in sorted(self.symbol_slippage_map.items()):
            rows.append({
                "symbol": sym,
                "spread_bps_1k": round(bps_1k, 2),
                "slippage_bps_5k": round(bps_1k * _notional_multiplier(5_000), 2),
                "slippage_bps_10k": round(bps_1k * _notional_multiplier(10_000), 2),
                "category": _category(bps_1k),
            })
        return rows


# ---------------------------------------------------------------------------
# Orderbook helpers
# ---------------------------------------------------------------------------

def _notional_multiplier(notional: float) -> float:
    """Emir büyüklüğüne göre market-impact çarpanı."""
    for threshold, mult in reversed(NOTIONAL_MULTIPLIER):
        if notional >= threshold:
            return mult
    return 1.0


def _category(bps: float) -> str:
    if bps <= 8:
        return "large-cap"
    elif bps <= 16:
        return "mid-cap"
    else:
        return "small-cap"


def _depth_weighted_price(levels: List[tuple[float, float]], notional: float, side: str) -> float:
    """Belirli notional'i doldurmak için VWAP fiyat hesapla.

    levels: [(price, qty_base), ...]  — asks için ascending, bids için descending
    Returns: average fill price, veya dolu doldurulamazsa son seviye fiyatı.
    """
    remaining = notional
    total_cost = 0.0
    total_qty = 0.0
    for price, qty in levels:
        cost_at_level = price * qty
        if cost_at_level >= remaining:
            fill_qty = remaining / price
            total_cost += fill_qty * price
            total_qty += fill_qty
            remaining = 0.0
            break
        total_cost += cost_at_level
        total_qty += qty
        remaining -= cost_at_level
    if total_qty <= 0:
        return levels[-1][0] if levels else 0.0
    return total_cost / total_qty


def _compute_impact_bps(mid: float, fill_price: float, side: str) -> float:
    """Doldurma fiyatının mid'e göre sapması (bps)."""
    if mid <= 0:
        return 0.0
    if side == "buy":
        return (fill_price - mid) / mid * 10_000
    else:
        return (mid - fill_price) / mid * 10_000


def fetch_orderbook_snapshot(symbol: str, limit: int = 20) -> OrderBookSnapshot:
    """Binance'tan tek snapshot — ccxt kullanır.

    Limit=20 → ilk 20 seviye yeterli ($10K emir için genellikle fazla).
    RateLimit: ccxt otomatik yönetir; fonksiyon sembol başına 1x çağrılır.
    """
    try:
        import ccxt  # type: ignore
    except ImportError as e:
        raise ImportError("ccxt kurulu değil: pip install ccxt") from e

    # DQ-04 FIX (SEC54.5): futures endpoint — perp orderbook depth
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    # CCXT sembol formatı BTC/USDT → binance native BTCUSDT
    book = ex.fetch_order_book(symbol, limit=limit)

    bids: List[tuple[float, float]] = [(float(p), float(q)) for p, q in book["bids"]]
    asks: List[tuple[float, float]] = [(float(p), float(q)) for p, q in book["asks"]]

    if not bids or not asks:
        raise ValueError(f"Boş orderbook: {symbol}")

    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    spread_bps = (best_ask - best_bid) / mid * 10_000

    # Derinlik etkisi: $1K, $5K, $10K için BUY tarafı (asks)
    depth_impact: Dict[int, float] = {}
    for notional in [1_000, 5_000, 10_000]:
        fill = _depth_weighted_price(asks, notional, "buy")
        impact = _compute_impact_bps(mid, fill, "buy")
        depth_impact[notional] = round(impact, 2)

    return OrderBookSnapshot(
        symbol=symbol,
        timestamp=time.time(),
        best_bid=best_bid,
        best_ask=best_ask,
        mid_price=mid,
        spread_bps=round(spread_bps, 2),
        depth_impact=depth_impact,
        raw_bids=bids,
        raw_asks=asks,
    )


# ---------------------------------------------------------------------------
# Ana builder fonksiyonu
# ---------------------------------------------------------------------------

def build_slippage_map(
    symbols: List[str],
    notional_ref: float = 1_000.0,
    use_live: bool = True,
    rate_limit_sleep: float = 0.3,
) -> Dict[str, float]:
    """Her sembol için slippage_bps (at notional_ref) döndür.

    Live erişim başarısızsa FALLBACK_SLIPPAGE_BPS kullanılır.

    Args:
        symbols: ["BTC/USDT", "ETH/USDT", ...]
        notional_ref: Baseline emir büyüklüğü (bps bu notional'da)
        use_live: False → sadece fallback
        rate_limit_sleep: Semboller arası bekleme (s)

    Returns:
        {symbol: half_spread_bps_at_notional_ref}
    """
    result: Dict[str, float] = {}
    snapshots: Dict[str, OrderBookSnapshot] = {}

    if use_live:
        for sym in symbols:
            try:
                snap = fetch_orderbook_snapshot(sym)
                snapshots[sym] = snap
                # Referans notional için depth impact kullan
                if notional_ref in snap.depth_impact:
                    result[sym] = snap.depth_impact[notional_ref]
                else:
                    # Interpolasyon: nearest notional
                    nearest_key = min(snap.depth_impact.keys(), key=lambda k: abs(k - notional_ref))
                    result[sym] = snap.depth_impact[nearest_key]
                time.sleep(rate_limit_sleep)
            except Exception as exc:
                # Fallback'e geç
                fallback = FALLBACK_SLIPPAGE_BPS.get(sym, 15.0)
                result[sym] = fallback
                import warnings
                warnings.warn(
                    f"Orderbook fetch failed for {sym} ({exc}), using fallback {fallback} bps",
                    stacklevel=2,
                )
    else:
        for sym in symbols:
            result[sym] = FALLBACK_SLIPPAGE_BPS.get(sym, 15.0)

    return result


def build_slippage_model(
    symbols: List[str],
    notional_ref: float = 5_000.0,
    use_live: bool = True,
) -> SlippageModel:
    """Tam SlippageModel nesnesi döndür — engine'e geçirilmeye hazır."""
    bps_map = build_slippage_map(symbols, notional_ref=notional_ref, use_live=use_live)
    return SlippageModel(
        symbol_slippage_map=bps_map,
        default_bps=15.0,
        notional=notional_ref,
    )


__all__ = [
    "OrderBookSnapshot",
    "SlippageModel",
    "FALLBACK_SLIPPAGE_BPS",
    "build_slippage_map",
    "build_slippage_model",
    "fetch_orderbook_snapshot",
]
