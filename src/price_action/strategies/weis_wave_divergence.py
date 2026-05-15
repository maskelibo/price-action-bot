"""Weis Wave Volume Divergence — reversal strategy.

Referans: `knowledge/books/vsa_volume_spread_analysis.md` §5.5
          `knowledge/books/volume_price_divergence.md` §1 (çok-bar mantığı)
Pre-reg : `memory/researcher/hypotheses/2026-05-14-vol-d4-weis-wave-divergence.md`

Konsept (David Weis, Wyckoff student):
  Wave = ardışık eş-yönlü kapanış barları (close[t] > close[t-1] → UP wave,
  close[t] < close[t-1] → DOWN wave). Bir wave'in toplam hacmi (sum of volumes)
  o wave'in "kümülatif çabası"dır. Weis: iki ardışık eş-yönlü dalga karşılaştırılır.
  Eğer yeni dalga price-extension yapıyor (HH veya LL) ama toplam hacim önceki
  dalganın daha azı ise → divergence, reversal habercisi.

Mekanik kurallar (lookahead-free):

Wave aggregation (causal):
  - wave_dir[t] = +1 if close[t] > close[t-1]
                  -1 if close[t] < close[t-1]
                   0 if close[t] == close[t-1] (flat — wave devamı sayılır)
  - Consecutive same-sign bars grouped into one wave.
  - Each wave: start_idx, end_idx, dir, n_bars, total_volume, wave_high, wave_low

SHORT setup (bearish wave divergence at top):
  - Find two consecutive UP waves W1 (older) and W2 (newer, ending at bar T)
  - wave_high(W2) > wave_high(W1)  — price HH
  - total_volume(W2) < vol_ratio_max × total_volume(W1)
  - n_bars(W1) ≥ min_wave_bars AND n_bars(W2) ≥ min_wave_bars
  - W1 ended at most 30 bars before T
  - Confirmation bar T+1: close[T+1] < close[T] (bearish)
  - Cooldown 10 bar same direction

LONG setup (bullish wave divergence at bottom): mirror with DOWN waves.

Entry: bar T+1 close → engine T+2 open.
SL (SHORT): wave_high(W2) + 0.50 × ATR(20)[T-1]
SL (LONG):  wave_low(W2) - 0.50 × ATR(20)[T-1]
TP: 2R primary.

Lookahead audit:
  - Wave ID assigned from cumulative sign-change count — pure causal
  - W1, W2 selection at bar T uses only bars ≤ T (wave T may or may not be
    "complete" — strategy treats current wave as still-running)
  - Signal EMIT on T+1 close; engine fills T+2 open
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# Engineering SEC21 taxonomy hook
STRATEGY_CLASS = "mean_reversion"


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "weis_wave_divergence",
        "version": "1.0.0",
        "description": (
            "Weis Wave Volume Divergence: two consecutive same-direction waves "
            "with price extension but lower aggregate volume -> reversal fade."
        ),
        "trend_filter": {"type": "none", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "weis_wave_div_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "atr_window": 20,
                        "vol_ratio_max": 0.70,    # vol(W2) < 0.70 * vol(W1)
                        "min_wave_bars": 2,
                        "max_wave_distance": 30,
                        "sl_atr_mult": 0.50,
                        "tp_r_multiple": 2.0,
                        "atr_min_pct": 0.005,
                        "cooldown_bars": 10,
                    },
                },
                {
                    "id": "weis_wave_div_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "atr_window": 20,
                        "vol_ratio_max": 0.70,
                        "min_wave_bars": 2,
                        "max_wave_distance": 30,
                        "sl_atr_mult": 0.50,
                        "tp_r_multiple": 2.0,
                        "atr_min_pct": 0.005,
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


def _wave_ids(closes: np.ndarray) -> np.ndarray:
    """Assign wave-id to each bar (lookahead-free).

    Wave-id is monotonically increasing integer; each wave-id corresponds to a
    maximal run of consecutive same-direction bars.

    Direction:
      +1 if close[t] > close[t-1]
      -1 if close[t] < close[t-1]
       0 if close[t] == close[t-1] (continues the current wave)

    Bar 0: no prior — assigned wave_id=0, dir=0.
    Bar 1: first directional bar → wave_id=1 (or 0 if flat).

    Returns array of wave_id (int) parallel to closes.
    """
    n = len(closes)
    wave_id = np.zeros(n, dtype=np.int64)
    if n == 0:
        return wave_id
    cur_id = 0
    cur_dir = 0
    for t in range(1, n):
        if closes[t] > closes[t - 1]:
            new_dir = 1
        elif closes[t] < closes[t - 1]:
            new_dir = -1
        else:
            new_dir = cur_dir  # flat: continue current wave
        # New wave starts on direction change (ignoring flat ↔ same dir)
        if new_dir != 0 and cur_dir != 0 and new_dir != cur_dir:
            cur_id += 1
        elif new_dir != 0 and cur_dir == 0:
            cur_id += 1
            cur_dir = new_dir
        if new_dir != 0:
            cur_dir = new_dir
        wave_id[t] = cur_id
    return wave_id


def _aggregate_waves(
    wave_id: np.ndarray,
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    vols: np.ndarray,
) -> list[dict]:
    """Aggregate per-wave stats. Each wave: id, dir, start, end, n_bars, vol_sum, high, low.

    Lookahead-free for use: when caller wants stats up to bar T, must slice
    waves where wave.end_idx <= T.
    """
    n = len(closes)
    waves: list[dict] = []
    if n == 0:
        return waves
    cur = None
    for t in range(n):
        wid = int(wave_id[t])
        if wid == 0:
            continue  # pre-direction bars
        if cur is None or cur["id"] != wid:
            if cur is not None:
                waves.append(cur)
            # Determine direction: compare close[t] with close[t-1] (first bar of new wave)
            if t > 0:
                if closes[t] > closes[t - 1]:
                    d = 1
                elif closes[t] < closes[t - 1]:
                    d = -1
                else:
                    d = 0
            else:
                d = 0
            cur = {
                "id": wid,
                "dir": d,
                "start": t,
                "end": t,
                "n_bars": 1,
                "vol_sum": float(vols[t]),
                "high": float(highs[t]),
                "low": float(lows[t]),
            }
        else:
            cur["end"] = t
            cur["n_bars"] += 1
            cur["vol_sum"] += float(vols[t])
            if highs[t] > cur["high"]:
                cur["high"] = float(highs[t])
            if lows[t] < cur["low"]:
                cur["low"] = float(lows[t])
    if cur is not None:
        waves.append(cur)
    return waves


class WeisWaveDivergenceStrategy(Strategy):
    """Weis Wave Volume Divergence reversal strategy (both long & short)."""

    name = "weis_wave_divergence"

    def _get_param(self, pattern_id: str, key: str, default: Any) -> Any:
        for p in self.manifest.signals.patterns:
            if p.id == pattern_id:
                return p.params.get(key, default)
        return default

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        atr_win = int(self._get_param("weis_wave_div_short", "atr_window", 20))
        df["atr20"] = _atr(df, atr_win)
        df["atr20_lag1"] = df["atr20"].shift(1)
        df["atr_pct_lag1"] = (df["atr20"].shift(1) / df["close"].shift(1)).replace(0, np.nan)
        df["ema50"] = _ema(df["close"], 50)
        df["wave_id"] = _wave_ids(df["close"].to_numpy(dtype=float))
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr20_lag1" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        min_score = float(signals_cfg.confluence.min_score)

        vol_ratio_max = float(self._get_param("weis_wave_div_short", "vol_ratio_max", 0.70))
        min_wave_bars = int(self._get_param("weis_wave_div_short", "min_wave_bars", 2))
        max_wave_dist = int(self._get_param("weis_wave_div_short", "max_wave_distance", 30))
        sl_mult = float(self._get_param("weis_wave_div_short", "sl_atr_mult", 0.50))
        tp_r = float(self._get_param("weis_wave_div_short", "tp_r_multiple", 2.0))
        atr_min_pct = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        cooldown = int(self._get_param("weis_wave_div_short", "cooldown_bars", 10))

        short_w = next((p.weight for p in signals_cfg.patterns if p.id == "weis_wave_div_short"), 2.0)
        long_w = next((p.weight for p in signals_cfg.patterns if p.id == "weis_wave_div_long"), 2.0)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        vols = df["volume"].to_numpy(dtype=float)
        atr_lag = df["atr20_lag1"].to_numpy(dtype=float)
        atr_pct_lag = df["atr_pct_lag1"].to_numpy(dtype=float)
        wave_id_arr = df["wave_id"].to_numpy(dtype=np.int64)
        ts_arr = df["ts"].to_numpy()
        n_bars = len(df)

        # Aggregate waves ONCE (causal: each wave stat is built using only bars within wave)
        waves = _aggregate_waves(wave_id_arr, closes, highs, lows, vols)
        if len(waves) < 2:
            return []

        # Build map: end_idx -> wave_index (for quick lookup)
        # And wave_index_by_id for sibling lookup
        wave_by_end = {w["end"]: i for i, w in enumerate(waves)}

        out: list[Signal] = []
        last_short_ts = -99
        last_long_ts = -99

        start_idx = max(25, 20 + 5)

        # We need bar T (last bar of W2) and bar T+1 (confirmation).
        # Loop t = T+1 (confirmation bar).
        for t in range(start_idx, n_bars):
            T = t - 1
            if T < start_idx - 1:
                continue
            atr_t = atr_lag[T]
            if np.isnan(atr_t) or atr_t <= 0:
                continue
            if atr_min_pct > 0 and (np.isnan(atr_pct_lag[T]) or atr_pct_lag[T] < atr_min_pct):
                continue

            # Check if bar T is the LAST bar of its wave (i.e., wave is "complete" at T)
            # We do not strictly require wave-completion — we check W2 ends at T or earlier.
            # Pragmatic: find the wave that ENDS at bar T (or skip).
            if T not in wave_by_end:
                continue
            w2_idx = wave_by_end[T]
            if w2_idx == 0:
                continue
            w2 = waves[w2_idx]
            w1 = waves[w2_idx - 1]

            # Both waves must have same direction (consecutive same-dir wave pair)
            # NOTE: waves are alternating-dir by construction (UP/DOWN/UP/DOWN). Two
            # consecutive same-dir waves don't exist directly; the "swing" of interest
            # is: latest UP wave (W2) vs PREVIOUS UP wave (W1 = waves[idx-2]).
            # Re-locate W1 = previous same-dir wave.
            if w2_idx < 2:
                continue
            w1 = waves[w2_idx - 2]
            if w1["dir"] != w2["dir"] or w2["dir"] == 0:
                continue

            # Wave size constraints
            if w1["n_bars"] < min_wave_bars or w2["n_bars"] < min_wave_bars:
                continue
            # Distance: W1 ended within max_wave_dist of W2.end
            if (w2["end"] - w1["end"]) > max_wave_dist:
                continue
            # Volume divergence
            if w1["vol_sum"] <= 0:
                continue
            vol_ratio = w2["vol_sum"] / w1["vol_sum"]
            if vol_ratio >= vol_ratio_max:
                continue

            # Cooldown
            if w2["dir"] == 1:  # UP waves — bearish divergence → SHORT
                if t <= last_short_ts + cooldown:
                    continue
            else:  # DOWN waves — bullish divergence → LONG
                if t <= last_long_ts + cooldown:
                    continue

            # --- BEARISH SHORT setup (UP waves) ---
            if w2["dir"] == 1:
                # Price extension: W2 high > W1 high
                if w2["high"] <= w1["high"]:
                    continue
                # Confirmation: T+1 close < T close
                if closes[t] >= closes[T]:
                    continue

                sl_price = w2["high"] + sl_mult * atr_t
                entry_ref = closes[t]
                risk = sl_price - entry_ref
                if risk <= 0:
                    continue
                tp_price = entry_ref - tp_r * risk
                score = short_w
                if score < min_score:
                    continue

                sig = self.emit_signal(
                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                    venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short",
                    pattern_id="weis_wave_div_short",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "w1_bars": int(w1["n_bars"]),
                        "w2_bars": int(w2["n_bars"]),
                        "w1_vol": float(w1["vol_sum"]),
                        "w2_vol": float(w2["vol_sum"]),
                        "vol_ratio": float(vol_ratio),
                        "w1_high": float(w1["high"]),
                        "w2_high": float(w2["high"]),
                        "price_extension_atr": float((w2["high"] - w1["high"]) / atr_t) if atr_t > 0 else None,
                        "wave_distance_bars": int(w2["end"] - w1["end"]),
                        "atr20": float(atr_t),
                    },
                )
                out.append(sig)
                last_short_ts = t

            # --- BULLISH LONG setup (DOWN waves) ---
            elif w2["dir"] == -1:
                # Price extension: W2 low < W1 low
                if w2["low"] >= w1["low"]:
                    continue
                # Confirmation: T+1 close > T close
                if closes[t] <= closes[T]:
                    continue

                sl_price = w2["low"] - sl_mult * atr_t
                entry_ref = closes[t]
                risk = entry_ref - sl_price
                if risk <= 0:
                    continue
                tp_price = entry_ref + tp_r * risk
                score = long_w
                if score < min_score:
                    continue

                sig = self.emit_signal(
                    ts=pd.Timestamp(ts_arr[t]).to_pydatetime(),
                    venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long",
                    pattern_id="weis_wave_div_long",
                    confluence_score=float(score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "w1_bars": int(w1["n_bars"]),
                        "w2_bars": int(w2["n_bars"]),
                        "w1_vol": float(w1["vol_sum"]),
                        "w2_vol": float(w2["vol_sum"]),
                        "vol_ratio": float(vol_ratio),
                        "w1_low": float(w1["low"]),
                        "w2_low": float(w2["low"]),
                        "price_extension_atr": float((w1["low"] - w2["low"]) / atr_t) if atr_t > 0 else None,
                        "wave_distance_bars": int(w2["end"] - w1["end"]),
                        "atr20": float(atr_t),
                    },
                )
                out.append(sig)
                last_long_ts = t

        self._log.bind(n=len(out), bars=len(df)).info("weis_wave_divergence.signals.generated")
        return out
