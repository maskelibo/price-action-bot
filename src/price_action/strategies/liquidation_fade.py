"""Liquidation Cascade Fade Strategy — Synthetic Proxy Version.

## Status: DEFERRED (see hypothesis 2026-05-09-liquidation-cascade-fade.md)

Real liquidation data (CoinGlass, Bybit, Binance) is unavailable for historical
backtesting without paid subscriptions ($29+/month). This module implements a
synthetic proxy approach using free data:

    CASCADE PROXY = Open Interest drop + Taker sell/buy ratio extreme

    Long cascade proxy: OI drops sharply (>= 95th pctile OI drop magnitude) AND
                        taker sell ratio extreme (>= rolling 90th pctile)
                        → Proxy for long liquidation cascade
                        → Fade: next-bar bullish pattern → LONG

    Short cascade proxy: OI rises sharply (>= 95th pctile OI increase) AND
                         taker buy ratio extreme (>= rolling 90th pctile)
                         → Proxy for short liquidation cascade
                         → Fade: next-bar bearish pattern → SHORT

## Structural Logic

The `liquidation_extreme_signal()` helper implements the core detection:
    1. Rolling 30-bar percentile bands (95th for extreme, shift(1) = lookahead-free)
    2. OI change threshold to filter noise from routine position building
    3. Taker flow confirmation: cascade produces taker-dominated flow
    4. Combined: both conditions must fire on same bar

## Limitations of Proxy vs Real Data

Real liquidation data would give:
    - Dollar-denominated liquidation totals (e.g., $300M in 4h)
    - Long vs short liquidation separated
    - Exchange-level breakdown (Binance, Bybit, OKX combined)
    - True cascade identification (spike in liquidation rate, not OI proxy)

Proxy limitations:
    - OI drop can be voluntary (profit-taking), not only forced liquidations
    - Taker flow extreme can be news-driven without cascade
    - Daily resolution misses intraday cascade timing
    - ~30 days of daily proxy data (free limit) — too few for robust backtest

## Backtest Viability

    FREE data: ~30 days daily — insufficient (need 200+ bars minimum)
    PAID (CoinGlass $29/mo): 3yr daily history — sufficient
    DEFER condition: activate when paid data available or 60-day OKX accumulation complete

## Decorrelation

    vs Funding MR: OI/taker proxy fires on ACUTE discrete events; funding MR fires
    on multi-day accumulated carry cost. Low temporal overlap.
    vs Engulfing: cascade fade is event-triggered counter-trend; engulfing is
    trend-following. Fires in different market regimes.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rolling window for adaptive percentile bands (bars)
ROLLING_WINDOW: int = 30

# Percentile for "extreme" detection (both OI change and taker ratio)
EXTREME_PCTILE: float = 0.90   # 90th percentile (less strict than funding's 95th)
EXTREME_PCTILE_HIGH: float = 0.95  # 95th for OI magnitude

# Minimum OI change magnitude to consider (vs noise)
MIN_OI_CHANGE_PCT: float = 0.02  # 2% OI change in one bar

# Taker ratio thresholds (0.0–1.0; taker_sell_ratio = sell_vol / (buy+sell))
TAKER_SELL_EXTREME: float = 0.60   # > 60% taker sell → long cascade proxy
TAKER_BUY_EXTREME: float = 0.40    # < 40% taker sell (= 60% buy) → short cascade proxy

# Symbols supported (perp markets with reliable OI data)
SUPPORTED_SYMBOLS: frozenset[str] = frozenset({
    "BTC/USDT:USDT",
    "BTCUSDT",
    "ETH/USDT:USDT",
    "ETHUSDT",
})


# ---------------------------------------------------------------------------
# Helper: liquidation_extreme_signal (the core public function)
# ---------------------------------------------------------------------------

def liquidation_extreme_signal(
    liq_data: pd.DataFrame,
    *,
    threshold_pct: float = EXTREME_PCTILE,
    min_oi_change: float = MIN_OI_CHANGE_PCT,
    taker_sell_extreme: float = TAKER_SELL_EXTREME,
    taker_buy_extreme: float = TAKER_BUY_EXTREME,
    rolling_window: int = ROLLING_WINDOW,
) -> tuple[pd.Series, pd.Series]:
    """Liquidation cascade extreme signal detection — lookahead-free.

    Parameters
    ----------
    liq_data : pd.DataFrame
        Columns expected: ts, oi_pct_change, taker_sell_ratio
        (output of `liquidation_ingest.build_cascade_proxy`)
    threshold_pct : float
        Rolling percentile threshold for OI change magnitude (default: 0.90 = 90th pctile).
    min_oi_change : float
        Minimum absolute OI % change to qualify (noise floor, default 0.02 = 2%).
    taker_sell_extreme : float
        Taker sell ratio threshold for long cascade proxy (default 0.60).
    taker_buy_extreme : float
        Taker buy ratio threshold for short cascade proxy (default 0.40).
    rolling_window : int
        Bars for rolling adaptive percentile (default 30).

    Returns
    -------
    long_cascade : pd.Series[bool]
        True where OI dropped sharply AND taker sell was extreme → proxy for
        long liquidation cascade → fade = LONG signal.
    short_cascade : pd.Series[bool]
        True where OI rose sharply (OI increase = short covering or new shorts) AND
        taker buy was extreme → proxy for short liquidation cascade → fade = SHORT signal.

    Lookahead safety
    ----------------
    - Rolling percentiles use shift(1) before rolling → bar t sees [t-window .. t-1] only
    - taker_sell_ratio and oi_pct_change at bar t are the CURRENT bar's values
    - Signal fires at bar t → traded at bar t+1 open (next-bar entry) in strategy
    """
    if liq_data is None or liq_data.empty:
        empty = pd.Series([], dtype=bool)
        return empty, empty

    df = liq_data.copy()
    if "ts" in df.columns:
        df = df.sort_values("ts").reset_index(drop=True)

    n = len(df)

    # ── OI change magnitude (absolute value) ──────────────────────────────
    if "oi_pct_change" not in df.columns:
        df["oi_pct_change"] = float("nan")
    oi_chg = df["oi_pct_change"].fillna(0.0)
    oi_drop = -oi_chg  # positive when OI decreases (long closures)

    # Adaptive threshold: rolling 95th percentile of OI drop magnitude
    # shift(1) → bar t sees [t-window, t-1]
    oi_drop_lagged = oi_drop.shift(1)
    oi_threshold = oi_drop_lagged.rolling(
        rolling_window, min_periods=max(5, rolling_window // 4)
    ).quantile(EXTREME_PCTILE_HIGH)

    # Adaptive threshold for OI rise (short cascade proxy)
    oi_rise_lagged = oi_chg.shift(1).clip(lower=0)
    oi_rise_threshold = oi_rise_lagged.rolling(
        rolling_window, min_periods=max(5, rolling_window // 4)
    ).quantile(EXTREME_PCTILE_HIGH)

    # ── Taker ratio ────────────────────────────────────────────────────────
    if "taker_sell_ratio" not in df.columns:
        df["taker_sell_ratio"] = float("nan")
    taker_sell = df["taker_sell_ratio"].fillna(0.5)

    # Adaptive taker extreme: rolling quantile (also shift(1))
    taker_sell_lagged = taker_sell.shift(1)
    taker_sell_extreme_threshold = taker_sell_lagged.rolling(
        rolling_window, min_periods=max(5, rolling_window // 4)
    ).quantile(threshold_pct)
    taker_buy_extreme_threshold = taker_sell_lagged.rolling(
        rolling_window, min_periods=max(5, rolling_window // 4)
    ).quantile(1.0 - threshold_pct)

    # ── Long cascade proxy ─────────────────────────────────────────────────
    # OI dropped >= threshold AND OI drop >= absolute floor AND taker sell extreme
    long_cascade = (
        (oi_drop >= oi_threshold.fillna(float("inf")))
        & (oi_drop >= min_oi_change)
        & (taker_sell >= taker_sell_extreme_threshold.fillna(taker_sell_extreme))
    )

    # ── Short cascade proxy ────────────────────────────────────────────────
    # OI rose >= threshold (shorts being added/covering) AND taker buy extreme
    short_cascade = (
        (oi_chg >= oi_rise_threshold.fillna(float("inf")))
        & (oi_chg >= min_oi_change)
        & (taker_sell <= taker_buy_extreme_threshold.fillna(taker_buy_extreme))
    )

    # Fill NaN (first rolling_window bars have no threshold)
    long_cascade = long_cascade.fillna(False).astype(bool)
    short_cascade = short_cascade.fillna(False).astype(bool)

    return long_cascade, short_cascade


# ---------------------------------------------------------------------------
# Feature helpers (OHLCV-based, same pattern as other strategies)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi, lo, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _detect_bullish_confirmation(df: pd.DataFrame) -> pd.Series:
    """Next-bar bullish confirmation patterns: engulfing OR pin bar OR inside-bar breakout.

    Lookahead-free: uses only current bar's OHLCV vs prev bar.
    """
    o, c = df["open"], df["close"]
    h, l = df["high"], df["low"]
    po, pc_prev = o.shift(1), c.shift(1)
    ph, pl = h.shift(1), l.shift(1)

    # Bullish engulfing
    engulf = (c > o) & (pc_prev < po) & (c >= po) & (o <= pc_prev)

    # Bullish pin bar (long lower wick)
    rng = (h - l).replace(0, np.nan)
    lower_wick = (pd.concat([o, c], axis=1).min(axis=1) - l) / rng
    body_ratio = (c - o).abs() / rng
    pin = (lower_wick >= 0.60) & (body_ratio <= 0.33)

    # Inside-bar bullish breakout (prev was inside, now breaks up)
    inside_prev = (ph < ph.shift(1)) & (pl > pl.shift(1))
    ib_bull = inside_prev.shift(1).fillna(False) & (c > ph)

    return (engulf | pin | ib_bull).fillna(False)


def _detect_bearish_confirmation(df: pd.DataFrame) -> pd.Series:
    """Next-bar bearish confirmation patterns: engulfing OR pin bar OR inside-bar breakout."""
    o, c = df["open"], df["close"]
    h, l = df["high"], df["low"]
    po, pc_prev = o.shift(1), c.shift(1)
    ph, pl = h.shift(1), l.shift(1)

    # Bearish engulfing
    engulf = (c < o) & (pc_prev > po) & (c <= po) & (o >= pc_prev)

    # Bearish pin bar (long upper wick)
    rng = (h - l).replace(0, np.nan)
    upper_wick = (h - pd.concat([o, c], axis=1).max(axis=1)) / rng
    body_ratio = (c - o).abs() / rng
    pin = (upper_wick >= 0.60) & (body_ratio <= 0.33)

    # Inside-bar bearish breakout
    inside_prev = (ph < ph.shift(1)) & (pl > pl.shift(1))
    ib_bear = inside_prev.shift(1).fillna(False) & (c < pl)

    return (engulf | pin | ib_bear).fillna(False)


def _swing_sl(df: pd.DataFrame, lookback: int = 5) -> tuple[pd.Series, pd.Series]:
    """Structural SL: rolling swing high/low over last `lookback` bars + 1 ATR buffer.

    shift(1) → bar t sees [t-lookback, t-1] only.
    """
    sh = df["high"].shift(1).rolling(lookback, min_periods=1).max()
    sl = df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return sh, sl


# ---------------------------------------------------------------------------
# Default manifest
# ---------------------------------------------------------------------------

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "liquidation_fade",
        "version": "0.1.0",
        "description": (
            "Fade liquidation cascades using synthetic proxy (OI drop + taker flow). "
            "DEFERRED: real liquidation data requires paid CoinGlass subscription. "
            "Proxy version — OI + taker ratio as cascade proxy — for forward accumulation."
        ),
        "timeframes": {"decision": "1d"},
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "liq_cascade_fade_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "rolling_window": ROLLING_WINDOW,
                        "extreme_pctile": EXTREME_PCTILE,
                        "min_oi_change": MIN_OI_CHANGE_PCT,
                        "taker_sell_extreme": TAKER_SELL_EXTREME,
                    },
                },
                {
                    "id": "liq_cascade_fade_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "rolling_window": ROLLING_WINDOW,
                        "extreme_pctile": EXTREME_PCTILE,
                        "min_oi_change": MIN_OI_CHANGE_PCT,
                        "taker_buy_extreme": TAKER_BUY_EXTREME,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_plus_atr", "swing_lookback": 5, "atr_multiplier": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 35,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------

class LiquidationFadeStrategy(Strategy):
    """Liquidation cascade fade — synthetic proxy (OI + taker flow).

    Input df must have columns:
        From OHLCV: ts, open, high, low, close, volume
        From cascade proxy: oi_pct_change, taker_sell_ratio

    The cascade proxy columns are merged before calling generate_signals().
    Use `liquidation_ingest.build_cascade_proxy()` to fetch and merge.

    This is a DEFERRED strategy — real liquidation data unavailable free.
    Implements the proxy version to allow forward accumulation testing.
    """

    def __init__(self, manifest: StrategyManifest | None = None) -> None:
        if manifest is None:
            manifest = _default_manifest()
        super().__init__(manifest)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # Cascade proxy signals (vectorized, lookahead-free)
        params = {}
        for pat in self.manifest.signals.patterns:
            params.update(pat.params)

        long_cas, short_cas = liquidation_extreme_signal(
            df,
            threshold_pct=float(params.get("extreme_pctile", EXTREME_PCTILE)),
            min_oi_change=float(params.get("min_oi_change", MIN_OI_CHANGE_PCT)),
            taker_sell_extreme=float(params.get("taker_sell_extreme", TAKER_SELL_EXTREME)),
            taker_buy_extreme=float(params.get("taker_buy_extreme", TAKER_BUY_EXTREME)),
            rolling_window=int(params.get("rolling_window", ROLLING_WINDOW)),
        )
        # Cascade at bar t → confirmation expected at bar t+1 → signal at t+1
        # Use shift(1) so at bar t+1 we know cascade happened at bar t
        df["long_cascade_prev"] = long_cas.shift(1).fillna(False)
        df["short_cascade_prev"] = short_cas.shift(1).fillna(False)

        # Confirmation patterns (at current bar — bar t+1)
        df["bull_confirm"] = _detect_bullish_confirmation(df)
        df["bear_confirm"] = _detect_bearish_confirmation(df)

        # Structural SL anchors
        swing_lookback = int(params.get("swing_lookback", 5))
        df["swing_high_sl"], df["swing_low_sl"] = _swing_sl(df, lookback=swing_lookback)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate fade signals from synthetic cascade proxy.

        Signal condition:
            LONG:  long_cascade_prev=True (cascade on prev bar) AND bull_confirm=True
            SHORT: short_cascade_prev=True AND bear_confirm=True

        Entry: next bar open (post_only limit at open)
        SL: structural swing_low - 1 ATR (long) / swing_high + 1 ATR (short)
        TP: entry + 2R * risk
        """
        if df.empty:
            return []

        # Check for required proxy columns
        missing_proxy = [c for c in ["oi_pct_change", "taker_sell_ratio"] if c not in df.columns]
        if missing_proxy:
            self._log.warning(
                "liq_fade.missing_proxy_cols",
                extra={
                    "missing": missing_proxy,
                    "note": "Run liquidation_ingest.build_cascade_proxy() first",
                },
            )
            return []

        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        primary_r = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        atr_mult = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_multiplier", 1.0)
        )

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            long_ok = bool(row.get("long_cascade_prev", False)) and bool(row.get("bull_confirm", False))
            short_ok = bool(row.get("short_cascade_prev", False)) and bool(row.get("bear_confirm", False))

            if not long_ok and not short_ok:
                continue

            sw_high = float(row.get("swing_high_sl") or close + 2 * atr)
            sw_low = float(row.get("swing_low_sl") or close - 2 * atr)

            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            if long_ok:
                sl_price = sw_low - atr_mult * atr
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_r * risk
                out.append(self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="liq_cascade_fade_long",
                    confluence_score=1.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=atr_mult,
                    metadata={
                        "atr14": atr,
                        "oi_pct_change": float(row.get("oi_pct_change") or float("nan")),
                        "taker_sell_ratio": float(row.get("taker_sell_ratio") or float("nan")),
                        "swing_low": sw_low,
                        "proxy_note": "synthetic_oi_taker_proxy",
                    },
                ))

            if short_ok:
                sl_price = sw_high + atr_mult * atr
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_r * risk
                out.append(self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="liq_cascade_fade_short",
                    confluence_score=1.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=atr_mult,
                    metadata={
                        "atr14": atr,
                        "oi_pct_change": float(row.get("oi_pct_change") or float("nan")),
                        "taker_sell_ratio": float(row.get("taker_sell_ratio") or float("nan")),
                        "swing_high": sw_high,
                        "proxy_note": "synthetic_oi_taker_proxy",
                    },
                ))

        self._log.bind(n=len(out), bars=len(df)).info("liq_fade.signals.generated")
        return out
