"""Pin Bar at Round Numbers stratejisi.

Concept (Volman): Round number'lar (BTC 10K aralıklar, ETH 500, SOL 50)
kurumsal limit emirlerin toplandığı manyetik seviyelerdir. Bu seviyelerde
oluşan pin bar'lar yüksek conviction reversal sinyali verir.

Kural özeti:
  - Round numbers: sembol bazlı sabit grid (BTC 10K, ETH 500, SOL 50 aralıklar)
  - Pin bar  : gövde ≤ %33 range, dominant wick ≥ %60 range
  - Proximity: pin bar high (bearish) veya low (bullish) round number'a
               ≤ 0.3 ATR yakınlıkta
  - Entry    : pin bar kapanışından bir sonraki bar açılışı (reversal yönünde)
  - SL       : pin bar tail ucu + 0.5 ATR
  - TP       : 2R (SL mesafesinin 2 katı)
  - Filtreler: ATR min pct, volume z-score, trend konfirmasyonu (opsiyonel)

Lookahead: Kesinlikle yok — tüm sinyaller bar N kapanışına göre üretilir,
           giriş N+1 açılışı simüle eder (entry_price = close bar N).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _rolling_sharpe,
    _sr_levels,
)


# =====================================================================
# Round number grid
# =====================================================================

# Symbol bazlı round number aralıkları (USDT fiyat cinsinden)
_DEFAULT_ROUND_GRIDS: dict[str, float] = {
    "BTC":  10_000.0,
    "ETH":  500.0,
    "SOL":  50.0,
    "BNB":  50.0,
    "XRP":  0.5,
    "ADA":  0.1,
    "DOGE": 0.05,
    "LTC":  10.0,
    "AVAX": 10.0,
    "MATIC": 0.5,
    "DOT":  1.0,
    "LINK": 5.0,
    "UNI":  1.0,
    "ATOM": 5.0,
}

_FALLBACK_GRID = 1.0  # bilinmeyen semboller için


def _symbol_base(symbol: str) -> str:
    """'BTC/USDT' → 'BTC', 'ETHUSDT' → 'ETH' vb."""
    s = symbol.upper().replace("-", "/")
    if "/" in s:
        return s.split("/")[0]
    # Quote currency'leri kırp
    for q in ("USDT", "USDC", "BUSD", "BTC", "ETH", "USD", "EUR"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def get_round_grid(symbol: str, override: float | None = None) -> float:
    """Sembol için round number grid aralığını döndür."""
    if override and override > 0:
        return override
    base = _symbol_base(symbol)
    return _DEFAULT_ROUND_GRIDS.get(base, _FALLBACK_GRID)


def nearest_round_levels(price: float, grid: float, n: int = 3) -> list[float]:
    """Fiyata en yakın n round number seviyesini döndür."""
    base = round(price / grid) * grid
    return [base + i * grid for i in range(-n, n + 1)]


def distance_to_nearest_round(price: float, grid: float) -> float:
    """Fiyatın en yakın round number'a mutlak mesafesi."""
    nearest = round(price / grid) * grid
    return abs(price - nearest)


# =====================================================================
# Pin bar detection
# =====================================================================

def _pin_bar_flags(
    df: pd.DataFrame,
    body_ratio_max: float = 0.33,
    wick_ratio_min: float = 0.60,
) -> tuple[pd.Series, pd.Series]:
    """Bullish ve bearish pin bar flagleri üret.

    Bullish pin bar: uzun alt wick (hammer)
      - body ≤ body_ratio_max * range
      - alt wick ≥ wick_ratio_min * range
      - kapanış üst yarıda (close > midpoint)

    Bearish pin bar: uzun üst wick (shooting star)
      - body ≤ body_ratio_max * range
      - üst wick ≥ wick_ratio_min * range
      - kapanış alt yarıda (close < midpoint)

    Lookahead-free: tek bar, dış veri yok.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    total_range = (h - l).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / total_range

    body_top = np.maximum(o, c)
    body_bot = np.minimum(o, c)
    upper_wick = h - body_top
    lower_wick = body_bot - l
    midpoint = (h + l) / 2.0

    upper_wick_ratio = upper_wick / total_range
    lower_wick_ratio = lower_wick / total_range

    body_ok = body_ratio <= body_ratio_max

    # Bullish (hammer): long lower wick, close above midpoint
    bull_pin = (
        body_ok
        & (lower_wick_ratio >= wick_ratio_min)
        & (c >= midpoint)
    )

    # Bearish (shooting star): long upper wick, close below midpoint
    bear_pin = (
        body_ok
        & (upper_wick_ratio >= wick_ratio_min)
        & (c <= midpoint)
    )

    return bull_pin.fillna(False), bear_pin.fillna(False)


# =====================================================================
# Round number proximity
# =====================================================================

def _round_proximity_flags(
    df: pd.DataFrame,
    grid: float,
    atr_factor: float = 0.3,
) -> tuple[pd.Series, pd.Series]:
    """Bullish: pin low, round number'a yakın.
       Bearish: pin high, round number'a yakın.

    Yakınlık kriteri: mesafe ≤ atr_factor * ATR14.
    Lookahead-free: aynı bar verileri kullanılır.
    """
    atr = df["atr14"].fillna(0.0)
    tolerance = atr_factor * atr

    # Bullish: bar low ≈ round number
    low_dist = df["low"].apply(lambda x: distance_to_nearest_round(x, grid))
    # Bearish: bar high ≈ round number
    high_dist = df["high"].apply(lambda x: distance_to_nearest_round(x, grid))

    bull_near = low_dist <= tolerance
    bear_near = high_dist <= tolerance

    return bull_near.fillna(False), bear_near.fillna(False)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw: dict[str, Any] = {
        "name": "pin_bar_round_numbers",
        "version": "1.0.0",
        "description": (
            "Pin bar at round number levels — Volman institutional magnet reversal. "
            "High conviction, rare signals."
        ),
        "trend_filter": {
            "type": "ema",
            "period": 50,
            "required": False,  # round number reversal trend-bağımsız çalışır
        },
        "signals": {
            "patterns": [
                {
                    "id": "bullish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "wick_ratio_min": 0.60,
                        "round_proximity_atr": 0.3,
                    },
                },
                {
                    "id": "bearish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "wick_ratio_min": 0.60,
                        "round_proximity_atr": 0.3,
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
                "require_proximity_to_sr_atr": 0.0,  # round number bizzat filtre
            },
            "filters": {
                "atr_min_pct": 0.003,  # min volatilite
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,
                "bear_regime_size_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "pin_tail", "tail_atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 200,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class PinBarRoundNumbersStrategy(Strategy):
    """Pin bar at round number levels — Volman institutional reversal.

    Pattern (mechanical):
      1. Pin bar: body ≤ 33% range, dominant wick ≥ 60% range
      2. Pin bar low (bullish) or high (bearish) ≤ 0.3 ATR to nearest round number
      3. Entry: next bar open (reversal direction)
      4. SL: pin tail extremity + 0.5 ATR buffer
      5. TP: 2R

    Round number grids (symbol-specific):
      BTC: 10 000, ETH: 500, SOL: 50, others: auto from _DEFAULT_ROUND_GRIDS
    """

    name = "pin_bar_round_numbers"

    def __init__(
        self,
        manifest: StrategyManifest,
        round_grid_override: float | None = None,
    ) -> None:
        super().__init__(manifest)
        self._round_grid_override = round_grid_override

    # ------------------------------------------------------------------
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        grid = get_round_grid(symbol, self._round_grid_override)

        # EMAs
        df["ema20"]  = _ema(df["close"], 20)
        df["ema50"]  = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"]    = _atr(df, 14)
        df["atr_pct"]  = df["atr14"] / df["close"]

        # Volume z-score
        vol   = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd  = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Pin bar flags (lookahead-free: per-bar calculation)
        params = {}
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_pin_at_round", "bearish_pin_at_round"):
                params = p.params
                break
        body_ratio_max = float(params.get("body_ratio_max", 0.33))
        wick_ratio_min = float(params.get("wick_ratio_min", 0.60))
        prox_atr       = float(params.get("round_proximity_atr", 0.3))

        df["bull_pin"], df["bear_pin"] = _pin_bar_flags(
            df,
            body_ratio_max=body_ratio_max,
            wick_ratio_min=wick_ratio_min,
        )

        # Round number proximity
        df["bull_round_near"], df["bear_round_near"] = _round_proximity_flags(
            df, grid=grid, atr_factor=prox_atr
        )

        # Combined: pin + round proximity
        df["bull_pin_at_round"] = df["bull_pin"] & df["bull_round_near"]
        df["bear_pin_at_round"] = df["bear_pin"] & df["bear_round_near"]

        # Round number grid stored for signals
        df["_round_grid"] = grid

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        # Swing high/low (for SL computation)
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"]  = sl

        return df

    # ------------------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "bull_pin_at_round" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg  = self.manifest.signals
        filters      = signals_cfg.filters
        confluence   = signals_cfg.confluence
        sr_cfg       = signals_cfg.structure.support_resistance

        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )
        tail_atr_buf = float(
            self.manifest.risk.get("stop_loss", {}).get("tail_atr_buffer", 0.5)
        )

        venue     = str(df["venue"].iloc[0])     if "venue"     in df.columns else "unknown"
        symbol    = str(df["symbol"].iloc[0])    if "symbol"    in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Pattern weights ---
        bull_weight = 2.0
        bear_weight = 2.0
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_pin_at_round":
                bull_weight = p.weight
            elif p.id == "bearish_pin_at_round":
                bear_weight = p.weight

        # --- Base scores ---
        long_score  = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        bull_flag = df["bull_pin_at_round"].fillna(False)
        bear_flag = df["bear_pin_at_round"].fillna(False)

        long_score  = long_score.where(~bull_flag,  bull_weight)
        short_score = short_score.where(~bear_flag, bear_weight)

        # --- ATR min filter ---
        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.0)
        if atr_min > 0:
            mask        = df["atr_pct"] >= atr_min
            long_score  = long_score.where(mask,  0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Volume z-score filter ---
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        if vol_min > 0 and "vol_z" in df.columns:
            mask        = df["vol_z"].fillna(-np.inf) >= vol_min
            long_score  = long_score.where(mask,  0.0)
            short_score = short_score.where(mask, 0.0)

        # --- Kaufman ER filter ---
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask        = df["kaufman_er"] >= er_min
            long_score  = long_score.where(mask,  0.0)
            short_score = short_score.where(mask, 0.0)

        # --- 200-EMA bear regime ---
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200   = df["close"] < df["ema200"]
            long_score  = long_score.where(~below_200, long_score * bear_factor)

        # --- S/R proximity bonus ---
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records  = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )
        sr_by_bar: dict[int, list[float]] = {}
        for i, lvl, _t in sr_records:
            sr_by_bar.setdefault(i, []).append(lvl)

        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus         = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score     = float(confluence.min_score)

        out: list[Signal] = []

        for i in range(len(df)):
            row   = df.iloc[i]
            close = float(row["close"])
            atr   = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # S/R proximity
            levels  = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol     = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, pattern_id_name in (
                ("long",  long_score,  "bullish_pin_at_round"),
                ("short", short_score, "bearish_pin_at_round"),
            ):
                base_score  = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if final_score < min_score:
                    continue

                # --- SL computation ---
                # Bullish pin: SL below bar low - buffer
                # Bearish pin: SL above bar high + buffer
                bar_low  = float(row["low"])
                bar_high = float(row["high"])

                if direction == "long":
                    sl_price = bar_low - tail_atr_buf * atr
                    sl_price = min(sl_price, close - 0.5 * atr)  # sanity
                    risk     = close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = close + primary_R * risk
                else:
                    sl_price = bar_high + tail_atr_buf * atr
                    sl_price = max(sl_price, close + 0.5 * atr)  # sanity
                    risk     = sl_price - close
                    if risk <= 0:
                        continue
                    tp_price = close - primary_R * risk

                ts_dt = pd.Timestamp(row["ts"]).to_pydatetime()

                # Nearest round number for metadata
                grid      = float(row.get("_round_grid", 1.0))
                anchor    = bar_low if direction == "long" else bar_high
                rn_dist   = distance_to_nearest_round(anchor, grid)
                rn_level  = round(anchor / grid) * grid if grid > 0 else 0.0

                sig = self.emit_signal(
                    ts=ts_dt,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    pattern_id=pattern_id_name,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "near_sr":        near_sr,
                        "atr14":          atr,
                        "round_grid":     grid,
                        "round_level":    rn_level,
                        "round_dist_atr": rn_dist / atr if atr > 0 else 0.0,
                        "bar_range":      bar_high - bar_low,
                        "ema50":          float(row.get("ema50") or 0.0),
                        "kaufman_er":     float(row.get("kaufman_er") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info(
            "pin_bar_round_numbers.signals.generated"
        )
        return out
