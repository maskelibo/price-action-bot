"""Quasimodo (QM) Reversal — 5-pivot Over-and-Under reversal pattern.

Konsept:
  Bearish QM (SHORT):
    Pivot zinciri (zaman geçmişten yakına): p4=LL_old, p3=LH_old, p2=HH_new (HEAD),
    p1=LL_recent (HEAD sonrası dip).
    Koşullar:
      - p3.high > p4.high   (uptrend baz: LL→LH)
      - p2.high > p3.high   (HEAD yeni HH yaptı — stop-run / liquidity grab)
      - p1.low  < p3.low    (HEAD sonrası p3 (önceki LH) altına indi — yapısal kırılım)
    Tetik bar t:
      - close[t] < p2.high AND close[t] < p3.high (LH retest zone)
      - bear confirmation: bearish engulf bar (close<open, body > prev body) OR
        bearish pin (upper wick > 2 * body)
    Exit:
      - SL: p2.high + 0.25 * ATR(14)
      - TP1: p1.low (yapısal target) — partial 50%
      - TP2: 2.0R — partial 30%
      - Runner 20%, trail engine default

  Bullish QM (LONG, mirror): p4=HH_old, p3=HL_old, p2=LL_new (HEAD), p1=HH_recent.

Filtreler:
  - ATR%(14) >= 0.5
  - p4 ile t arasi 10-80 bar
  - Cooldown same side 10 bar

Lookahead-free:
  - Pivot detection fractal_n=2 — pivot bar i confirmed at i+n
  - At bar t, only pivots at index <= t-n_fractal are usable
  - Trigger bar t close; entry t+1 open (engine default)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema, _fractal_swings


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "quasimodo_reversal",
        "version": "1.0.0",
        "description": (
            "Quasimodo 5-pivot Over-and-Under reversal. "
            "Bearish: LL-LH-HH(head)-LL(recent) + LH retest. Mirror long."
        ),
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "qm_bear_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "fractal_n": 2,
                        "pivot_window_min": 10,
                        "pivot_window_max": 80,
                        "sl_atr_mult_above_head": 0.25,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 10,
                        "bear_confirm_pin_wick_ratio": 2.0,
                    },
                },
                {
                    "id": "qm_bull_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "fractal_n": 2,
                        "pivot_window_min": 10,
                        "pivot_window_max": 80,
                        "sl_atr_mult_below_head": 0.25,
                        "tp_r_multiple": 2.0,
                        "cooldown_bars": 10,
                        "bull_confirm_pin_wick_ratio": 2.0,
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


class QuasimodoReversalStrategy(Strategy):
    """Quasimodo 5-pivot reversal."""

    name = "quasimodo_reversal"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        df["ema50"] = _ema(df["close"], 50)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        n_fractal = int(self._get_param("qm_bear_short", "fractal_n", 2))
        sh, sl = _fractal_swings(df, n=n_fractal)
        df["swing_high_flag"] = sh
        df["swing_low_flag"] = sl

        # Volume z (60-bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "swing_high_flag" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        n_fractal = int(self._get_param("qm_bear_short", "fractal_n", 2))
        pivot_win_min = int(self._get_param("qm_bear_short", "pivot_window_min", 10))
        pivot_win_max = int(self._get_param("qm_bear_short", "pivot_window_max", 80))
        sl_mult = float(self._get_param("qm_bear_short", "sl_atr_mult_above_head", 0.25))
        tp_r = float(self._get_param("qm_bear_short", "tp_r_multiple", 2.0))
        cooldown = int(self._get_param("qm_bear_short", "cooldown_bars", 10))
        pin_wick_ratio = float(self._get_param("qm_bear_short", "bear_confirm_pin_wick_ratio", 2.0))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "qm_bear_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "qm_bull_long"), 2.0)

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
        sh_flag = df["swing_high_flag"].to_numpy(dtype=bool)
        sl_flag = df["swing_low_flag"].to_numpy(dtype=bool)
        ts_arr = df["ts"].to_numpy()
        n = len(df)

        out: list[Signal] = []
        last_short_ts = -99
        last_long_ts = -99

        def _bear_confirm(t_idx: int) -> bool:
            """Bearish confirmation: engulf veya pin (upper wick >= ratio * body)."""
            body = closes[t_idx] - opens[t_idx]  # negative if bearish
            bar_range = highs[t_idx] - lows[t_idx]
            if bar_range <= 0:
                return False
            # Bearish engulf: close < open AND body magnitude > 1.0 * prev body magnitude (relative)
            if body < 0:
                prev_body = abs(closes[t_idx - 1] - opens[t_idx - 1])
                if abs(body) > prev_body and abs(body) > 0.3 * bar_range:
                    return True
            # Bearish pin: upper wick >= ratio * |body|, close near low
            upper_wick = highs[t_idx] - max(opens[t_idx], closes[t_idx])
            body_abs = max(abs(body), bar_range * 0.05)  # avoid div-by-zero
            if upper_wick >= pin_wick_ratio * body_abs and closes[t_idx] < (highs[t_idx] + lows[t_idx]) / 2:
                return True
            return False

        def _bull_confirm(t_idx: int) -> bool:
            body = closes[t_idx] - opens[t_idx]
            bar_range = highs[t_idx] - lows[t_idx]
            if bar_range <= 0:
                return False
            if body > 0:
                prev_body = abs(closes[t_idx - 1] - opens[t_idx - 1])
                if body > prev_body and body > 0.3 * bar_range:
                    return True
            lower_wick = min(opens[t_idx], closes[t_idx]) - lows[t_idx]
            body_abs = max(abs(body), bar_range * 0.05)
            if lower_wick >= pin_wick_ratio * body_abs and closes[t_idx] > (highs[t_idx] + lows[t_idx]) / 2:
                return True
            return False

        # Need at least pivot_win_max + n_fractal bars; iterate t
        for t in range(pivot_win_min + n_fractal + 1, n):
            atr_t = atrs[t]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and not np.isnan(atr_pct[t]) and atr_pct[t] < atr_min_pct:
                continue

            # Confirmed pivots: indices <= t - n_fractal
            confirmed_end = t - n_fractal  # exclusive
            window_start = max(0, t - pivot_win_max)

            # ----- BEARISH QM (SHORT) -----
            if t > last_short_ts + cooldown:
                # Collect pivot indices in window [window_start, confirmed_end)
                # We need 4 pivots in alternating order: low (p4), high (p3), high (p2=head), low (p1)
                # Walk backwards from confirmed_end-1
                # Find p1 = most recent confirmed swing low (closest to t, but not too close)
                p1_idx = -1
                for i in range(confirmed_end - 1, window_start - 1, -1):
                    if sl_flag[i] and (t - i) >= pivot_win_min // 2:
                        p1_idx = i
                        break
                if p1_idx < 0:
                    pass
                else:
                    # Find p2 (head = swing high before p1)
                    p2_idx = -1
                    for i in range(p1_idx - 1, window_start - 1, -1):
                        if sh_flag[i]:
                            p2_idx = i
                            break
                    if p2_idx < 0:
                        pass
                    else:
                        # Find p3 (LH_old = swing high before p2 — but lower than p2)
                        p3_idx = -1
                        for i in range(p2_idx - 1, window_start - 1, -1):
                            if sh_flag[i] and highs[i] < highs[p2_idx]:
                                p3_idx = i
                                break
                        if p3_idx < 0:
                            pass
                        else:
                            # Find p4 (LL_old = swing low before p3 — but lower than p1)
                            p4_idx = -1
                            for i in range(p3_idx - 1, window_start - 1, -1):
                                if sl_flag[i] and lows[i] < highs[p3_idx]:
                                    p4_idx = i
                                    break
                            if p4_idx < 0:
                                pass
                            else:
                                # Validate QM bearish structure
                                p4_low = lows[p4_idx]
                                p3_high = highs[p3_idx]
                                p2_high = highs[p2_idx]
                                p1_low = lows[p1_idx]
                                # Structural pivot window range
                                age_bars = t - p4_idx
                                if (age_bars >= pivot_win_min and age_bars <= pivot_win_max
                                    and p3_high > p4_low  # baseline uptrend (LL->LH)
                                    and p2_high > p3_high  # HEAD new HH (stop-run)
                                    and p1_low < lows[p3_idx]  # post-head pull < prev LH_low (structural break)
                                    and closes[t] < p2_high
                                    and closes[t] < p3_high
                                    and _bear_confirm(t)):
                                    # Signal
                                    sl_price = p2_high + sl_mult * atr_t
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
                                                pattern_id="qm_bear_short",
                                                confluence_score=float(score),
                                                sl_price=float(sl_price),
                                                tp_price=float(tp_price),
                                                suggested_size_atr=1.0,
                                                metadata={
                                                    "p4_low": float(p4_low),
                                                    "p3_high": float(p3_high),
                                                    "p2_high_head": float(p2_high),
                                                    "p1_low_recent": float(p1_low),
                                                    "pivot_age": int(age_bars),
                                                    "structural_target_p1_low": float(p1_low),
                                                },
                                            )
                                            out.append(sig)
                                            last_short_ts = t

            # ----- BULLISH QM (LONG, mirror) -----
            if t > last_long_ts + cooldown:
                p1_idx = -1
                for i in range(confirmed_end - 1, window_start - 1, -1):
                    if sh_flag[i] and (t - i) >= pivot_win_min // 2:
                        p1_idx = i
                        break
                if p1_idx < 0:
                    continue
                p2_idx = -1
                for i in range(p1_idx - 1, window_start - 1, -1):
                    if sl_flag[i]:
                        p2_idx = i
                        break
                if p2_idx < 0:
                    continue
                p3_idx = -1
                for i in range(p2_idx - 1, window_start - 1, -1):
                    if sl_flag[i] and lows[i] > lows[p2_idx]:
                        p3_idx = i
                        break
                if p3_idx < 0:
                    continue
                p4_idx = -1
                for i in range(p3_idx - 1, window_start - 1, -1):
                    if sh_flag[i] and highs[i] > lows[p3_idx]:
                        p4_idx = i
                        break
                if p4_idx < 0:
                    continue
                p4_high = highs[p4_idx]
                p3_low = lows[p3_idx]
                p2_low = lows[p2_idx]
                p1_high = highs[p1_idx]
                age_bars = t - p4_idx
                if (age_bars >= pivot_win_min and age_bars <= pivot_win_max
                    and p3_low < p4_high
                    and p2_low < p3_low  # HEAD new LL (sweep)
                    and p1_high > highs[p3_idx]  # post-head bounce > prev HL_high
                    and closes[t] > p2_low
                    and closes[t] > p3_low
                    and _bull_confirm(t)):
                    sl_price = p2_low - sl_mult * atr_t
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
                                pattern_id="qm_bull_long",
                                confluence_score=float(score),
                                sl_price=float(sl_price),
                                tp_price=float(tp_price),
                                suggested_size_atr=1.0,
                                metadata={
                                    "p4_high": float(p4_high),
                                    "p3_low": float(p3_low),
                                    "p2_low_head": float(p2_low),
                                    "p1_high_recent": float(p1_high),
                                    "pivot_age": int(age_bars),
                                    "structural_target_p1_high": float(p1_high),
                                },
                            )
                            out.append(sig)
                            last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("quasimodo_reversal.signals.generated")
        return out
