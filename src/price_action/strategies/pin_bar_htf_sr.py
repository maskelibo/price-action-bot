"""Pin Bar at HTF S/R stratejisi.

Strateji: 1W timeframe'den tespit edilen major S/R seviyelerine yakın
           tek-bar pin bar reversal. Volman/Grimes sentezi.

Kural ozeti (mekanik):
  - Pin bar tanimi :
      body   <= %33 of total range  (body_ratio_max = 0.33)
      wick   >= %60 of total range  (dominant_wick_ratio_min = 0.60)
    Bullish pin : lower_wick dominant (lower_wick / range >= 0.60),
                  body + upper_wick kucuk, kapanis fitil koku tarafinda
    Bearish pin : upper_wick dominant (upper_wick / range >= 0.60)
  - HTF S/R     : 1W OHLCV'den 5-hafta lookback swing high/low
  - Yakinlik    : Pin bar'in high veya low'u 0.5×ATR(1d) icinde olmali
  - Giris       : Pin bar kapanisi (N+1 acilis order da desteklenir)
  - Stop        : Pin bar fitil ucu + 0.1×ATR tampon
  - Hedef       : 2R (primary), stop pine gore ATR-bazli
  - Engulfing'den FARK: tek-bar, kucuk govde; engulfing cift-bar, buyuk govde

Manifest yoksa dahili default kullanilir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _rolling_sharpe,
)

# =====================================================================
# Pin bar helpers (vektorel, lookahead-free)
# =====================================================================


def _pin_bar_components(df: pd.DataFrame) -> pd.DataFrame:
    """Her bar icin fitil/govde bilesenleri.

    Returns DataFrame with columns:
        rng, body, upper_wick, lower_wick,
        body_ratio, upper_wick_ratio, lower_wick_ratio
    """
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    close = df["close"]

    rng = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    upper_wick = high - df[["close", "open"]].max(axis=1)
    lower_wick = df[["close", "open"]].min(axis=1) - low

    body_ratio = (body / rng).fillna(0.0)
    upper_wick_ratio = (upper_wick / rng).fillna(0.0)
    lower_wick_ratio = (lower_wick / rng).fillna(0.0)

    out = pd.DataFrame(
        {
            "rng": rng,
            "body": body,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "body_ratio": body_ratio,
            "upper_wick_ratio": upper_wick_ratio,
            "lower_wick_ratio": lower_wick_ratio,
        },
        index=df.index,
    )
    return out


def _bullish_pin_bar(
    df: pd.DataFrame,
    body_ratio_max: float = 0.33,
    lower_wick_ratio_min: float = 0.60,
    upper_wick_ratio_max: float = 0.25,
) -> pd.Series:
    """Bullish pin bar: uzun alt fitil, kucuk govde, kapanis uste.

    Grimes/Volman tanimlari:
      - body <= 33% range
      - lower_wick >= 60% range  (dominant rejection wick)
      - upper_wick <= 25% range  (kisa veya yok)
      - kapanis, bar ortasinin ustunde olmali (close > mid)
    """
    pc = _pin_bar_components(df)
    mid = (df["high"] + df["low"]) / 2

    cond = (
        (pc["body_ratio"] <= body_ratio_max)
        & (pc["lower_wick_ratio"] >= lower_wick_ratio_min)
        & (pc["upper_wick_ratio"] <= upper_wick_ratio_max)
        & (df["close"] >= mid)  # kapanis ust yarisinda
    )
    return cond.fillna(False)


def _bearish_pin_bar(
    df: pd.DataFrame,
    body_ratio_max: float = 0.33,
    upper_wick_ratio_min: float = 0.60,
    lower_wick_ratio_max: float = 0.25,
) -> pd.Series:
    """Bearish pin bar: uzun ust fitil, kucuk govde, kapanis altta."""
    pc = _pin_bar_components(df)
    mid = (df["high"] + df["low"]) / 2

    cond = (
        (pc["body_ratio"] <= body_ratio_max)
        & (pc["upper_wick_ratio"] >= upper_wick_ratio_min)
        & (pc["lower_wick_ratio"] <= lower_wick_ratio_max)
        & (df["close"] <= mid)  # kapanis alt yarisinda
    )
    return cond.fillna(False)


# =====================================================================
# HTF S/R tespit (1W swing high/low)
# =====================================================================


def _weekly_swing_sr_levels(
    df_weekly: pd.DataFrame,
    lookback_weeks: int = 52,
    fractal_n: int = 2,
) -> pd.Series:
    """1W verisinden swing high/low S/R seviyeleri uret.

    Her hafta icin: son `lookback_weeks` hafta icindeki swing yuksek/dusukler
    bir liste olarak verilir. Index: haftalik timestamps.
    Donus: dict-like Series, index=haftalik_ts, value=list[float].

    Lookahead-free: t haftasi icin [t-lookback, t-1] kullanilir.
    """
    if df_weekly.empty:
        return pd.Series(dtype=object)

    df_w = df_weekly.sort_values("ts").reset_index(drop=True).copy()
    sh, sl = _fractal_swings(df_w, n=fractal_n)
    df_w["_sh"] = sh
    df_w["_sl"] = sl

    out: list[list[float]] = []
    for i in range(len(df_w)):
        start_i = max(0, i - lookback_weeks)
        # FIX 2026-07-08 (dalga-4 W4 HIGH): fraktal teyit gecikmesi.
        # _fractal_swings docstring: swing "sadece bar t-n için kullanilabilir"
        # (sağ taraf bilgisi). Hafta j'nin swing'i j+fractal_n haftası KAPANANA
        # kadar kesinleşmez. Eski üst sınır `i` (i-1'e kadar) → hafta i, i+1'de
        # kesinleşecek swing'i kullanıyordu = fractal_n haftalık LOOKAHEAD.
        # Doğru üst sınır i-fractal_n: en son dahil edilen hafta i-fractal_n-1,
        # swing'i i-1'de kesinleşir → hafta i'de gerçekten bilinir.
        end_i = max(start_i, i - fractal_n)
        window = df_w.iloc[start_i:end_i]
        levels: list[float] = []
        for _, row in window.iterrows():
            if row["_sh"]:
                levels.append(float(row["high"]))
            if row["_sl"]:
                levels.append(float(row["low"]))
        out.append(levels)

    return pd.Series(out, index=df_w["ts"].values)


def _resample_to_weekly(df_daily: pd.DataFrame) -> pd.DataFrame:
    """1D OHLCV'yi 1W OHLCV'ye donustur (ISO week, Monday-based).

    Lookahead yok: her hafta ancak o haftanin tum barlari kapaninca olusur.
    Backtest'te simule etmek icin: bar N'in haftasini shift(1) ile al.
    """
    df = df_daily.copy()
    df = df.sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    weekly = df.resample("W-MON", label="left", closed="left")[list(agg.keys())].agg(agg)
    weekly = weekly.dropna(subset=["close"]).reset_index()
    weekly = weekly.rename(columns={"ts": "ts"})

    # Ek kollar kopyala (venue, symbol, timeframe)
    for col in ("venue", "symbol"):
        if col in df_daily.columns:
            weekly[col] = df_daily[col].iloc[0]
    weekly["timeframe"] = "1w"
    return weekly


def _map_weekly_levels_to_daily(
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    sr_series: pd.Series,
) -> list[list[float]]:
    """Her gunluk bar icin gecerli HTF S/R seviyelerini dondur.

    Lookahead-free: bar N icin yalnizca onceki haftanin kapanisina kadar
    bilinen S/R seviyeleri kullanilir.

    Timezone normalizasyonu yapilir: sr_series index UTC'ye esitleniyor.
    """
    df_d = df_daily.sort_values("ts").reset_index(drop=True).copy()
    df_d["ts"] = pd.to_datetime(df_d["ts"], utc=True)

    # sr_series index'ini UTC'ye normalize et
    sr_idx = pd.DatetimeIndex(sr_series.index)
    sr_idx = sr_idx.tz_localize("UTC") if sr_idx.tz is None else sr_idx.tz_convert("UTC")

    # sr_series'i yeniden indeksle (tz-normalized)
    sr_values = list(sr_series.values)
    sr_dict = {ts: vals for ts, vals in zip(sr_idx, sr_values, strict=False)}

    mapped: list[list[float]] = []
    for _, row in df_d.iterrows():
        bar_ts = pd.Timestamp(row["ts"])
        if bar_ts.tzinfo is None:
            bar_ts = bar_ts.tz_localize("UTC")

        # Bir hafta oncesine kadar olan S/R'lari kullan (lookahead-free)
        cutoff = bar_ts - pd.Timedelta(days=7)

        # sr_dict'ten cutoff'tan onceki en son seri
        candidate = None
        for ts in sorted(sr_dict.keys()):
            if ts <= cutoff:
                candidate = sr_dict[ts]
            else:
                break

        if candidate is None:
            mapped.append([])
        else:
            mapped.append(list(candidate) if isinstance(candidate, list) else [])

    return mapped


# =====================================================================
# Default manifest
# =====================================================================


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "pin_bar_htf_sr",
        "version": "1.0.0",
        "description": (
            "Single-bar pin bar reversal at HTF (1W) S/R levels. "
            "Volman/Grimes concept: 68-73% WR when pin fires at major S/R."
        ),
        "timeframes": {
            "decision": "1d",
            "trend_filter": "1w",
        },
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_pin_htf_sr",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "lower_wick_ratio_min": 0.60,
                        "upper_wick_ratio_max": 0.25,
                    },
                },
                {
                    "id": "bearish_pin_htf_sr",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_max": 0.33,
                        "upper_wick_ratio_min": 0.60,
                        "lower_wick_ratio_max": 0.25,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 52,  # 52 hafta = 1 yil HTF lookback
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 1,
                    "max_age_bars": 52,
                },
                "require_proximity_to_sr_atr": 0.5,  # 0.5 ATR(1d) yakinlik
            },
            "filters": {
                "atr_min_pct": 0.005,  # bar range minimum %0.5
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,  # chop filter yok (S/R reversal)
                "htf_lookback_weeks": 52,  # 52 haftalik S/R tarama
                "htf_min_sr_levels": 1,  # en az 1 HTF level olmali
                "sr_proximity_atr_factor": 0.5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {
                "method": "pin_wick",  # pin fitil ucuna stop
                "wick_buffer_atr": 0.10,  # 0.1 ATR tampon
            },
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 300,  # 52 hafta + 300 gun warmup
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================


class PinBarHTFSRStrategy(Strategy):
    """Pin Bar at HTF S/R — Volman/Grimes single-bar reversal.

    Temel mekanik:
      1. 1D bar uzerinde pin bar tespiti (govde <= %33 range, wick >= %60)
      2. 1W verisinden oncelikli S/R seviyeleri (swing high/low, >= 5 hafta lookback)
      3. Pin bar'in wick ucu HTF S/R'a 0.5 ATR(1d) icinde olmali
      4. Giris: bar kapanisinda (veya N+1 bar acilis)
      5. Stop: dominant wick ucu +/- 0.1 ATR tampon
      6. Hedef: 2R

    Engulfing'den fark:
      - Tek bar (iki bar degil)
      - Kucuk govde (buyuk govde degil)
      - S/R'a yakinlik zorunlu (EMA pullback degil)
    """

    name = "pin_bar_htf_sr"

    def __init__(self, manifest: StrategyManifest) -> None:
        super().__init__(manifest)
        # weekly OHLCV cache: symbol -> DataFrame
        self._weekly_cache: dict[str, pd.DataFrame] = {}
        # HTF S/R series cache: symbol -> pd.Series (index=weekly_ts, value=list[float])
        self._htf_sr_cache: dict[str, pd.Series] = {}

    def set_weekly_data(self, symbol: str, df_weekly: pd.DataFrame) -> None:
        """Dis kaynak 1W OHLCV enjekte et (backtest scriptinden cagrilir)."""
        self._weekly_cache[symbol] = df_weekly.copy()

    # ----- prepare_features -----

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"

        # --- EMA & ATR ---
        df["ema20"] = _ema(df["close"], 20)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Rolling Sharpe
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=60)

        # Pin bar flags (1D)
        params_bull = {}
        params_bear = {}
        for p in self.manifest.signals.patterns:
            if p.id == "bullish_pin_htf_sr":
                params_bull = p.params
            elif p.id == "bearish_pin_htf_sr":
                params_bear = p.params

        df["bull_pin"] = _bullish_pin_bar(
            df,
            body_ratio_max=float(params_bull.get("body_ratio_max", 0.33)),
            lower_wick_ratio_min=float(params_bull.get("lower_wick_ratio_min", 0.60)),
            upper_wick_ratio_max=float(params_bull.get("upper_wick_ratio_max", 0.25)),
        )
        df["bear_pin"] = _bearish_pin_bar(
            df,
            body_ratio_max=float(params_bear.get("body_ratio_max", 0.33)),
            upper_wick_ratio_min=float(params_bear.get("upper_wick_ratio_min", 0.60)),
            lower_wick_ratio_max=float(params_bear.get("lower_wick_ratio_max", 0.25)),
        )

        # HTF S/R seviyeleri — 1W verisinden
        htf_lookback = int(getattr(filters_cfg, "htf_lookback_weeks", 52) or 52)
        weekly_df = self._weekly_cache.get(symbol)
        if weekly_df is None:
            # 1D verisini 1W'ya yeniden ornekle (fallback)
            weekly_df = _resample_to_weekly(df)
            self._weekly_cache[symbol] = weekly_df

        # HTF S/R seri hesapla (once cache'den al)
        if symbol not in self._htf_sr_cache:
            sr_series = _weekly_swing_sr_levels(
                weekly_df,
                lookback_weeks=htf_lookback,
                fractal_n=2,
            )
            self._htf_sr_cache[symbol] = sr_series
        else:
            sr_series = self._htf_sr_cache[symbol]

        # Her gunluk bar icin HTF S/R listesi
        mapped_levels = _map_weekly_levels_to_daily(df, weekly_df, sr_series)
        df["htf_sr_levels"] = mapped_levels  # list of floats per row

        # Pin bar'in wick ucu ile en yakin HTF S/R arasindaki mesafe (ATR biriminde)
        sr_proximity_atr = float(getattr(filters_cfg, "sr_proximity_atr_factor", 0.5) or 0.5)
        atr_vals = df["atr14"].fillna(0.0).to_numpy()
        lows = df["low"].to_numpy()
        highs = df["high"].to_numpy()
        htf_levels_list = df["htf_sr_levels"].tolist()

        bull_near_sr = np.zeros(len(df), dtype=bool)
        bear_near_sr = np.zeros(len(df), dtype=bool)
        closest_bull_sr = np.full(len(df), np.nan)
        closest_bear_sr = np.full(len(df), np.nan)

        for i in range(len(df)):
            levels = htf_levels_list[i]
            if not levels:
                continue
            atr = atr_vals[i]
            if atr <= 0 or np.isnan(atr):
                continue
            tol = sr_proximity_atr * atr
            # Bullish pin: lower wick ucu (low) S/R'a yakın mı?
            for lvl in levels:
                if abs(lows[i] - lvl) <= tol:
                    bull_near_sr[i] = True
                    if np.isnan(closest_bull_sr[i]) or abs(lows[i] - lvl) < abs(
                        lows[i] - closest_bull_sr[i]
                    ):
                        closest_bull_sr[i] = lvl
            # Bearish pin: upper wick ucu (high) S/R'a yakın mı?
            for lvl in levels:
                if abs(highs[i] - lvl) <= tol:
                    bear_near_sr[i] = True
                    if np.isnan(closest_bear_sr[i]) or abs(highs[i] - lvl) < abs(
                        highs[i] - closest_bear_sr[i]
                    ):
                        closest_bear_sr[i] = lvl

        df["bull_near_htf_sr"] = bull_near_sr
        df["bear_near_htf_sr"] = bear_near_sr
        df["closest_bull_sr"] = closest_bull_sr
        df["closest_bear_sr"] = closest_bear_sr

        return df

    # ----- generate_signals -----

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "bull_pin" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence

        primary_r = float(self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0))
        wick_buffer_atr = float(
            self.manifest.risk.get("stop_loss", {}).get("wick_buffer_atr", 0.10)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        min_score = float(confluence.min_score)
        bonus_sr = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)

        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)

        # Pattern weights
        bull_weight = 2.0
        bear_weight = 2.0
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_pin_htf_sr":
                bull_weight = p.weight
            elif p.id == "bearish_pin_htf_sr":
                bear_weight = p.weight

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # ATR min filter
            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # Volume z-score filter
            vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
            if vol_min > 0:
                vol_z = float(row.get("vol_z") or -np.inf)
                if np.isnan(vol_z) or vol_z < vol_min:
                    continue

            # --- Bullish pin bar + HTF S/R ---
            bull_pin = bool(row.get("bull_pin", False))
            bull_near = bool(row.get("bull_near_htf_sr", False))

            if bull_pin and bull_near:
                score = bull_weight + bonus_sr
                if score >= min_score:
                    # Stop: pin bar low - buffer
                    sl_price = float(row["low"]) - wick_buffer_atr * atr
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    if risk <= 0:
                        risk = 0.5 * atr
                        sl_price = close - risk
                    tp_price = close + primary_r * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="bullish_pin_htf_sr",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "htf_sr_level": float(row.get("closest_bull_sr") or 0.0),
                            "pin_low": float(row["low"]),
                            "body_ratio": float(row.get("atr14", 0.0)),
                            "ema50": float(row.get("ema50") or 0.0),
                            "kaufman_er": float(row.get("kaufman_er") or 0.0),
                            "vol_z": float(row.get("vol_z") or 0.0),
                        },
                    )
                    out.append(sig)

            # --- Bearish pin bar + HTF S/R ---
            bear_pin = bool(row.get("bear_pin", False))
            bear_near = bool(row.get("bear_near_htf_sr", False))

            if bear_pin and bear_near:
                score = bear_weight + bonus_sr
                if score >= min_score:
                    # Stop: pin bar high + buffer
                    sl_price = float(row["high"]) + wick_buffer_atr * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk = sl_price - close
                    if risk <= 0:
                        risk = 0.5 * atr
                        sl_price = close + risk
                    tp_price = close - primary_r * risk

                    ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="short",
                        pattern_id="bearish_pin_htf_sr",
                        confluence_score=float(score),
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "atr14": atr,
                            "htf_sr_level": float(row.get("closest_bear_sr") or 0.0),
                            "pin_high": float(row["high"]),
                            "ema50": float(row.get("ema50") or 0.0),
                            "kaufman_er": float(row.get("kaufman_er") or 0.0),
                            "vol_z": float(row.get("vol_z") or 0.0),
                        },
                    )
                    out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("pin_bar_htf_sr.signals.generated")
        return out
