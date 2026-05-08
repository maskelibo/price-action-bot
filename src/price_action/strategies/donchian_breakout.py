"""Donchian Channel Breakout + Bollinger Squeeze Volatility Expansion strategy.

Strateji: 55-bar Donchian kanalı kırılımı, öncesinde Bollinger Squeeze (dusuk vol)
          gerceklestigini onaylar. Kaufman ER >= 0.30 (guclu trend) filtresi ile
          whipsaw rejimlerini ayiklar.

Kural ozeti:
  - Donchian 55-bar high kırılımı (dun barı hariç, close > 55-bar rolling high)
  - Son 5 barda Bollinger Squeeze aktif (BB Keltner kanalı icinde — dusuk vol)
  - Kaufman ER >= 0.30 (trend guclu)
  - Giriş: N+1 bar açılışı (N barı kapanışı sonrası karar)
  - SL: 20-bar Donchian düşüğü (long) / 20-bar Donchian yüksegi (short)
  - TP: 3R primary; trailing Donchian20 exit (Turtle style)

Turtle System 2 (Dennis & Eckhardt) + Bollinger Squeeze (Kaufman Setup 9) kombinasyonu.
Referans: Kaufman Ch.7 (Channel Breakout, Squeeze), Chan Ch.6 (Volatility Breakout).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Paylasilan yardimcilar
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
)


# =====================================================================
# Donchian & Bollinger / Keltner yardimcilari
# =====================================================================

def _donchian_channel(df: pd.DataFrame, period: int = 55) -> pd.DataFrame:
    """N-bar Donchian kanalı (high/low rolling max/min).

    Lookahead-free: t bari icin [t-period..t-1] kullanilir (shift(1) sonrasi
    rolling). Dondurur: donchian{period}_high, donchian{period}_low

    Args:
        df: OHLCV DataFrame (high, low sutunlari olmali)
        period: lookback bar sayisi (varsayilan 55 — Turtle System 2)

    Returns:
        Orijinal df'e iki sutun eklenip geri dondurulen DataFrame.
    """
    # shift(1): bugunun barini disarida birakmak icin (lookahead-free)
    high_col = f"donchian{period}_high"
    low_col = f"donchian{period}_low"
    df[high_col] = df["high"].shift(1).rolling(period, min_periods=period).max()
    df[low_col] = df["low"].shift(1).rolling(period, min_periods=period).min()
    return df


def _bollinger_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_atr_mult: float = 1.5,
) -> pd.DataFrame:
    """TTM-style Bollinger Squeeze: BB(bb_period, bb_std) Keltner(kc_period, kc_atr_mult)
    icinde oldugunda squeeze_active = True (dusuk vol rejimi).

    Bollinger Bands:
        bb_mid = EMA(close, bb_period)
        bb_upper = bb_mid + bb_std * std(close, bb_period)
        bb_lower = bb_mid - bb_std * std(close, bb_period)

    Keltner Channel:
        kc_mid = EMA(close, kc_period)
        kc_upper = kc_mid + kc_atr_mult * ATR(kc_period)
        kc_lower = kc_mid - kc_atr_mult * ATR(kc_period)

    Squeeze: BB upper < KC upper AND BB lower > KC lower

    Args:
        df: OHLCV DataFrame
        bb_period: Bollinger Band period (varsayilan 20)
        bb_std: Bollinger Band std multiplier (varsayilan 2.0)
        kc_period: Keltner Channel EMA period (varsayilan 20)
        kc_atr_mult: Keltner Channel ATR multiplier (varsayilan 1.5)

    Returns:
        df'e bb_upper, bb_lower, bb_mid, kc_upper, kc_lower, kc_mid,
        squeeze_active sutunlari eklenip dondurulur.
    """
    close = df["close"]

    # --- Bollinger Bands ---
    bb_mid = close.ewm(span=bb_period, adjust=False).mean()
    bb_std_s = close.rolling(bb_period, min_periods=bb_period).std(ddof=0)
    bb_upper = bb_mid + bb_std * bb_std_s
    bb_lower = bb_mid - bb_std * bb_std_s

    # --- Keltner Channel ---
    kc_mid = close.ewm(span=kc_period, adjust=False).mean()
    kc_atr = _atr(df, kc_period)
    kc_upper = kc_mid + kc_atr_mult * kc_atr
    kc_lower = kc_mid - kc_atr_mult * kc_atr

    # --- Squeeze: BB inside KC ---
    squeeze_active = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    df["bb_mid"] = bb_mid
    df["bb_upper"] = bb_upper
    df["bb_lower"] = bb_lower
    df["bb_std"] = bb_std_s
    df["kc_mid"] = kc_mid
    df["kc_upper"] = kc_upper
    df["kc_lower"] = kc_lower
    df["squeeze_active"] = squeeze_active.fillna(False)

    return df


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    """Donchian Breakout icin dahili default manifest.

    Turtle System 2 parametreleri (55-bar entry, 20-bar exit) ile
    Bollinger Squeeze (20 period, 2 std, 1.5 ATR mult) kombinasyonu.
    """
    raw = {
        "name": "donchian_breakout",
        "version": "1.0.0",
        "description": (
            "Donchian 55-bar breakout after Bollinger Squeeze (vol expansion); "
            "Turtle-style exit on 20-bar Donchian. Kaufman ER >= 0.30 filter."
        ),
        "trend_filter": {"type": "donchian", "period": 55, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "donchian_long_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": 55,
                        "donchian_exit_period": 20,
                        "squeeze_lookback": 5,
                    },
                },
                {
                    "id": "donchian_short_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "donchian_entry_period": 55,
                        "donchian_exit_period": 20,
                        "squeeze_lookback": 5,
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
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.30,
                "bb_period": 20,
                "bb_std": 2.0,
                "kc_period": 20,
                "kc_atr_mult": 1.5,
                "squeeze_lookback_bars": 5,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "donchian20", "exit_period": 20},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strateji sinifi
# =====================================================================

class DonchianBreakoutStrategy(Strategy):
    """Donchian Channel Breakout + Bollinger Squeeze Volatility Expansion.

    Turtle System 2 (55-bar entry, 20-bar exit) + Bollinger Squeeze filtresi.
    Dusuk volatiliteden yuksek volatiliteye gecis (squeeze release) aninda
    kırılım sinyali uretir. Kaufman ER >= 0.30 whipsaw koruması saglar.

    Attributes:
        name: Strateji kimlik adi (sinyal kayitlarinda kullanilir).
    """

    name = "donchian_breakout"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLCV df'e Donchian + Bollinger Squeeze + yardimci ozellikleri ekle.

        Uretilen kolonlar:
            donchian55_high  : 55-bar rolling high (shift(1) ile lookahead-free)
            donchian55_low   : 55-bar rolling low
            donchian20_high  : 20-bar rolling high (short exit SL)
            donchian20_low   : 20-bar rolling low (long exit SL / Turtle exit)
            bb_mid           : Bollinger Band orta (EMA20)
            bb_upper         : BB ust banti
            bb_lower         : BB alt banti
            bb_std           : BB std serisi
            kc_mid           : Keltner Channel orta (EMA20)
            kc_upper         : KC ust banti
            kc_lower         : KC alt banti
            squeeze_active   : True => BB KC icinde (dusuk vol)
            squeeze_recent   : Son squeeze_lookback barda squeeze var miydi?
            atr14            : ATR(14) — risk ve stop hesabi icin
            atr_pct          : ATR / close — sinyal filtresi icin
            kaufman_er       : Kaufman Efficiency Ratio (trend guc olcusu)

        Args:
            df: Sirali OHLCV DataFrame (ts, open, high, low, close, volume zorunlu).

        Returns:
            Ozellikler eklenmis DataFrame (kopya, orijinal degismez).
        """
        if df.empty:
            return df.copy()

        df = df.sort_values("ts").reset_index(drop=True).copy()

        # Filtre parametrelerini manifest'ten al
        filters_cfg = self.manifest.signals.filters
        bb_period = int(getattr(filters_cfg, "bb_period", 20) or 20)
        bb_std = float(getattr(filters_cfg, "bb_std", 2.0) or 2.0)
        kc_period = int(getattr(filters_cfg, "kc_period", 20) or 20)
        kc_atr_mult = float(getattr(filters_cfg, "kc_atr_mult", 1.5) or 1.5)
        squeeze_lookback = int(getattr(filters_cfg, "squeeze_lookback_bars", 5) or 5)
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)

        # --- Donchian kanalları ---
        df = _donchian_channel(df, period=55)  # entry
        df = _donchian_channel(df, period=20)  # exit / SL

        # --- Bollinger Squeeze ---
        df = _bollinger_squeeze(
            df,
            bb_period=bb_period,
            bb_std=bb_std,
            kc_period=kc_period,
            kc_atr_mult=kc_atr_mult,
        )

        # --- squeeze_recent: son N barda squeeze aktif miydi? ---
        # shift(1): bugunun squeeze durumu degil, dun ve oncesini izle
        # (sinyal uretiminde "son 5 barda squeeze var miydi?" sorusu)
        df["squeeze_recent"] = (
            df["squeeze_active"]
            .shift(1)
            .rolling(squeeze_lookback, min_periods=1)
            .max()
            .fillna(0)
            .astype(bool)
        )

        # --- ATR ---
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # --- Kaufman ER ---
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Donchian Breakout + Squeeze sinyalleri uret.

        Sinyal kosullari (long):
            1. close > donchian55_high (dun barinin 55-bar high'ini ast)
            2. squeeze_recent == True (son 5 barda dusuk vol rejimi vardi)
            3. kaufman_er >= 0.30 (guclu trend)
            4. atr_pct >= atr_min_pct (minimum volatilite)

        Short: simetrik (close < donchian55_low, donchian55_high -> donchian55_low)

        SL hesabi:
            Long  : donchian20_low (20-bar trailing Donchian — Turtle exit)
            Short : donchian20_high

        TP hesabi:
            primary_R = 3.0 (manifest'ten) => tp = entry + 3 * risk

        Args:
            df: prepare_features() cikmisi (ozellikler ekli OHLCV).

        Returns:
            Signal nesneleri listesi.
        """
        if df.empty:
            return []

        # Ozellikler eksikse hazirla
        if "donchian55_high" not in df.columns:
            df = self.prepare_features(df)

        filters_cfg = self.manifest.signals.filters
        confluence_cfg = self.manifest.signals.confluence

        # Risk parametreleri
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        atr_min = float(getattr(filters_cfg, "atr_min_pct", 0.005) or 0.005)
        er_min = float(getattr(filters_cfg, "kaufman_er_min", 0.30) or 0.30)
        min_score = float(confluence_cfg.min_score)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # --- Vektörel koşullar ---
        close = df["close"]
        don55_high = df["donchian55_high"]
        don55_low = df["donchian55_low"]
        don20_low = df["donchian20_low"]   # long SL (Turtle exit)
        don20_high = df["donchian20_high"]  # short SL

        squeeze_recent = df["squeeze_recent"].fillna(False)
        kaufman_er = df["kaufman_er"].fillna(0.0)
        atr_pct = df["atr_pct"].fillna(0.0)
        atr14 = df["atr14"].fillna(0.0)

        # Kırılım koşulları (tüm filtreler vektörize)
        long_breakout = (
            close > don55_high.fillna(np.inf)           # 55-bar high kırılımı
        ) & squeeze_recent                               # son 5 barda squeeze
        short_breakout = (
            close < don55_low.fillna(-np.inf)           # 55-bar low kırılımı
        ) & squeeze_recent

        # Kaufman ER filtresi
        er_ok = kaufman_er >= er_min
        long_breakout = long_breakout & er_ok
        short_breakout = short_breakout & er_ok

        # ATR min filtresi
        atr_ok = atr_pct >= atr_min
        long_breakout = long_breakout & atr_ok
        short_breakout = short_breakout & atr_ok

        # NaN kontrolleri (warmup barlarında donchian NaN olabilir)
        long_breakout = long_breakout & don55_high.notna() & don20_low.notna()
        short_breakout = short_breakout & don55_low.notna() & don20_high.notna()

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            entry_close = float(row["close"])
            atr = float(atr14.iat[i])

            if atr <= 0 or np.isnan(atr):
                continue

            for direction, signal_flag, pattern_id in (
                ("long", long_breakout, "donchian_long_breakout"),
                ("short", short_breakout, "donchian_short_breakout"),
            ):
                if not bool(signal_flag.iat[i]):
                    continue

                if direction == "long":
                    sl_raw = float(row.get("donchian20_low") or (entry_close - 2.0 * atr))
                    if np.isnan(sl_raw) or sl_raw <= 0:
                        sl_raw = entry_close - 2.0 * atr
                    # SL muhakkak close'un altında olmalı
                    sl_price = min(sl_raw, entry_close - 0.5 * atr)
                    risk = entry_close - sl_price
                    if risk <= 0:
                        continue
                    tp_price = entry_close + primary_R * risk
                else:
                    sl_raw = float(row.get("donchian20_high") or (entry_close + 2.0 * atr))
                    if np.isnan(sl_raw) or sl_raw <= 0:
                        sl_raw = entry_close + 2.0 * atr
                    sl_price = max(sl_raw, entry_close + 0.5 * atr)
                    risk = sl_price - entry_close
                    if risk <= 0:
                        continue
                    tp_price = entry_close - primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    pattern_id=pattern_id,
                    confluence_score=float(min_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "donchian55_high": float(row.get("donchian55_high") or 0.0),
                        "donchian55_low": float(row.get("donchian55_low") or 0.0),
                        "donchian20_low": float(row.get("donchian20_low") or 0.0),
                        "donchian20_high": float(row.get("donchian20_high") or 0.0),
                        "squeeze_recent": bool(row.get("squeeze_recent", False)),
                        "squeeze_active": bool(row.get("squeeze_active", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                        "atr14": atr,
                        "bb_upper": float(row.get("bb_upper") or 0.0),
                        "bb_lower": float(row.get("bb_lower") or 0.0),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("donchian_breakout.signals.generated")
        return out
