"""Session VWAP Mean-Reversion strategy (HYP-2026-05-17-scalp-02).

Strategy concept (Brian Shannon 2008/2022 "Maximum Trading Gains with Anchored VWAP" +
Bollinger 1980s + Wilder 1978 ADX chop filter + Makarov & Schoar 2020 crypto microstructure):

  - Session VWAP anchored at UTC 00:00 daily — fair-value benchmark.
  - 24-bar (2h on 5m TF) rolling std of (close - VWAP) deviation = volatility cone.
  - When close stretches +/- 2.0 sigma beyond VWAP AND 1h ADX(14) < 20 (chop regime
    = mean-reversion conditions, not trending whipsaw), fade the move.
  - Exit on VWAP retag (dynamic TP) OR 1.0R fixed (whichever first) OR 18-bar (90min)
    time-stop.

Lookahead-free contract:
  - Session VWAP uses cumulative sum from session start (00:00 UTC) through bar t —
    standard. Signal fires at bar t close; engine fills t+1 open.
  - 1h ADX merged via .shift(1) merge_asof backward (no future leak).
  - rolling std uses pandas .rolling(24).std() — past 24 bars including t (causal).

Configuration (manifest params):
  vwap_anchor       : "session" (UTC 00:00) — only session supported in v1
  sigma_window      : 24 (= 2h on 5m TF)
  sigma_mult        : 2.0
  adx_threshold     : 20
  adx_timeframe     : "1h"
  skip_first_n_bars : 12 (= 1h after session open; VWAP not yet stable)
  atr_sl_mult       : 1.0
  tp_r              : 1.0
  hold_max_bars     : 18 (= 90 min on 5m TF)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Indicators
# =====================================================================

def _session_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP — cumulative from UTC 00:00 each day.

    typical_price = (high + low + close) / 3
    VWAP_t = cumsum(tp * vol)[t] / cumsum(vol)[t]
    Reset at each UTC date change.

    Returns:
      pd.Series indexed same as df, NaN before first vol > 0.
    """
    ts = pd.to_datetime(df["ts"], utc=True)
    date_key = ts.dt.date
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy()
    vol = df["volume"].clip(lower=0.0).to_numpy()
    tpv = typical * vol

    # cumsum within each session (date) — restart at each new date
    cum_tpv = pd.Series(tpv, index=df.index).groupby(date_key.values).cumsum()
    cum_vol = pd.Series(vol, index=df.index).groupby(date_key.values).cumsum()

    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where(cum_vol.to_numpy() > 0,
                        cum_tpv.to_numpy() / cum_vol.to_numpy(),
                        np.nan)
    return pd.Series(vwap, index=df.index, dtype=float, name="session_vwap")


def _adx_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX(14). Lookahead-free (causal smoothing)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    plus_dm = (high - high.shift(1))
    minus_dm = (low.shift(1) - low)
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > (high - high.shift(1))) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder smoothing = EMA alpha=1/period
    atr_w = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_w.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_w.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx.fillna(0.0)


def _merge_adx_1h(df_5m: pd.DataFrame, df_1h: pd.DataFrame) -> pd.Series:
    """Merge 1h ADX into 5m df via backward asof (causal — no future leak).

    Each 5m bar gets the most recent 1h ADX value <= bar timestamp.
    """
    if df_1h is None or df_1h.empty:
        return pd.Series(np.nan, index=df_5m.index)
    df_1h = df_1h.sort_values("ts").copy()
    df_1h["adx_1h"] = _adx_wilder(df_1h, period=14)
    # backward asof: 5m bar's ts -> latest 1h bar with ts <= 5m ts
    # IMPORTANT: shift 1h adx by 1 bar to ensure no same-bar peek
    df_1h["adx_1h"] = df_1h["adx_1h"].shift(1)
    df_1h_compact = df_1h[["ts", "adx_1h"]].dropna()
    if df_1h_compact.empty:
        return pd.Series(np.nan, index=df_5m.index)

    left = pd.DataFrame({"ts": pd.to_datetime(df_5m["ts"], utc=True)}).reset_index()
    right = df_1h_compact.copy()
    right["ts"] = pd.to_datetime(right["ts"], utc=True)
    merged = pd.merge_asof(
        left.sort_values("ts"),
        right.sort_values("ts"),
        on="ts",
        direction="backward",
    )
    merged = merged.set_index("index").sort_index()
    return merged["adx_1h"]


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "session_vwap_mean_reversion",
        "version": "1.0.0",
        "description": (
            "5m Session VWAP +/-2 sigma fade with 1h ADX<20 chop filter "
            "(HYP-2026-05-17-scalp-02, Shannon/Bollinger/Wilder)."
        ),
        "trend_filter": {"type": "none", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vwap_mr_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "sigma_window": 24,
                        "sigma_mult": 2.0,
                        "adx_threshold": 20.0,
                        "skip_first_n_bars": 12,
                    },
                },
                {
                    "id": "vwap_mr_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "sigma_window": 24,
                        "sigma_mult": 2.0,
                        "adx_threshold": 20.0,
                        "skip_first_n_bars": 12,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.001,  # 0.1% on 5m
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_mult": 1.0},
            "take_profit": {"method": "r_multiple", "tp_r": 1.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 50,
            "fees": {"taker": 0.00040, "maker": -0.00010},  # 4 bps RT one-side; 8 bps total
            "slippage_bps": 10.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class SessionVWAPMeanReversionStrategy(Strategy):
    """5m Session VWAP +/-2 sigma fade (mean-reversion in chop regime).

    Detection (per bar t):
      1. close[t] beyond vwap[t] +/- sigma_mult * sigma[t]
      2. adx_1h[t] < adx_threshold (chop regime, not trending)
      3. session bar count > skip_first_n_bars (VWAP stable)
      4. atr_pct > atr_min_pct (liquidity sanity)

    Entry: bar t close (engine fills t+1 open).
    SL: 1.0 * ATR_14 opposite direction.
    TP: min(VWAP retag, +1.0R) — engine handles dynamic VWAP via tp_price as 1R fixed.
        Note: pure-fixed TP here for engine compatibility; dynamic VWAP-touch
        exit modeled in standalone harness instead.
    """

    name = "session_vwap_mean_reversion"

    @property
    def _cfg(self) -> dict[str, Any]:
        for p in self.manifest.signals.patterns:
            return p.params
        return {}

    @property
    def _sigma_window(self) -> int:
        return int(self._cfg.get("sigma_window", 24))

    @property
    def _sigma_mult(self) -> float:
        return float(self._cfg.get("sigma_mult", 2.0))

    @property
    def _adx_threshold(self) -> float:
        return float(self._cfg.get("adx_threshold", 20.0))

    @property
    def _skip_first_n_bars(self) -> int:
        return int(self._cfg.get("skip_first_n_bars", 12))

    @property
    def _atr_sl_mult(self) -> float:
        return float(self.manifest.risk.get("stop_loss", {}).get("atr_mult", 1.0))

    @property
    def _tp_r(self) -> float:
        return float(self.manifest.risk.get("take_profit", {}).get("tp_r", 1.0))

    @property
    def _atr_min_pct(self) -> float:
        return float(getattr(self.manifest.signals.filters, "atr_min_pct", 0.001) or 0.001)

    # ----- prepare_features -----
    def prepare_features(self, df: pd.DataFrame, df_1h: pd.DataFrame | None = None) -> pd.DataFrame:
        """Compute session VWAP + sigma cone + ADX_1h merge.

        df_1h: optional pre-loaded 1h OHLCV for ADX merge. If None, ADX filter
        is skipped (warning); intended for standalone harness which loads 1h
        externally.
        """
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        df["session_vwap"] = _session_vwap(df)
        df["vwap_dev"] = df["close"] - df["session_vwap"]
        df["vwap_sigma"] = df["vwap_dev"].rolling(self._sigma_window,
                                                  min_periods=self._sigma_window).std(ddof=0)

        # Session bar count (each UTC date)
        ts = pd.to_datetime(df["ts"], utc=True)
        date_key = ts.dt.date
        df["session_bar_idx"] = pd.Series(range(len(df)), index=df.index).groupby(
            date_key.values
        ).cumcount()

        # ADX_1h merge
        if df_1h is not None and not df_1h.empty:
            df["adx_1h"] = _merge_adx_1h(df, df_1h).reindex(df.index)
        else:
            df["adx_1h"] = np.nan

        return df

    # ----- generate_signals -----
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "session_vwap" not in df.columns:
            df = self.prepare_features(df)

        required = ["session_vwap", "vwap_sigma", "atr14", "session_bar_idx"]
        for col in required:
            if col not in df.columns:
                return []

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "5m"

        sigma_mult = self._sigma_mult
        adx_th = self._adx_threshold
        skip_n = self._skip_first_n_bars
        atr_sl = self._atr_sl_mult
        tp_r = self._tp_r
        atr_min_pct = self._atr_min_pct

        out: list[Signal] = []
        for i in range(2, len(df) - 1):
            row = df.iloc[i]
            atr = float(row.get("atr14") or 0.0)
            close = float(row["close"])
            if atr <= 0 or np.isnan(atr) or close <= 0:
                continue
            if atr / close < atr_min_pct:
                continue

            vwap = float(row.get("session_vwap") or np.nan)
            sigma = float(row.get("vwap_sigma") or np.nan)
            if np.isnan(vwap) or np.isnan(sigma) or sigma <= 0:
                continue

            session_idx = int(row.get("session_bar_idx") or 0)
            if session_idx < skip_n:
                continue

            adx_1h = row.get("adx_1h", np.nan)
            adx_val = float(adx_1h) if not pd.isna(adx_1h) else np.nan
            if not np.isnan(adx_val) and adx_val >= adx_th:
                continue  # trending — skip

            upper = vwap + sigma_mult * sigma
            lower = vwap - sigma_mult * sigma

            # SHORT: fade upward stretch
            if close > upper:
                sl_price = close + atr_sl * atr
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - tp_r * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                conf = min(1.0, (close - upper) / (sigma_mult * sigma + 1e-9))
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short", pattern_id="vwap_mr_short",
                    confluence_score=1.0 + conf,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={"vwap": vwap, "sigma": sigma, "adx_1h": adx_val,
                              "session_idx": session_idx, "bar_idx": i,
                              "deviation_sigma": (close - vwap) / sigma},
                )
                out.append(sig)

            # LONG: fade downward stretch
            elif close < lower:
                sl_price = close - atr_sl * atr
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + tp_r * risk
                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                conf = min(1.0, (lower - close) / (sigma_mult * sigma + 1e-9))
                sig = self.emit_signal(
                    ts=ts, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="vwap_mr_long",
                    confluence_score=1.0 + conf,
                    sl_price=float(sl_price), tp_price=float(tp_price),
                    suggested_size_atr=atr_sl,
                    metadata={"vwap": vwap, "sigma": sigma, "adx_1h": adx_val,
                              "session_idx": session_idx, "bar_idx": i,
                              "deviation_sigma": (close - vwap) / sigma},
                )
                out.append(sig)

        return out


def build_strategy(overrides: dict[str, Any] | None = None) -> SessionVWAPMeanReversionStrategy:
    manifest = _default_manifest()
    if overrides:
        raw = manifest.model_dump()
        raw.update(overrides)
        manifest = StrategyManifest.model_validate(raw)
    return SessionVWAPMeanReversionStrategy(manifest)


__all__ = [
    "SessionVWAPMeanReversionStrategy",
    "build_strategy",
    "_default_manifest",
    "_session_vwap",
    "_adx_wilder",
    "_merge_adx_1h",
]
