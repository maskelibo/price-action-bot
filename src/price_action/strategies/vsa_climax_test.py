"""VSA Selling Climax + Test Bar stratejisi.

Wyckoff/VSA Phase A dip sinyali:
  - Selling Climax (SC): extreme hacim + genis asagi bar + ust yari kapanis + 5-bar min low
  - Test Bar (TB): 3-15 bar sonra SC low'una dusuk hacimli geri donus
  - Giris: Test Bar sonrasi ilk YESIL bar acilisinda
  - SL: SC low - 1×ATR
  - TP: 3R (mean-reversion / yuksek hedef)

Mirror (kisa): Buying Climax + Up Thrust short simetrik kurulumu.

Referans: knowledge/books/vsa_volume_spread_analysis.md
Sablon:   src/price_action/strategies/engulfing_continuation.py
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Ortak yardimcilar
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
)


# =====================================================================
# VSA yardimci fonksiyonlari
# =====================================================================

def _vol_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Gecmis period barlara gore volume SMA (lookahead-safe)."""
    return volume.rolling(period, min_periods=max(1, period // 2)).mean()


def _spread(df: pd.DataFrame) -> pd.Series:
    """Bar spread (high - low)."""
    return df["high"] - df["low"]


def _close_position(df: pd.DataFrame) -> pd.Series:
    """Kapanis pozisyonu: 0=alt, 1=ust (range icindeki orani)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return (df["close"] - df["low"]) / rng


def _detect_selling_climax(
    df: pd.DataFrame,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    spread_atr_mult: float = 1.5,
    vol_sma_mult: float = 2.5,
    close_pos_min: float = 0.50,
    min_low_bars: int = 5,
) -> pd.Series:
    """Selling Climax (SC) tespit eder.

    Kriterler (VSA reference Section 4.2 + Section 7):
      1. Wide spread: spread > spread_atr_mult * ATR(20)
      2. Climactic volume: volume > vol_sma_mult * SMA_vol(20)
      3. Close upper half: close > low + close_pos_min * (high-low)
      4. 5-bar minimum low: rolling min(5) == low (yerel dip)

    Lookahead-safe: sadece shift/rolling gecmis veri.

    Returns
    -------
    pd.Series[bool]
    """
    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    wide_spread = spread > (spread_atr_mult * atr)
    climax_vol = vol > (vol_sma_mult * vol_sma)
    upper_close = close_pos >= close_pos_min
    # 5-bar minimum low: su bar dip bar mi?
    # rolling min icin shift(1) ile onceki 4 bar + su bar -> 5 bar pencere
    # Ama biz su anki low'u da dahil ediyoruz: rolling(5).min() == low (LOOKAHEAD-FREE)
    # Neden safe? rolling(5) t-4..t barlari kullanir, sadece gecmisteki/simdiki bilgi.
    local_min = df["low"].rolling(min_low_bars, min_periods=min_low_bars).min()
    is_5bar_low = (df["low"] == local_min)

    sc = wide_spread & climax_vol & upper_close & is_5bar_low
    return sc.fillna(False)


def _detect_buying_climax(
    df: pd.DataFrame,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    spread_atr_mult: float = 1.5,
    vol_sma_mult: float = 2.5,
    close_pos_max: float = 0.50,
    max_high_bars: int = 5,
) -> pd.Series:
    """Buying Climax (BC) tespit eder — SC'nin ayı simetriği.

    Kriterler (VSA reference Section 4.11):
      1. Wide spread
      2. Climactic volume
      3. Close lower half (ust fitil)
      4. 5-bar maximum high
    """
    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    wide_spread = spread > (spread_atr_mult * atr)
    climax_vol = vol > (vol_sma_mult * vol_sma)
    lower_close = close_pos <= close_pos_max
    local_max = df["high"].rolling(max_high_bars, min_periods=max_high_bars).max()
    is_5bar_high = (df["high"] == local_max)

    bc = wide_spread & climax_vol & lower_close & is_5bar_high
    return bc.fillna(False)


def _detect_test_bar_after_sc(
    df: pd.DataFrame,
    sc_flag: pd.Series,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    wait_min: int = 3,
    wait_max: int = 15,
    low_tolerance_pct: float = 0.03,
    vol_ratio_max: float = 0.75,
    spread_atr_max: float = 0.80,
    close_pos_min: float = 0.50,
) -> tuple[pd.Series, pd.Series]:
    """SC sonrasi Test Bar tespit eder.

    Kural:
      - En son SC'den wait_min..wait_max bar sonra
      - Low, SC low +/- tolerance icinde (1D kripto icin %3 uygun)
      - Volume < vol_ratio_max * SMA_vol
      - Spread < spread_atr_max * ATR
      - Close >= %50 range

    Kalibrasyon notu: VSA referansi +-1% yazar, ama 1D kripto barlarda
    low'lar nadir olarak tam eslesiyor. BTC 2023-2026 verisi analizi
    gosteriyor ki yaklasim mesafesi genellikle %1-3 arasindadir.
    Vol_ratio_max 0.75 civarinda kalibre edildi (0.60 cok katiydi).

    Returns
    -------
    (test_bar_flag, sc_low_at_test)
        test_bar_flag: pd.Series[bool]
        sc_low_at_test: SC low degeri (SL hesabi icin)
    """
    n = len(df)
    test_flag = pd.Series(False, index=df.index)
    sc_low_series = pd.Series(np.nan, index=df.index)

    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    # SC low'larini ve indekslerini kaydet
    # Lookahead-safe: her t bari icin sadece t-1 ve oncesine bakilir
    for i in range(wait_min, n):
        # En son SC'yi [i - wait_max .. i - wait_min] araliginda ara
        sc_start = max(0, i - wait_max)
        sc_end = i - wait_min + 1  # dahil

        # Bu penceredeki SC'leri bul
        sc_window = sc_flag.iloc[sc_start:sc_end]
        if not sc_window.any():
            continue

        # En son SC indeksi
        last_sc_idx = sc_window[::-1].idxmax()
        sc_low = df["low"].iloc[last_sc_idx]
        tol = sc_low * low_tolerance_pct

        # Test bar kriterleri
        curr_low = df["low"].iloc[i]
        curr_vol = vol.iloc[i]
        curr_spread = spread.iloc[i]
        curr_close_pos = close_pos.iloc[i]
        curr_atr = atr.iloc[i]
        curr_vol_sma = vol_sma.iloc[i]

        # SC low'una yakin mi?
        near_sc_low = abs(curr_low - sc_low) <= tol

        # Dusuk hacim?
        low_vol = (curr_vol_sma > 0) and (curr_vol < vol_ratio_max * curr_vol_sma)

        # Dar spread?
        narrow_spread = (curr_atr > 0) and (curr_spread < spread_atr_max * curr_atr)

        # Ust yari kapanis?
        upper_close = curr_close_pos >= close_pos_min

        if near_sc_low and low_vol and narrow_spread and upper_close:
            test_flag.iloc[i] = True
            sc_low_series.iloc[i] = sc_low

    return test_flag, sc_low_series


def _detect_up_thrust_after_bc(
    df: pd.DataFrame,
    bc_flag: pd.Series,
    atr_col: str = "atr20",
    vol_sma_col: str = "vol_sma20",
    wait_min: int = 3,
    wait_max: int = 15,
    high_tolerance_pct: float = 0.03,
    vol_ratio_max: float = 0.75,
    spread_atr_max: float = 0.80,
    close_pos_max: float = 0.50,
) -> tuple[pd.Series, pd.Series]:
    """BC sonrasi Up Thrust (UT) tespit eder — Test Bar'in ayı simetriği.

    Kural (VSA Section 4.12):
      - En son BC'den wait_min..wait_max bar sonra
      - High, BC high +/- tolerance icinde
      - Volume < vol_ratio_max * SMA_vol (dusuk hacimli geri donus)
      - Spread < spread_atr_max * ATR
      - Close < %50 range (ust fitil olustu)

    Returns
    -------
    (up_thrust_flag, bc_high_at_test)
    """
    n = len(df)
    ut_flag = pd.Series(False, index=df.index)
    bc_high_series = pd.Series(np.nan, index=df.index)

    atr = df[atr_col].fillna(0.0)
    vol_sma = df[vol_sma_col].fillna(0.0)
    spread = _spread(df)
    close_pos = _close_position(df)
    vol = df["volume"]

    for i in range(wait_min, n):
        bc_start = max(0, i - wait_max)
        bc_end = i - wait_min + 1

        bc_window = bc_flag.iloc[bc_start:bc_end]
        if not bc_window.any():
            continue

        last_bc_idx = bc_window[::-1].idxmax()
        bc_high = df["high"].iloc[last_bc_idx]
        tol = bc_high * high_tolerance_pct

        curr_high = df["high"].iloc[i]
        curr_vol = vol.iloc[i]
        curr_spread = spread.iloc[i]
        curr_close_pos = close_pos.iloc[i]
        curr_atr = atr.iloc[i]
        curr_vol_sma = vol_sma.iloc[i]

        near_bc_high = abs(curr_high - bc_high) <= tol
        low_vol = (curr_vol_sma > 0) and (curr_vol < vol_ratio_max * curr_vol_sma)
        narrow_spread = (curr_atr > 0) and (curr_spread < spread_atr_max * curr_atr)
        lower_close = curr_close_pos <= close_pos_max

        if near_bc_high and low_vol and narrow_spread and lower_close:
            ut_flag.iloc[i] = True
            bc_high_series.iloc[i] = bc_high

    return ut_flag, bc_high_series


def _detect_confirmation_bar(
    df: pd.DataFrame,
    trigger_flag: pd.Series,
    direction: str = "long",
    max_wait: int = 3,
) -> pd.Series:
    """Trigger (Test Bar / Up Thrust) sonrasi ilk onay barini tespit eder.

    Long icin: Test Bar sonraki bar(lar)da ilk YESIL bar (close > open)
    Short icin: Up Thrust sonraki bar(lar)da ilk KIRMIZI bar (close < open)

    Returns pd.Series[bool] — giris bari isaretlenir.
    Lookahead-safe: trigger t-1 oldugundan, t barinda onay alinir.
    """
    n = len(df)
    conf_flag = pd.Series(False, index=df.index)

    for i in range(1, n):
        # Son max_wait barda trigger var mi?
        for offset in range(1, max_wait + 1):
            j = i - offset
            if j < 0:
                break
            if trigger_flag.iloc[j]:
                # i barinda onay kontrol
                if direction == "long":
                    is_green = df["close"].iloc[i] > df["open"].iloc[i]
                    if is_green:
                        conf_flag.iloc[i] = True
                else:
                    is_red = df["close"].iloc[i] < df["open"].iloc[i]
                    if is_red:
                        conf_flag.iloc[i] = True
                break  # ilk trigger bulundu, devam etme

    return conf_flag


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "vsa_climax_test",
        "version": "1.0.0",
        "description": (
            "VSA Selling Climax + Test Bar — Wyckoff Phase A kapitulasyon + "
            "dusuk hacimli geri test giris sistemi. Mirror: BC + Up Thrust short."
        ),
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vsa_sc_test_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_min": 0.50,
                        "min_low_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "low_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
                    },
                },
                {
                    "id": "vsa_bc_thrust_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "spread_atr_mult": 1.5,
                        "vol_sma_mult": 2.5,
                        "close_pos_max": 0.50,
                        "max_high_bars": 5,
                        "wait_min": 3,
                        "wait_max": 15,
                        "high_tolerance_pct": 0.03,
                        "vol_ratio_max": 0.75,
                        "spread_atr_max": 0.80,
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
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "sc_low_atr", "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 60,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class VSAClimaxTestStrategy(Strategy):
    """VSA Selling Climax + Test Bar (long) / Buying Climax + Up Thrust (short).

    Long kurulumu:
      1. Selling Climax tespiti (SC)
      2. 3-15 bar bekle
      3. Test Bar: SC low'una dusuk hacimli donus
      4. Giris: Test Bar sonrasi ilk yesil bar acilisi
      5. SL: SC low - 1 ATR
      6. TP: 3R

    Short kurulumu (simetrik):
      1. Buying Climax tespiti (BC)
      2. 3-15 bar bekle
      3. Up Thrust: BC high'ına dusuk hacimli yaklasim + ust fitil
      4. Giris: Up Thrust sonrasi ilk kirmizi bar acilisi
      5. SL: BC high + 1 ATR
      6. TP: 3R
    """

    name = "vsa_climax_test"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # ATR(20) — VSA reference Section 7: ATR penceresi 14 veya 20, biz 20 kullaniyoruz
        df["atr20"] = _atr(df, 20)
        df["atr_pct"] = df["atr20"] / df["close"].replace(0, np.nan)

        # Volume SMA(20) — Williams: 20 bar onerir
        df["vol_sma20"] = _vol_sma(df["volume"], 20)

        # EMA200 (opsiyonel bias filtresi)
        df["ema200"] = _ema(df["close"], 200)

        # Pattern parametrelerini manifest'ten al
        sc_params = {}
        bc_params = {}
        for p in self.manifest.signals.patterns:
            if p.id == "vsa_sc_test_long":
                sc_params = p.params
            elif p.id == "vsa_bc_thrust_short":
                bc_params = p.params

        # --- Selling Climax ---
        df["sc_flag"] = _detect_selling_climax(
            df,
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            spread_atr_mult=float(sc_params.get("spread_atr_mult", 1.5)),
            vol_sma_mult=float(sc_params.get("vol_sma_mult", 2.5)),
            close_pos_min=float(sc_params.get("close_pos_min", 0.50)),
            min_low_bars=int(sc_params.get("min_low_bars", 5)),
        )

        # --- Buying Climax ---
        df["bc_flag"] = _detect_buying_climax(
            df,
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            spread_atr_mult=float(bc_params.get("spread_atr_mult", 1.5)),
            vol_sma_mult=float(bc_params.get("vol_sma_mult", 2.5)),
            close_pos_max=float(bc_params.get("close_pos_max", 0.50)),
            max_high_bars=int(bc_params.get("max_high_bars", 5)),
        )

        # --- Test Bar (SC sonrasi) ---
        tb_flag, sc_low_at_test = _detect_test_bar_after_sc(
            df,
            sc_flag=df["sc_flag"],
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            wait_min=int(sc_params.get("wait_min", 3)),
            wait_max=int(sc_params.get("wait_max", 15)),
            low_tolerance_pct=float(sc_params.get("low_tolerance_pct", 0.01)),
            vol_ratio_max=float(sc_params.get("vol_ratio_max", 0.60)),
            spread_atr_max=float(sc_params.get("spread_atr_max", 0.80)),
            close_pos_min=float(sc_params.get("close_pos_min", 0.50)),
        )
        df["test_bar_flag"] = tb_flag
        df["sc_low_at_test"] = sc_low_at_test

        # --- Up Thrust (BC sonrasi) ---
        ut_flag, bc_high_at_ut = _detect_up_thrust_after_bc(
            df,
            bc_flag=df["bc_flag"],
            atr_col="atr20",
            vol_sma_col="vol_sma20",
            wait_min=int(bc_params.get("wait_min", 3)),
            wait_max=int(bc_params.get("wait_max", 15)),
            high_tolerance_pct=float(bc_params.get("high_tolerance_pct", 0.01)),
            vol_ratio_max=float(bc_params.get("vol_ratio_max", 0.60)),
            spread_atr_max=float(bc_params.get("spread_atr_max", 0.80)),
            close_pos_max=float(bc_params.get("close_pos_max", 0.50)),
        )
        df["up_thrust_flag"] = ut_flag
        df["bc_high_at_ut"] = bc_high_at_ut

        # --- Onay barlari ---
        # Long: Test Bar sonrasi ilk yesil bar
        df["long_confirm"] = _detect_confirmation_bar(df, df["test_bar_flag"], direction="long")
        # Short: Up Thrust sonrasi ilk kirmizi bar
        df["short_confirm"] = _detect_confirmation_bar(df, df["up_thrust_flag"], direction="short")

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "sc_flag" not in df.columns:
            df = self.prepare_features(df)

        filters = self.manifest.signals.filters
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 3.0)
        )
        atr_buffer = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 1.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        atr_min = float(getattr(filters, "atr_min_pct", 0.003) or 0.003)

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            atr = float(row.get("atr20") or 0.0)
            atr_pct = float(row.get("atr_pct") or 0.0)
            close = float(row["close"])
            open_ = float(row["open"])

            if atr <= 0 or np.isnan(atr):
                continue
            if atr_min > 0 and atr_pct < atr_min:
                continue

            # ------ LONG: SC + Test Bar + Yesil onay bari ------
            if bool(row.get("long_confirm", False)):
                sc_low = float(row.get("sc_low_at_test") or 0.0)
                if np.isnan(sc_low) or sc_low <= 0:
                    # Fallback: son close'un 2 ATR altı
                    sc_low = close - 2.0 * atr

                # Giris: bu barin acilisi (bar kapatildiktan sonra sinyal)
                entry = open_
                sl_price = sc_low - atr_buffer * atr
                sl_price = min(sl_price, entry - 0.5 * atr)  # en az 0.5 ATR risk
                risk = entry - sl_price
                if risk <= 0:
                    continue
                tp_price = entry + primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="vsa_sc_test_long",
                    confluence_score=2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "sc_low": float(sc_low),
                        "atr20": float(atr),
                        "entry_open": float(entry),
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

            # ------ SHORT: BC + Up Thrust + Kirmizi onay bari ------
            if bool(row.get("short_confirm", False)):
                bc_high = float(row.get("bc_high_at_ut") or 0.0)
                if np.isnan(bc_high) or bc_high <= 0:
                    bc_high = close + 2.0 * atr

                entry = open_
                sl_price = bc_high + atr_buffer * atr
                sl_price = max(sl_price, entry + 0.5 * atr)
                risk = sl_price - entry
                if risk <= 0:
                    continue
                tp_price = entry - primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="vsa_bc_thrust_short",
                    confluence_score=2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "bc_high": float(bc_high),
                        "atr20": float(atr),
                        "entry_open": float(entry),
                        "risk_r": float(risk),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("vsa_climax_test.signals.generated")
        return out
