"""Brooks Three-Push Wedge Fade — Mean-Reversion structural pattern.

Konsept (Al Brooks "Trading Price Action Reversals" Ch5 — Wedges and Three-Push
Reversal Patterns; Connors 3-consecutive close edge):
  - 3 ardisik swing-high (each within wedge angle, marjinal yukselis = exhaustion)
  - 3rd push'ta kucuk-govdeli rejection bar (upper-wick > 40%) -> SHORT
  - Mirror 3 descending swing-low + lower-wick rejection -> LONG

Bearish 3-Push (SHORT):
  - En son 3 confirmed pivot_high (5-bar fractal): PH3(oldest), PH2, PH1(newest)
  - Lookback window: 30 bar
  - Ascending sequence: PH1 > PH2 > PH3
  - Marjinal yukselis (climax char NOT impulse):
      (PH1-PH2)/PH2 in [0.005, 0.05]
      (PH2-PH3)/PH3 in [0.005, 0.05]
  - Wedge convergence proxy (top slope softening vs bottom rising):
      between PH3 and PH2 find pivot_low PL2, between PH2 and PH1 find PL1.
      Require PL1 > PL2 (rising lows = wedge bottom angle up).
  - 3rd-push trigger at bar t (within 3 bars after PH1):
      body_ratio < 0.40 (small body) AND upper_wick_ratio > 0.40 AND close < PH1.
  - ATR%(14) >= 0.5%
  - Cooldown 10 bar same side

Bullish 3-Push (LONG, mirror): 3 descending pivot_lows + descending pivot_highs
+ lower-wick rejection at/after PL1.

Targets:
  - SL: SHORT: high[t] + 0.5*ATR; LONG: low[t] - 0.5*ATR
  - TP1: PH3/PL3 (oldest push — Brooks "first target is start of pattern") partial 50%
  - TP2: 2.0R primary, partial 30%
  - Runner: 20%, engine default trail

Lookahead-free audit:
  - Pivot at bar i confirmed only after bar i+2 close (5-bar fractal n=2)
  - Bar t must be >= idx(PH1) + 2 (PH1 fully confirmed)
  - All pivot scans use bars [t-lookback, t-2] (always past+confirmed)
  - Entry t+1 open (decision_after_close=True)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy
STRATEGY_CLASS = "mean_reversion"


def _detect_pivots(highs: np.ndarray, lows: np.ndarray, n: int = 2):
    """5-bar fractal pivot detection (n=2 left + n=2 right + center).
    Returns (pivot_high_mask, pivot_low_mask) — both boolean arrays length len(highs).
    Pivot at bar i confirmed AT bar i+n (after right side closes). For lookahead-free
    use, only inspect pivots with idx <= t - n (sec22 audit).
    """
    L = len(highs)
    ph = np.zeros(L, dtype=bool)
    pl = np.zeros(L, dtype=bool)
    for i in range(n, L - n):
        if highs[i] >= highs[i - n:i + n + 1].max() and highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            ph[i] = True
        if lows[i] <= lows[i - n:i + n + 1].min() and lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            pl[i] = True
    return ph, pl


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "three_push_wedge_fade",
        "version": "1.0.0",
        "description": (
            "Brooks 3-push wedge reversal: 3 ascending/descending pivots with "
            "marginal gains, wedge convergence, 3rd-push exhaustion bar. Mean-rev fade."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "three_push_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "marginal_gain_min": 0.005,
                        "marginal_gain_max": 0.05,
                        "body_ratio_max": 0.40,
                        "wick_ratio_min": 0.40,
                        "max_bars_after_ph1": 3,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 10,
                    },
                },
                {
                    "id": "three_push_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_bars": 30,
                        "marginal_gain_min": 0.005,
                        "marginal_gain_max": 0.05,
                        "body_ratio_max": 0.40,
                        "wick_ratio_min": 0.40,
                        "max_bars_after_pl1": 3,
                        "sl_atr_mult": 0.5,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 10,
                    },
                },
            ],
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "take_profit": {"primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


class ThreePushWedgeFadeStrategy(Strategy):
    """Brooks 3-push wedge mean-reversion fade (LONG + SHORT)."""

    name = "three_push_wedge_fade"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = _ema(df["close"], 50)

        # Pivots (5-bar fractal n=2)
        ph, pl = _detect_pivots(df["high"].to_numpy(), df["low"].to_numpy(), n=2)
        df["pivot_high"] = ph
        df["pivot_low"] = pl

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "pivot_high" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        lookback = int(self._get_param("three_push_short", "lookback_bars", 30))
        mgain_min = float(self._get_param("three_push_short", "marginal_gain_min", 0.005))
        mgain_max = float(self._get_param("three_push_short", "marginal_gain_max", 0.05))
        body_max = float(self._get_param("three_push_short", "body_ratio_max", 0.40))
        wick_min = float(self._get_param("three_push_short", "wick_ratio_min", 0.40))
        max_after = int(self._get_param("three_push_short", "max_bars_after_ph1", 3))
        sl_mult = float(self._get_param("three_push_short", "sl_atr_mult", 0.5))
        tp_r = float(self._get_param("three_push_short", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("three_push_short", "cooldown_bars", 10))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "three_push_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "three_push_long"), 2.0)
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        atrs = df["atr14"].to_numpy(dtype=float)
        atr_pct = df["atr_pct"].to_numpy(dtype=float)
        ph_mask = df["pivot_high"].to_numpy(dtype=bool)
        pl_mask = df["pivot_low"].to_numpy(dtype=bool)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_long_ts = -99
        last_short_ts = -99
        FRACTAL_N = 2

        for t in range(lookback + FRACTAL_N + 5, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            # Only consider pivots confirmed up to bar t-FRACTAL_N
            scan_end = t - FRACTAL_N  # exclusive: bars [scan_start, scan_end)
            scan_start = max(0, t - lookback)
            if scan_end - scan_start < 7:
                continue

            # Bar body / wick characteristics at t
            rng_t = highs[t] - lows[t]
            if rng_t <= 0:
                continue
            body_t = abs(closes[t] - opens[t])
            body_ratio = body_t / rng_t
            upper_wick = (highs[t] - max(opens[t], closes[t])) / rng_t
            lower_wick = (min(opens[t], closes[t]) - lows[t]) / rng_t

            # ----- SHORT: 3 ascending pivot_highs + exhaustion bar -----
            if t > last_short_ts + cooldown:
                ph_indices = [i for i in range(scan_start, scan_end) if ph_mask[i]]
                if len(ph_indices) >= 3:
                    # Latest 3
                    ph1_idx = ph_indices[-1]
                    ph2_idx = ph_indices[-2]
                    ph3_idx = ph_indices[-3]
                    ph1 = highs[ph1_idx]
                    ph2 = highs[ph2_idx]
                    ph3 = highs[ph3_idx]
                    # Ascending
                    if ph1 > ph2 > ph3:
                        g1 = (ph1 - ph2) / ph2
                        g2 = (ph2 - ph3) / ph3
                        if (mgain_min <= g1 <= mgain_max and
                            mgain_min <= g2 <= mgain_max):
                            # Wedge bottom: pivot_lows between PH3-PH2 and PH2-PH1
                            pl_between_32 = [i for i in range(ph3_idx + 1, ph2_idx) if pl_mask[i]]
                            pl_between_21 = [i for i in range(ph2_idx + 1, ph1_idx) if pl_mask[i]]
                            if pl_between_32 and pl_between_21:
                                pl2_idx = pl_between_32[-1]
                                pl1_idx = pl_between_21[-1]
                                pl2 = lows[pl2_idx]
                                pl1 = lows[pl1_idx]
                                if pl1 > pl2:  # rising lows = wedge convergence proxy
                                    # 3rd-push trigger at bar t
                                    bars_after = t - ph1_idx
                                    if (0 <= bars_after <= max_after and
                                        body_ratio < body_max and
                                        upper_wick > wick_min and
                                        closes[t] < ph1):
                                        # Signal!
                                        sl_price = highs[t] + sl_mult * atr_t
                                        entry_ref = closes[t]
                                        risk = sl_price - entry_ref
                                        if risk > 0:
                                            tp_price = entry_ref - tp_r * risk
                                            score = short_w
                                            if score >= min_score:
                                                sig = self.emit_signal(
                                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                                    direction="short",
                                                    pattern_id="three_push_short",
                                                    confluence_score=float(score),
                                                    sl_price=float(sl_price),
                                                    tp_price=float(tp_price),
                                                    suggested_size_atr=1.0,
                                                    metadata={
                                                        "ph1": float(ph1), "ph2": float(ph2), "ph3": float(ph3),
                                                        "pl1": float(pl1), "pl2": float(pl2),
                                                        "g1": float(g1), "g2": float(g2),
                                                        "body_ratio": float(body_ratio),
                                                        "upper_wick": float(upper_wick),
                                                        "bars_after_ph1": int(bars_after),
                                                        "ph3_target": float(ph3),
                                                    },
                                                )
                                                out.append(sig)
                                                last_short_ts = t

            # ----- LONG: 3 descending pivot_lows + exhaustion bar (mirror) -----
            if t > last_long_ts + cooldown:
                pl_indices = [i for i in range(scan_start, scan_end) if pl_mask[i]]
                if len(pl_indices) >= 3:
                    pl1_idx = pl_indices[-1]
                    pl2_idx = pl_indices[-2]
                    pl3_idx = pl_indices[-3]
                    pl1v = lows[pl1_idx]
                    pl2v = lows[pl2_idx]
                    pl3v = lows[pl3_idx]
                    # Descending
                    if pl1v < pl2v < pl3v:
                        g1 = (pl2v - pl1v) / pl2v
                        g2 = (pl3v - pl2v) / pl3v
                        if (mgain_min <= g1 <= mgain_max and
                            mgain_min <= g2 <= mgain_max):
                            ph_between_32 = [i for i in range(pl3_idx + 1, pl2_idx) if ph_mask[i]]
                            ph_between_21 = [i for i in range(pl2_idx + 1, pl1_idx) if ph_mask[i]]
                            if ph_between_32 and ph_between_21:
                                ph2_idx = ph_between_32[-1]
                                ph1_idx = ph_between_21[-1]
                                ph2v = highs[ph2_idx]
                                ph1v = highs[ph1_idx]
                                if ph1v < ph2v:  # falling highs = wedge convergence proxy
                                    bars_after = t - pl1_idx
                                    if (0 <= bars_after <= max_after and
                                        body_ratio < body_max and
                                        lower_wick > wick_min and
                                        closes[t] > pl1v):
                                        sl_price = lows[t] - sl_mult * atr_t
                                        entry_ref = closes[t]
                                        risk = entry_ref - sl_price
                                        if risk > 0:
                                            tp_price = entry_ref + tp_r * risk
                                            score = long_w
                                            if score >= min_score:
                                                sig = self.emit_signal(
                                                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                                                    venue=venue, symbol=symbol, timeframe=timeframe,
                                                    direction="long",
                                                    pattern_id="three_push_long",
                                                    confluence_score=float(score),
                                                    sl_price=float(sl_price),
                                                    tp_price=float(tp_price),
                                                    suggested_size_atr=1.0,
                                                    metadata={
                                                        "pl1": float(pl1v), "pl2": float(pl2v), "pl3": float(pl3v),
                                                        "ph1": float(ph1v), "ph2": float(ph2v),
                                                        "g1": float(g1), "g2": float(g2),
                                                        "body_ratio": float(body_ratio),
                                                        "lower_wick": float(lower_wick),
                                                        "bars_after_pl1": int(bars_after),
                                                        "pl3_target": float(pl3v),
                                                    },
                                                )
                                                out.append(sig)
                                                last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("three_push_wedge_fade.signals.generated")
        return out
