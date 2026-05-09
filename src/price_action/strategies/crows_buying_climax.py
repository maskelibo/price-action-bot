"""HYP-NEW-6: Three Black Crows + Buying Climax Distribution Short.

Edge: Bulkowski Three Black Crows %78 (Rank 7/103) + VSA Buying Climax =
mechanical distribution short confluencesi.

Researcher beklentisi: %75-82 Win Rate (highest priority).

4-bar sequence (Buying Climax bar + 3 crows) — standalone Three Black Crows'tan
decorrelated: BC filtresi volume + spread + kapanış koşuluyla giriş kalitesini
artırırken sinyal frekansını bilerek düşürür (kalite > miktar).

Mekanik kurallar:
  BC Bar (t-3):
    - spread > 1.5 x ATR(14)          (genis bar)
    - volume > 2.5 x volume_SMA(20)   (klimaktik hacim)
    - close < low + 0.50 x range      (alt yaridana kapanis — uzun ust fitil)
    - high == rolling_max(high, 5)     (yerel zirve — 5-bar new high)
    - Opsiyonel: close > open          (FOMO yukarı bar — BC klasik tanımı)

  3 Black Crows (t-2, t-1, t):
    - Bearish: close < open
    - Body >= 50% range
    - Lower wick <= 20% range
    - Close[i] < close[i-1] (LL serisi)
    - Open[i] within prior bar body (open proximity)
    - Volume escalation: her kus bir oncekinden yuksek hacim

  Bagim (EMA-200):
    - BC bar (t-3) 200-EMA uzerinde olmali (bull cycle distribution top)

  Entry: 3. kus barinin kapanis sonrasi acilis (kısa = next bar open ≈ t kapanisi)
  SL   : BC high + 0.5 x ATR (structural top)
  TP   : 3R
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr, _ema


# =====================================================================
# Buying Climax detector
# =====================================================================

def _buying_climax(
    df: pd.DataFrame,
    *,
    spread_atr_mult: float = 1.5,
    vol_sma_mult: float = 2.5,
    close_pos_max: float = 0.50,
    new_high_bars: int = 5,
    vol_sma_window: int = 20,
    require_up_bar: bool = True,
) -> pd.Series:
    """Buying Climax (BC) dedektoru (lookahead-free).

    VSA tanımı (vsa_volume_spread_analysis.md §4.11):
      up_bar AND spread > spread_atr_mult * ATR AND
      close < low + close_pos_max * (high - low) AND
      volume > vol_sma_mult * volume_SMA AND
      high == rolling_max(high, new_high_bars)

    Parameters
    ----------
    spread_atr_mult : float
        Spread esigi: spread > mult * ATR(14).
    vol_sma_mult : float
        Hacim esigi: volume > mult * SMA(vol_sma_window).
    close_pos_max : float
        Kapanıs pozisyonu: close range icinde ust %50'nin altinda.
        close < low + close_pos_max * range => uzun ust fitil.
    new_high_bars : int
        "5-bar new high" penceresi: high == rolling max.
    vol_sma_window : int
        Volume SMA penceresi (genellikle 20).
    require_up_bar : bool
        BC bar'i bullish (close > open) olmali mi? (klasik VSA evet).
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    v = df["volume"]

    rng = (h - l).replace(0, np.nan)
    atr14 = _atr(df, 14)
    vol_sma = v.rolling(vol_sma_window, min_periods=5).mean()

    # Spread koşulu
    spread_ok = rng > spread_atr_mult * atr14

    # Volume koşulu
    vol_ok = v > vol_sma_mult * vol_sma

    # Kapanış pozisyonu: üst fitle uzun (close alt yarida)
    # close < low + close_pos_max * range  →  ust yarida degil
    close_pos_ok = c < (l + close_pos_max * rng)

    # 5-bar new high (rolling max önceki new_high_bars barda)
    # Kullanıyoruz: high == rolling_max(high, new_high_bars) — yani
    # bu bar son N barin en yüksek high'ı. Lookahead-safe:
    # rolling_max geçmiş barları kullanır.
    rolling_h_max = h.rolling(new_high_bars, min_periods=new_high_bars).max()
    new_high_ok = h >= rolling_h_max  # == ile float karşılaştırması; >= identik

    # Up bar (BC classik: fiyat yukari hareket ediyordu - FOMO)
    if require_up_bar:
        up_bar_ok = c > o
    else:
        up_bar_ok = pd.Series(True, index=df.index)

    bc = spread_ok & vol_ok & close_pos_ok & new_high_ok & up_bar_ok
    return bc.fillna(False)


# =====================================================================
# Three Black Crows detector (tighter than standalone — for confluence)
# =====================================================================

def _three_black_crows_strict(
    df: pd.DataFrame,
    *,
    body_ratio_min: float = 0.50,
    lower_shadow_max: float = 0.20,
    open_proximity_pct: float = 0.60,
    vol_escalation_strict: bool = True,
) -> pd.Series:
    """Three Black Crows (siki versiyon — confluence icin).

    Standalone'dan fark:
    - Her kus bar-to-bar volume eskalasyonu (v2>v1 AND v3>v2) — daha siki
    - open_proximity daha siki (onceki bar body icinde acilis)

    t barinda True => [t-2, t-1, t] uclisi tam kural karsiliyor.
    """
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]
    v = df["volume"]

    rng = (h - l).replace(0, np.nan)
    body_abs = (c - o).abs()
    body_ratio = body_abs / rng

    # Bearish bar icin lower shadow = close - low (close < open)
    lower_shadow = (c - l).clip(lower=0.0)
    lower_shadow_ratio = lower_shadow / rng

    is_bearish = c < o
    good_bar = (
        is_bearish
        & (body_ratio >= body_ratio_min)
        & (lower_shadow_ratio <= lower_shadow_max)
    )

    # Indexler: t=bar3, t-1=bar2, t-2=bar1
    gb3 = good_bar
    gb2 = good_bar.shift(1).fillna(False)
    gb1 = good_bar.shift(2).fillna(False)

    o3, c3 = o, c
    o2, c2 = o.shift(1), c.shift(1)
    o1, c1 = o.shift(2), c.shift(2)
    v3 = v
    v2 = v.shift(1)
    v1 = v.shift(2)

    # LL serisi
    ll_ok = (c3 < c2) & (c2 < c1)

    # Open proximity: bar opens within prior bar body (strict)
    # For bar3: open3 should be between c2 and o2 (prior bearish body)
    # Since prior is bearish: body spans [c2, o2] (c2 < o2)
    # Allow open3 in [c2 - proximity*body, o2 + proximity*body] band
    body2_abs = (o2 - c2).clip(lower=0.0)  # prior bearish body size
    body1_abs = (o1 - c1).clip(lower=0.0)

    # Bar3 opens near bar2 close (not too far above c2)
    prox3_band = open_proximity_pct * body2_abs
    open3_ok = (o3 <= o2 + prox3_band) & (o3 >= c2 - prox3_band * 0.5)

    prox2_band = open_proximity_pct * body1_abs
    open2_ok = (o2 <= o1 + prox2_band) & (o2 >= c1 - prox2_band * 0.5)

    # Volume escalation: strict bar-to-bar (v1 < v2 < v3)
    if vol_escalation_strict:
        vol_ok = (v2 > v1) & (v3 > v2)
    else:
        # Net escalation: v3 > v1
        vol_ok = v3 > v1

    signal = gb1 & gb2 & gb3 & ll_ok & open2_ok & open3_ok & vol_ok
    return signal.fillna(False)


# =====================================================================
# Confluence detector
# =====================================================================

def _crows_buying_climax_signal(
    df: pd.DataFrame,
    *,
    # BC parametreleri
    bc_spread_atr_mult: float = 1.5,
    bc_vol_sma_mult: float = 2.5,
    bc_close_pos_max: float = 0.50,
    bc_new_high_bars: int = 5,
    bc_vol_sma_window: int = 20,
    bc_require_up_bar: bool = True,
    # Crows parametreleri
    crow_body_min: float = 0.50,
    crow_shadow_max: float = 0.20,
    crow_proximity: float = 0.60,
    crow_vol_strict: bool = True,
    # 200-EMA filtresi
    require_ema200_above: bool = True,
) -> pd.Series:
    """BC + 3 Crows confluence sinyali.

    Sinyal t barinda True ise:
      - t-3: Buying Climax
      - t-2, t-1, t: Three Black Crows (sıkı versiyon)
      - t-3 bar 200-EMA uzerinde (eger filtre aktifse)

    Entry: t kapanis sonrasi (t+1 acilis = short market).
    """
    bc_flags = _buying_climax(
        df,
        spread_atr_mult=bc_spread_atr_mult,
        vol_sma_mult=bc_vol_sma_mult,
        close_pos_max=bc_close_pos_max,
        new_high_bars=bc_new_high_bars,
        vol_sma_window=bc_vol_sma_window,
        require_up_bar=bc_require_up_bar,
    )

    crow_flags = _three_black_crows_strict(
        df,
        body_ratio_min=crow_body_min,
        lower_shadow_max=crow_shadow_max,
        open_proximity_pct=crow_proximity,
        vol_escalation_strict=crow_vol_strict,
    )

    # BC 3 bar once olmali (t-3) — crow_flags at t means crows at [t-2,t-1,t]
    bc_3bars_ago = bc_flags.shift(3).fillna(False)

    confluence = bc_3bars_ago & crow_flags

    # 200-EMA filtresi: BC bari (t-3) 200-EMA uzerinde
    if require_ema200_above:
        ema200 = _ema(df["close"], 200)
        bc_bar_close = df["close"].shift(3)
        bc_bar_ema200 = ema200.shift(3)
        ema_ok = bc_bar_close > bc_bar_ema200
        confluence = confluence & ema_ok.fillna(False)

    return confluence.fillna(False)


def _bc_sl_price(df: pd.DataFrame, atr_buffer: float = 0.5) -> pd.Series:
    """SL = BC bar high (t-3) + 0.5 x ATR(14).

    Structural top = kurumsal dağıtım tepesi.
    """
    atr14 = _atr(df, 14)
    bc_high = df["high"].shift(3)
    return bc_high + atr_buffer * atr14


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "crows_buying_climax",
        "version": "1.0.0",
        "description": (
            "HYP-NEW-6: Three Black Crows + Buying Climax Distribution Short. "
            "Bulkowski %78 (Rank 7/103) + VSA Buying Climax confluence. "
            "Short-only. 200-EMA above required (bull cycle distribution top). "
            "SL: BC high + 0.5*ATR. TP: 3R."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "crows_buying_climax",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        # Buying Climax params
                        "bc_spread_atr_mult": 1.5,
                        "bc_vol_sma_mult": 2.5,
                        "bc_close_pos_max": 0.50,
                        "bc_new_high_bars": 5,
                        "bc_vol_sma_window": 20,
                        "bc_require_up_bar": True,
                        # Three Black Crows params
                        "crow_body_min": 0.50,
                        "crow_shadow_max": 0.20,
                        "crow_proximity": 0.60,
                        "crow_vol_strict": True,
                        # Context
                        "require_ema200_above": True,
                        "sl_atr_buffer": 0.5,
                    },
                }
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
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 3.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "bc_high_atr", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy class
# =====================================================================

class CrowsBuyingClimaxStrategy(Strategy):
    """HYP-NEW-6: Three Black Crows + Buying Climax Distribution Short.

    SHORT ONLY.

    4-bar sinyal yapisi:
      t-3: Buying Climax (klimaktik hacim + genis bar + uzun ust fitil + yerel zirve)
      t-2: Crow 1 (bearish, genis govde, dusuk alt golge)
      t-1: Crow 2 (bearish, genis govde, dusuk alt golge, c2 < c1)
      t  : Crow 3 (bearish, genis govde, dusuk alt golge, c3 < c2)
           + volume eskalasyonu (v1<v2<v3 veya v3>v1)

    Entry: bar t kapanisinda (ya da t+1 acilis) short market.
    SL   : BC bar (t-3) high + 0.5 x ATR (structural top).
    TP   : 3R (distribution moves big).
    """

    name = "crows_buying_climax"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMA ve ATR
        df["ema200"] = _ema(df["close"], 200)
        df["ema50"] = _ema(df["close"], 50)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=5).mean()
        vstd = vol.rolling(60, min_periods=5).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Volume SMA (20 bar) — BC icin
        df["vol_sma20"] = vol.rolling(20, min_periods=5).mean()

        # Parametre okuma
        params: dict[str, Any] = {}
        for p in self.manifest.signals.patterns:
            if p.id == "crows_buying_climax":
                params = p.params
                break

        bc_spread = float(params.get("bc_spread_atr_mult", 1.5))
        bc_vol = float(params.get("bc_vol_sma_mult", 2.5))
        bc_close_pos = float(params.get("bc_close_pos_max", 0.50))
        bc_new_high = int(params.get("bc_new_high_bars", 5))
        bc_sma_win = int(params.get("bc_vol_sma_window", 20))
        bc_up_bar = bool(params.get("bc_require_up_bar", True))
        crow_body = float(params.get("crow_body_min", 0.50))
        crow_shadow = float(params.get("crow_shadow_max", 0.20))
        crow_prox = float(params.get("crow_proximity", 0.60))
        crow_vol_strict = bool(params.get("crow_vol_strict", True))
        req_ema = bool(params.get("require_ema200_above", True))
        sl_buf = float(params.get("sl_atr_buffer", 0.5))

        # Confluence sinyali
        df["cbc_signal"] = _crows_buying_climax_signal(
            df,
            bc_spread_atr_mult=bc_spread,
            bc_vol_sma_mult=bc_vol,
            bc_close_pos_max=bc_close_pos,
            bc_new_high_bars=bc_new_high,
            bc_vol_sma_window=bc_sma_win,
            bc_require_up_bar=bc_up_bar,
            crow_body_min=crow_body,
            crow_shadow_max=crow_shadow,
            crow_proximity=crow_prox,
            crow_vol_strict=crow_vol_strict,
            require_ema200_above=req_ema,
        )

        # BC flags standalone (for reporting)
        df["bc_flag"] = _buying_climax(
            df,
            spread_atr_mult=bc_spread,
            vol_sma_mult=bc_vol,
            close_pos_max=bc_close_pos,
            new_high_bars=bc_new_high,
            vol_sma_window=bc_sma_win,
            require_up_bar=bc_up_bar,
        )

        # 3 Crows flags standalone (for reporting)
        df["crow_flag"] = _three_black_crows_strict(
            df,
            body_ratio_min=crow_body,
            lower_shadow_max=crow_shadow,
            open_proximity_pct=crow_prox,
            vol_escalation_strict=crow_vol_strict,
        )

        # SL: BC high (t-3) + 0.5 * ATR
        df["cbc_sl"] = _bc_sl_price(df, atr_buffer=sl_buf)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "cbc_signal" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        min_score = float(signals_cfg.confluence.min_score)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        pattern_weight = 3.0
        for p in signals_cfg.patterns:
            if p.id == "crows_buying_climax" and p.enabled:
                pattern_weight = p.weight
                break

        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]

            if not bool(row.get("cbc_signal", False)):
                continue

            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            close = float(row["close"])

            # SL = BC high (t-3) + 0.5 * ATR
            sl_price = float(row.get("cbc_sl") or (close + 3.0 * atr))
            if np.isnan(sl_price) or sl_price <= 0:
                sl_price = close + 3.0 * atr
            # Ensure SL is above close (short trade)
            sl_price = max(sl_price, close + 0.5 * atr)

            risk = sl_price - close
            if risk <= 0:
                continue
            tp_price = close - primary_R * risk

            score = pattern_weight
            if score < min_score:
                continue

            ts = pd.Timestamp(row["ts"]).to_pydatetime()
            sig = self.emit_signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
                direction="short",
                pattern_id="crows_buying_climax",
                confluence_score=float(score),
                sl_price=float(sl_price),
                tp_price=float(tp_price),
                suggested_size_atr=1.0,
                metadata={
                    "atr14": atr,
                    "ema200": float(row.get("ema200") or 0.0),
                    "vol_z": float(row.get("vol_z") or 0.0),
                    "bc_vol_sma20": float(row.get("vol_sma20") or 0.0),
                    "close": close,
                },
            )
            out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("crows_buying_climax.signals.generated")
        return out
