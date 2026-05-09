"""On-Chain Signals Strategy — BTC on-chain metrics as edge.

HYPOTHESIS:
  BTC on-chain indicators (MVRV, NUPL_proxy, exchange flows, active addresses)
  provide structurally different alpha than price action because they reflect
  actual network usage and capital flows, not chart patterns.

DATA SOURCE: Coin Metrics Community API (free, no API key).
  CapMVRVCur  — Market Value to Realized Value ratio
  nupl_proxy  — Synthetic NUPL = (MVRV-1)/MVRV (mathematically equivalent)
  ex_netflow_z — Exchange netflow z-score (90d rolling)
  AdrActCnt   — Active addresses
  HashRate    — Mining hashrate

SIGNAL LOGIC (v1.0.0):
  LONG entry conditions (all required):
    1. MVRV < MVRV_BOTTOM (default 1.0)   — market undervalued vs realized
    2. nupl_proxy < NUPL_BOTTOM (0.25)     — holders mostly in loss/breakeven
    3. ex_netflow_z > -FLOW_SIGMA (0.0)    — exchange flow not extremely bearish
    4. price > EMA50                       — short-term trend confirmation
    5. Optional: AdrActCnt z-score > -1σ   — network not dead

  SHORT entry conditions (all required):
    1. MVRV > MVRV_TOP (default 3.5)       — market significantly overvalued
    2. nupl_proxy > NUPL_TOP (0.75)        — holders in extreme unrealized profit
    3. ex_netflow_z < FLOW_SIGMA (0.0)     — no extreme outflow (distribution)
    4. price < EMA50                       — short-term trend confirmation

  Risk management:
    SL: structural swing low/high (lookback 10 bars) + 0.5 ATR buffer
    TP: 3R primary (configurable)
    Size: standard ATR-based

EDGE ASSESSMENT:
  Real edge: On-chain data reflects actual capital movement (wallets, miners).
  It is NOT a retail indicator — BTC blockchain state is public but requires
  specialized data pipelines. The signal is slow (1d resolution, mean-reversion
  oriented) and combines poorly with intraday noise.

  Caveat: Glassnode/CryptoQuant dashboards have made MVRV/NUPL mainstream by
  2024-2026. The edge has compressed vs. 2020-2021. Institutional desks now
  monitor the same metrics. Edge is most reliable at extremes (MVRV > 3.5 or
  < 0.8) which occur rarely (1-3 times per cycle).

  BTC only — ETH/alts have insufficient on-chain history and different
  tokenomics for these thresholds to be reliable.

INTEGRATION:
  The strategy expects a merged DataFrame with OHLCV + on-chain columns.
  Use merge_onchain_to_ohlcv() to join on date (daily).

BACKTEST EXPECTATION:
  - 3y BTC 1d: few signals (2-6 per cycle), high expected value per signal
  - Compare to engulfing on BTC (was -0.9% CAGR): on-chain should show
    better CAGR but lower trade count
  - Combined: engulfing + on-chain filter should improve win rate

BTC only note: engulfing on BTC was weak (-0.9% CAGR) likely due to
  BTC trending in long cycles — on-chain confirms macro regime shifts.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema, _fractal_swings

# =====================================================================
# Constants / default thresholds
# =====================================================================

# MVRV thresholds (historically validated for BTC):
#   Bottom zone: < 1.0 → market below realized cost basis
#   Top zone:    > 3.5 → extreme overvaluation vs realized cap
MVRV_BOTTOM_DEFAULT: float = 1.0
MVRV_TOP_DEFAULT: float = 3.5

# NUPL proxy thresholds (derived: nupl = 1 - 1/mvrv):
#   NUPL < 0.25 → MVRV < 1.33 → majority of supply at loss or tiny profit
#   NUPL > 0.75 → MVRV > 4.0  → extreme unrealized profit (euphoria)
NUPL_BOTTOM_DEFAULT: float = 0.25
NUPL_TOP_DEFAULT: float = 0.75

# Exchange netflow z-score thresholds (90d rolling):
#   z > 1 → significant outflow (accumulation signal, bullish)
#   z < -1 → significant inflow (distribution signal, bearish)
FLOW_SIGMA_DEFAULT: float = 1.0

# Active address z-score lookback (252 bars ~ 1 year)
ADDR_ZSCORE_WINDOW: int = 252


# =====================================================================
# Feature helpers (on-chain specific)
# =====================================================================

def _mvrv_regime(
    mvrv: pd.Series,
    bottom_thresh: float = MVRV_BOTTOM_DEFAULT,
    top_thresh: float = MVRV_TOP_DEFAULT,
) -> tuple[pd.Series, pd.Series]:
    """Return boolean series: (is_bottom_zone, is_top_zone).

    Lookahead-free: uses point-in-time MVRV value (already lagged 1 bar
    in generate_signals to avoid same-bar lookahead).
    """
    is_bottom = mvrv < bottom_thresh
    is_top = mvrv > top_thresh
    return is_bottom.fillna(False), is_top.fillna(False)


def _nupl_regime(
    nupl: pd.Series,
    bottom_thresh: float = NUPL_BOTTOM_DEFAULT,
    top_thresh: float = NUPL_TOP_DEFAULT,
) -> tuple[pd.Series, pd.Series]:
    """Return (is_fear_zone, is_greed_zone)."""
    is_fear = nupl < bottom_thresh
    is_greed = nupl > top_thresh
    return is_fear.fillna(False), is_greed.fillna(False)


def _addr_zscore(addr_cnt: pd.Series, window: int = ADDR_ZSCORE_WINDOW) -> pd.Series:
    """Rolling z-score of active address count.

    High z: network usage spike → momentum (not used for entry, used as filter).
    Low z < -1: network dying → avoid long entries.
    """
    roll = addr_cnt.rolling(window, min_periods=window // 4)
    mean = roll.mean()
    std = roll.std(ddof=0).replace(0, float("nan"))
    return ((addr_cnt - mean) / std).fillna(0.0)


def _swing_sl_price(
    df: pd.DataFrame,
    i: int,
    direction: str,
    lookback: int = 10,
    atr_buffer: float = 0.5,
) -> float:
    """Structural SL: swing low/high in last `lookback` bars + ATR buffer.

    Lookahead-free: only uses bars [max(0, i-lookback)..i-1].
    """
    start = max(0, i - lookback)
    window = df.iloc[start:i]
    atr_val = float(df["atr14"].iloc[i]) if "atr14" in df.columns else 0.0

    if direction == "long":
        swing_low = float(window["low"].min()) if not window.empty else float(df["low"].iloc[i])
        return swing_low - atr_buffer * atr_val
    else:
        swing_high = float(window["high"].max()) if not window.empty else float(df["high"].iloc[i])
        return swing_high + atr_buffer * atr_val


# =====================================================================
# Merge helpers
# =====================================================================

def merge_onchain_to_ohlcv(
    ohlcv: pd.DataFrame,
    onchain: pd.DataFrame,
    *,
    on_col: str = "ts",
) -> pd.DataFrame:
    """Merge on-chain daily metrics into OHLCV DataFrame by date.

    Both DataFrames must have a 'ts' column (timezone-aware or naive UTC).
    On-chain is daily → matched to OHLCV bar date (floor to day).
    Forward-fills missing on-chain values (weekends/gaps).

    Returns OHLCV with on-chain columns appended. Missing on-chain
    periods remain NaN (no forward-fill across week gaps > 3 days).
    """
    if ohlcv.empty:
        return ohlcv.copy()

    onchain_cols = [c for c in onchain.columns if c not in ("ts", "asset", "time")]

    ohlcv = ohlcv.copy()
    # Normalize timestamps to UTC date for join
    ohlcv["_date"] = pd.to_datetime(ohlcv[on_col]).dt.normalize()

    oc = onchain.copy()
    oc["_date"] = pd.to_datetime(oc[on_col] if on_col in oc.columns else oc.get("time", oc.index)).dt.normalize()
    oc = oc[["_date"] + onchain_cols].drop_duplicates("_date")

    merged = ohlcv.merge(oc, on="_date", how="left")
    # Forward-fill on-chain gaps (holidays, weekends) — limit 3 days
    for col in onchain_cols:
        if col in merged.columns:
            merged[col] = merged[col].ffill(limit=3)

    merged = merged.drop(columns=["_date"])
    return merged


# =====================================================================
# Default manifest factory
# =====================================================================

def _default_manifest() -> StrategyManifest:
    """Default OnChainSignalsStrategy manifest."""
    raw: dict[str, Any] = {
        "name": "onchain_signals",
        "version": "1.0.0",
        "description": "BTC on-chain indicators (MVRV/NUPL/exchange flows) as macro regime signal",
        "universe": {"mode": "manual", "symbols": ["BTC/USDT"]},
        "timeframes": {"decision": "1d", "trend_filter": None, "refinement": None},
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "onchain_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "mvrv_bottom": MVRV_BOTTOM_DEFAULT,
                        "nupl_bottom": NUPL_BOTTOM_DEFAULT,
                        "flow_sigma_min": -FLOW_SIGMA_DEFAULT,
                        "addr_z_min": -1.5,
                    },
                },
                {
                    "id": "onchain_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "mvrv_top": MVRV_TOP_DEFAULT,
                        "nupl_top": NUPL_TOP_DEFAULT,
                        "flow_sigma_max": FLOW_SIGMA_DEFAULT,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 100,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 100,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_swing", "swing_lookback": 10, "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
        },
        "execution": {
            "decision_after_close": True,
            "entry_type": "market",
            "limit_offset_atr": 0.0,
            "invalidation_after_bars": 3,
        },
        "backtest": {
            "warmup_bars": 300,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class OnChainSignalsStrategy(Strategy):
    """BTC on-chain macro regime strategy.

    Uses: MVRV, synthetic NUPL (from MVRV), exchange netflow z-score,
    active address z-score, and EMA50 trend filter.

    BTC ONLY — on-chain thresholds are calibrated for Bitcoin.
    For other assets, the MVRV/NUPL cycle dynamics differ significantly.

    Data requirement: merged OHLCV + on-chain DataFrame (use merge_onchain_to_ohlcv).
    If on-chain columns are missing → returns empty signals (graceful degradation).
    """

    # Class-level name attribute for test compatibility
    name: str = "onchain_signals"

    # Required on-chain columns (if missing → no signals)
    REQUIRED_ONCHAIN_COLS: frozenset[str] = frozenset(["CapMVRVCur", "nupl_proxy"])

    def __init__(self, manifest: StrategyManifest | None = None) -> None:
        if manifest is None:
            manifest = _default_manifest()
        super().__init__(manifest)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical and on-chain derived features.

        On-chain columns expected: CapMVRVCur, nupl_proxy, ex_netflow_z, AdrActCnt.
        If missing → features set to NaN (signals will be suppressed).
        """
        if df.empty:
            return df.copy()

        df = df.sort_values("ts").reset_index(drop=True).copy()

        # --- Price-based features ---
        period = self.manifest.trend_filter.period or 50
        df["ema_trend"] = _ema(df["close"], period)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, float("nan"))

        # --- On-chain features (lag 1 bar to prevent lookahead) ---
        # We lag all on-chain metrics by 1 bar (T+1 signal on T data).
        # Coin Metrics publishes T daily data at T midnight — so T bar's
        # on-chain is known at T+1 open. This is conservative but safe.
        if "CapMVRVCur" in df.columns:
            df["mvrv_lag1"] = df["CapMVRVCur"].shift(1)
        else:
            df["mvrv_lag1"] = float("nan")

        if "nupl_proxy" in df.columns:
            df["nupl_lag1"] = df["nupl_proxy"].shift(1)
        else:
            df["nupl_lag1"] = float("nan")

        if "ex_netflow_z" in df.columns:
            df["flow_z_lag1"] = df["ex_netflow_z"].shift(1)
        else:
            df["flow_z_lag1"] = float("nan")

        if "AdrActCnt" in df.columns:
            df["addr_z"] = _addr_zscore(df["AdrActCnt"])
            df["addr_z_lag1"] = df["addr_z"].shift(1)
        else:
            df["addr_z_lag1"] = float("nan")

        if "HashRate" in df.columns:
            # Hashrate trend (90d EMA) — a collapsing hashrate signals miner stress
            df["hashrate_ema90"] = _ema(df["HashRate"].ffill(), 90)
            df["hashrate_declining"] = df["HashRate"] < df["hashrate_ema90"] * 0.9
        else:
            df["hashrate_declining"] = False

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate on-chain regime signals.

        Returns Signal list. No signals if on-chain columns missing.
        """
        if df.empty:
            return []

        # Check required on-chain columns
        missing = self.REQUIRED_ONCHAIN_COLS - set(df.columns)
        if missing:
            self._log.bind(missing=list(missing)).warning(
                "onchain_signals.missing_onchain_cols — no signals"
            )
            return []

        if "mvrv_lag1" not in df.columns:
            df = self.prepare_features(df)

        # Extract params from manifest
        long_pattern = next(
            (p for p in self.manifest.signals.patterns if p.id == "onchain_long"), None
        )
        short_pattern = next(
            (p for p in self.manifest.signals.patterns if p.id == "onchain_short"), None
        )

        lp = long_pattern.params if long_pattern and long_pattern.enabled else {}
        sp = short_pattern.params if short_pattern and short_pattern.enabled else {}

        mvrv_bottom = float(lp.get("mvrv_bottom", MVRV_BOTTOM_DEFAULT))
        nupl_bottom = float(lp.get("nupl_bottom", NUPL_BOTTOM_DEFAULT))
        flow_sigma_min = float(lp.get("flow_sigma_min", -FLOW_SIGMA_DEFAULT))
        addr_z_min = float(lp.get("addr_z_min", -1.5))

        mvrv_top = float(sp.get("mvrv_top", MVRV_TOP_DEFAULT))
        nupl_top = float(sp.get("nupl_top", NUPL_TOP_DEFAULT))
        flow_sigma_max = float(sp.get("flow_sigma_max", FLOW_SIGMA_DEFAULT))

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        sl_lookback = int(
            self.manifest.risk.get("stop_loss", {}).get("swing_lookback", 10)
        )
        sl_atr_buf = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.5)
        )

        trend_required = self.manifest.trend_filter.required
        atr_min = self.manifest.signals.filters.atr_min_pct

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "binance"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "BTC/USDT"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)

            if atr <= 0 or np.isnan(atr):
                continue
            if atr_min > 0 and (atr / close) < atr_min:
                continue

            mvrv = float(row.get("mvrv_lag1", float("nan")))
            nupl = float(row.get("nupl_lag1", float("nan")))
            flow_z = float(row.get("flow_z_lag1", 0.0))
            addr_z = float(row.get("addr_z_lag1", 0.0))
            ema = float(row.get("ema_trend", float("nan")))

            # Skip bars without on-chain data
            if np.isnan(mvrv) or np.isnan(nupl):
                continue

            # --- LONG signal ---
            if long_pattern and long_pattern.enabled:
                long_cond = (
                    mvrv < mvrv_bottom              # MVRV below realized cost
                    and nupl < nupl_bottom           # Majority at loss/breakeven
                    and (np.isnan(flow_z) or flow_z > flow_sigma_min)  # No panic inflow
                    and (np.isnan(addr_z) or addr_z > addr_z_min)      # Network alive
                )
                if trend_required and not np.isnan(ema):
                    long_cond = long_cond and (close > ema)

                if long_cond:
                    sl = _swing_sl_price(df, i, "long", lookback=sl_lookback, atr_buffer=sl_atr_buf)
                    risk = close - sl
                    if risk <= 0:
                        sl = close - 2 * atr
                        risk = 2 * atr
                    tp = close + primary_R * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="onchain_long",
                        confluence_score=float(long_pattern.weight),
                        sl_price=float(sl),
                        tp_price=float(tp),
                        suggested_size_atr=sl_atr_buf,
                        metadata={
                            "mvrv": mvrv,
                            "nupl_proxy": nupl,
                            "ex_netflow_z": flow_z,
                            "addr_z": addr_z,
                            "ema_trend": ema if not np.isnan(ema) else None,
                            "atr14": atr,
                            "regime": "capitulation" if mvrv < 0.8 else "bottom_zone",
                        },
                    )
                    out.append(sig)

            # --- SHORT signal ---
            if short_pattern and short_pattern.enabled:
                short_cond = (
                    mvrv > mvrv_top                 # MVRV extremely elevated
                    and nupl > nupl_top              # Extreme unrealized profit (euphoria)
                    and (np.isnan(flow_z) or flow_z < flow_sigma_max)  # No major outflow spike
                )
                if trend_required and not np.isnan(ema):
                    short_cond = short_cond and (close < ema)

                if short_cond:
                    sl = _swing_sl_price(df, i, "short", lookback=sl_lookback, atr_buffer=sl_atr_buf)
                    risk = sl - close
                    if risk <= 0:
                        sl = close + 2 * atr
                        risk = 2 * atr
                    tp = close - primary_R * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id="onchain_short",
                        confluence_score=float(short_pattern.weight),
                        sl_price=float(sl),
                        tp_price=float(tp),
                        suggested_size_atr=sl_atr_buf,
                        metadata={
                            "mvrv": mvrv,
                            "nupl_proxy": nupl,
                            "ex_netflow_z": flow_z,
                            "ema_trend": ema if not np.isnan(ema) else None,
                            "atr14": atr,
                            "regime": "euphoria",
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("onchain_signals.generated")
        return out
