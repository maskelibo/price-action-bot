"""Wyckoff Phase D Accumulation/Distribution Strategy.

Strateji: Birikimin sonunda (Phase D) Spring + SOS sinyali ile long;
          Dağıtımın sonunda (Phase D) UTAD + SOW sinyali ile short.

Kural özeti (uzun taraf):
  - Phase B pre-koşulu : Fiyat >= 30 bar boyunca trading range içinde
                          (lookback bar low / high sabit kalıyor)
  - Phase C Spring      : Bar low, önceki 30-bar low'unu deler + 1-3 bar
                          içinde range içine kapanış (false breakdown)
  - Phase D SOS         : Spring sonrası (< 5 bar), body > 1.5 × ATR(14)
                          + volume z-score > 1.0 + kapanış range orta noktasının üstünde
  - Giriş               : SOS barının ARDINDAKİ bar açılışında
  - Stop                : Spring low altı (yapısal)
  - Hedef               : 3R (veya range yüksekliği, hangisi daha yakınsa)

Kısa taraf (UTAD + SOW): Tam simetrik tersine çevirme.

Bias filtresi: Uzun için 200-EMA üstü (trend dışı da açık bırakıldı opsiyonel).
kaufman_er_min: 0.15 (Wyckoff range'lerde trend daha yavaş — düşük eşik).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Shared helpers from classic_pa
from price_action.strategies.classic_pa import (
    _atr,
    _ema,
    _kaufman_efficiency_ratio,
)


# =====================================================================
# Yardımcı fonksiyonlar
# =====================================================================

def _vol_zscore(volume: pd.Series, window: int = 60) -> pd.Series:
    """Rolling volume z-score (lookahead-free)."""
    vmean = volume.rolling(window, min_periods=10).mean()
    vstd = volume.rolling(window, min_periods=10).std(ddof=0)
    return (volume - vmean) / vstd.replace(0, np.nan)


def _detect_spring(
    df: pd.DataFrame,
    lookback: int = 30,
) -> pd.Series:
    """Phase C Spring dedektörü.

    Kural (lookahead-free):
      t barında Spring = 1 eğer:
        - t barının low'u, [t-lookback .. t-1] aralığının minimum low'unun ALTINA iner
        - t veya (t+1 ya da t+2 ya da t+3) barlarından biri range low'unun ÜSTÜNDE kapanıyor

    Uygulamada lookahead olmadan:
      - Spring flag, t+3 tarihinde kesinleşir (reclaim teyidi için).
      - Fakat biz spring_idx serisini t+1 en erken bar olarak emit ediyoruz
        (t barı penetrasyon, t+1 bar ilk kapanış teyidi — 1-bar reclaim).
      - Daha geniş reclaim (2-3 bar) da kabul edilir, spring_idx = t+2 veya t+3.

    Döner: Her index konumunda Spring ONAYLANDI mi (1/0) boolean pd.Series.
    Spring indexi, reclaim barının indexidir (giriş kararı verildiği bar).

    ⚠️ WYK-001 (2026-05-15 Signal Chief audit): Bu fonksiyon `closes[t+k]`
    (k=1..3) future bar close kullanıyor — HARD FAIL lookahead. Spring flag
    reclaim_bar index'inde set ediliyor ama o index'in close'unu okumak için
    BAR KAPANIŞINI bekliyor — backtest engine flag'ı reclaim_bar açılışında
    kullanırsa fantasy alpha üretir. Ticket WYK-001 Engineering Chief sprint'inde
    causal versiyonla (Seçenek A same-bar VEYA Seçenek B 1-bar offset) replace
    edilecek + 6 test fixture causal data ile rewrite + replay re-baseline.
    Geçici güvenlik: configs/risk_balanced.yaml sat 149'da wyckoff_phase_d'yi
    Principal onayı ile production pool'dan disable etmek önerilir.
    """
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)

    # Her bar için önceki lookback barın min low'u
    # shift(1) ile t-1 dahil, rolling ile [t-lookback..t-1]
    range_low = df["low"].shift(1).rolling(lookback, min_periods=lookback // 2).min().to_numpy()
    range_high = df["high"].shift(1).rolling(lookback, min_periods=lookback // 2).max().to_numpy()

    spring_confirmed = np.zeros(n, dtype=bool)
    spring_low_arr = np.full(n, np.nan)  # Spring bar'ının low değeri

    for t in range(1, n):
        rl = range_low[t]
        rh = range_high[t]
        if np.isnan(rl) or np.isnan(rh):
            continue
        # Penetrasyon: t barının low'u range_low'un altına giriyor
        if lows[t] >= rl:
            continue
        # Reclaim: t+1, t+2, t+3 bar'larından biri range_low üstünde kapanıyor (1-3 bar pencere)
        for reclaim_offset in range(1, 4):
            reclaim_bar = t + reclaim_offset
            if reclaim_bar >= n:
                break
            if closes[reclaim_bar] > rl:
                # Spring confirmed at reclaim_bar
                spring_confirmed[reclaim_bar] = True
                spring_low_arr[reclaim_bar] = lows[t]  # Spring low = penetrasyon barının low
                break

    return (
        pd.Series(spring_confirmed, index=df.index, name="spring_confirmed"),
        pd.Series(spring_low_arr, index=df.index, name="spring_low"),
        pd.Series(range_low, index=df.index, name="range_low_30"),
        pd.Series(range_high, index=df.index, name="range_high_30"),
    )


def _detect_sos(
    df: pd.DataFrame,
    spring_confirmed: pd.Series,
    spring_low_series: pd.Series,
    range_mid: pd.Series,
    atr_mult: float = 1.5,
    vol_z_min: float = 1.0,
    lookback_spring: int = 5,
) -> pd.Series:
    """Phase D SOS (Sign of Strength) dedektörü.

    Kural (lookahead-free):
      SOS at bar t eğer:
        - Son lookback_spring bar içinde en az 1 Spring onaylandı
        - t barı bullish (close > open)
        - body (close - open) > atr_mult × ATR(14)
        - vol_z > vol_z_min
        - close > range_mid (range'in orta noktasının üstünde kapanış)

    Döner: Boolean pd.Series (SOS bar indexleri).
    """
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    atr = df["atr14"].to_numpy()
    vol_z = df["vol_z"].to_numpy()
    spring_arr = spring_confirmed.to_numpy()
    range_mid_arr = range_mid.to_numpy()
    n = len(df)

    sos_flags = np.zeros(n, dtype=bool)

    for t in range(lookback_spring, n):
        # Son lookback_spring bar içinde spring var mı?
        recent_spring = spring_arr[max(0, t - lookback_spring):t].any()
        if not recent_spring:
            continue

        # Bullish bar
        body = closes[t] - opens[t]
        if body <= 0:
            continue

        # Body > atr_mult × ATR
        atr_t = atr[t]
        if np.isnan(atr_t) or atr_t <= 0:
            continue
        if body < atr_mult * atr_t:
            continue

        # Volume z-score yeterli mi?
        vz = vol_z[t]
        if np.isnan(vz) or vz < vol_z_min:
            continue

        # Kapanış range midpoint üstünde mi?
        rm = range_mid_arr[t]
        if np.isnan(rm) or closes[t] <= rm:
            continue

        sos_flags[t] = True

    return pd.Series(sos_flags, index=df.index, name="sos_confirmed")


def _detect_utad(
    df: pd.DataFrame,
    lookback: int = 30,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Phase C UTAD (Upthrust After Distribution) dedektörü.

    Simetrik karşısı: Spring'in tam tersi.
    UTAD at reclaim_bar eğer:
      - t barının high'ı [t-lookback..t-1]'in max high'ını aşıyor
      - t+1, t+2 veya t+3 bar'larından biri range_high'ın altında kapanıyor

    ⚠️ WYK-001 (2026-05-15 Signal Chief audit): Bu fonksiyon `closes[t+k]`
    future bar close kullanıyor — _detect_spring ile aynı HARD FAIL.
    Engineering Chief sprint'inde causal versiyonla replace edilecek.
    """
    highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)

    range_low = df["low"].shift(1).rolling(lookback, min_periods=lookback // 2).min().to_numpy()
    range_high = df["high"].shift(1).rolling(lookback, min_periods=lookback // 2).max().to_numpy()

    utad_confirmed = np.zeros(n, dtype=bool)
    utad_high_arr = np.full(n, np.nan)

    for t in range(1, n):
        rl = range_low[t]
        rh = range_high[t]
        if np.isnan(rl) or np.isnan(rh):
            continue
        # Penetrasyon: t barının high'ı range_high'ın üzerine çıkıyor
        if highs[t] <= rh:
            continue
        # Reclaim: t+1, t+2, t+3 barlarından biri range_high altında kapanıyor
        for reclaim_offset in range(1, 4):
            reclaim_bar = t + reclaim_offset
            if reclaim_bar >= n:
                break
            if closes[reclaim_bar] < rh:
                utad_confirmed[reclaim_bar] = True
                utad_high_arr[reclaim_bar] = highs[t]  # UTAD high = penetrasyon barının high
                break

    return (
        pd.Series(utad_confirmed, index=df.index, name="utad_confirmed"),
        pd.Series(utad_high_arr, index=df.index, name="utad_high"),
        pd.Series(range_low, index=df.index, name="range_low_30"),
        pd.Series(range_high, index=df.index, name="range_high_30"),
    )


def _detect_sow(
    df: pd.DataFrame,
    utad_confirmed: pd.Series,
    utad_high_series: pd.Series,
    range_mid: pd.Series,
    atr_mult: float = 1.5,
    vol_z_min: float = 1.0,
    lookback_utad: int = 5,
) -> pd.Series:
    """Phase D SOW (Sign of Weakness) dedektörü.

    Simetrik karşısı: SOS'un tam tersi.
    SOW at bar t eğer:
      - Son lookback_utad bar içinde en az 1 UTAD onaylandı
      - t barı bearish (close < open)
      - body (open - close) > atr_mult × ATR
      - vol_z > vol_z_min
      - close < range_mid
    """
    opens = df["open"].to_numpy()
    closes = df["close"].to_numpy()
    atr = df["atr14"].to_numpy()
    vol_z = df["vol_z"].to_numpy()
    utad_arr = utad_confirmed.to_numpy()
    range_mid_arr = range_mid.to_numpy()
    n = len(df)

    sow_flags = np.zeros(n, dtype=bool)

    for t in range(lookback_utad, n):
        recent_utad = utad_arr[max(0, t - lookback_utad):t].any()
        if not recent_utad:
            continue

        body = opens[t] - closes[t]
        if body <= 0:
            continue

        atr_t = atr[t]
        if np.isnan(atr_t) or atr_t <= 0:
            continue
        if body < atr_mult * atr_t:
            continue

        vz = vol_z[t]
        if np.isnan(vz) or vz < vol_z_min:
            continue

        rm = range_mid_arr[t]
        if np.isnan(rm) or closes[t] >= rm:
            continue

        sow_flags[t] = True

    return pd.Series(sow_flags, index=df.index, name="sow_confirmed")


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "wyckoff_phase_d",
        "version": "1.0.0",
        "description": "Wyckoff Phase D accumulation/distribution — Spring+SOS long / UTAD+SOW short",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "wyckoff_long_sos",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 15,             # gevşetildi (30→15)
                        "atr_mult": 1.0,            # gevşetildi (1.5→1.0)
                        "vol_z_min": 0.5,           # gevşetildi (1.0→0.5)
                        "lookback_spring": 5,
                    },
                },
                {
                    "id": "wyckoff_short_sow",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 15,
                        "atr_mult": 1.0,
                        "vol_z_min": 0.5,
                        "lookback_utad": 5,
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
                "require_proximity_to_sr_atr": 0.0,  # Wyckoff'ta S/R yakınlığı zorunlu değil
            },
            "filters": {
                "atr_min_pct": 0.003,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,  # gevşetildi: range ortamlarında ER düşük olabilir
                "ema200_long_only": True,  # Uzun taraf için 200-EMA üstü bias
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "below_spring_low": True},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================

class WyckoffPhaseDStrategy(Strategy):
    """Wyckoff Phase D giriş stratejisi.

    Uzun taraf  : Spring (false breakdown) + SOS (güçlü hacimli yukarı bar)
    Kısa taraf  : UTAD (false breakout) + SOW (güçlü hacimli aşağı bar)
    Giriş       : SOS/SOW barının ERTESI bar açılışı
    Stop        : Spring low / UTAD high (yapısal)
    Hedef       : 3R veya range yüksekliği (hangisi yakınsa)
    Bias        : 200-EMA üstü = long tercih (kısa varsayılan: her iki yön)
    """

    name = "wyckoff_phase_d"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMAs
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR(14)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score (60-bar)
        df["vol_z"] = _vol_zscore(df["volume"], window=60)

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Lookback parametresi (default gevşetildi: 30 → 15)
        lookback = 15
        for p in self.manifest.signals.patterns:
            if p.id == "wyckoff_long_sos":
                lookback = int(p.params.get("lookback", 15))
                break

        # Spring dedektörü (uzun taraf)
        sc, sl, rl, rh = _detect_spring(df, lookback=lookback)
        df["spring_confirmed"] = sc
        df["spring_low"] = sl
        df["range_low_30"] = rl
        df["range_high_30"] = rh
        df["range_mid"] = (rl + rh) / 2.0

        # SOS dedektörü (uzun taraf)
        long_cfg = {}
        for p in self.manifest.signals.patterns:
            if p.id == "wyckoff_long_sos":
                long_cfg = p.params
                break
        df["sos_confirmed"] = _detect_sos(
            df,
            spring_confirmed=df["spring_confirmed"],
            spring_low_series=df["spring_low"],
            range_mid=df["range_mid"],
            atr_mult=float(long_cfg.get("atr_mult", 1.5)),
            vol_z_min=float(long_cfg.get("vol_z_min", 1.0)),
            lookback_spring=int(long_cfg.get("lookback_spring", 5)),
        )

        # UTAD dedektörü (kısa taraf)
        utad_lookback = lookback
        for p in self.manifest.signals.patterns:
            if p.id == "wyckoff_short_sow":
                utad_lookback = int(p.params.get("lookback", lookback))
                break
        uc, uh, _, _ = _detect_utad(df, lookback=utad_lookback)
        df["utad_confirmed"] = uc
        df["utad_high"] = uh

        # SOW dedektörü (kısa taraf)
        short_cfg = {}
        for p in self.manifest.signals.patterns:
            if p.id == "wyckoff_short_sow":
                short_cfg = p.params
                break
        df["sow_confirmed"] = _detect_sow(
            df,
            utad_confirmed=df["utad_confirmed"],
            utad_high_series=df["utad_high"],
            range_mid=df["range_mid"],
            atr_mult=float(short_cfg.get("atr_mult", 1.5)),
            vol_z_min=float(short_cfg.get("vol_z_min", 1.0)),
            lookback_utad=int(short_cfg.get("lookback_utad", 5)),
        )

        # Spring low forward-fill: en son geçerli spring low değerini koruyoruz
        # SOS barında spring_low NaN olabilir, o yüzden forward-fill
        df["spring_low_fill"] = df["spring_low"].ffill()
        df["utad_high_fill"] = df["utad_high"].ffill()

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "sos_confirmed" not in df.columns:
            df = self.prepare_features(df)

        filters_cfg = self.manifest.signals.filters
        risk_cfg = self.manifest.risk

        primary_R = float(risk_cfg.get("take_profit", {}).get("primary_R", 3.0))
        er_min = float(getattr(filters_cfg, "kaufman_er_min", 0.15) or 0.0)
        atr_min_pct = float(getattr(filters_cfg, "atr_min_pct", 0.003) or 0.0)
        ema200_long_only = bool(getattr(filters_cfg, "ema200_long_only", True))

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        out: list[Signal] = []

        # SOS sinyali: t+1 açılışında long (t = SOS bar)
        # SOW sinyali: t+1 açılışında short (t = SOW bar)
        # Not: generate_signals bar-by-bar değil, toplu çalışır.
        # "Giriş t+1 açılışında" demek: sinyali t barında emit ediyoruz,
        # engine t+1 açılışta çalıştırıyor.

        closes = df["close"].to_numpy()
        opens = df["open"].to_numpy()
        atr = df["atr14"].to_numpy()
        atr_pct = df["atr_pct"].to_numpy()
        vol_z = df["vol_z"].to_numpy()
        kaufman_er = df["kaufman_er"].to_numpy()
        ema200 = df["ema200"].to_numpy()
        sos_arr = df["sos_confirmed"].to_numpy()
        sow_arr = df["sow_confirmed"].to_numpy()
        spring_low_fill = df["spring_low_fill"].to_numpy()
        utad_high_fill = df["utad_high_fill"].to_numpy()
        range_low = df["range_low_30"].to_numpy()
        range_high = df["range_high_30"].to_numpy()
        range_mid = df["range_mid"].to_numpy()

        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            close = float(closes[i])
            atr_i = float(atr[i])
            if atr_i <= 0 or np.isnan(atr_i):
                continue

            # ATR min filtresi
            if atr_min_pct > 0 and float(atr_pct[i]) < atr_min_pct:
                continue

            # Kaufman ER filtresi
            if er_min > 0 and float(kaufman_er[i]) < er_min:
                continue

            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            # --- LONG: SOS sinyali ---
            if sos_arr[i]:
                # 200-EMA bias filtresi (opsiyonel)
                if ema200_long_only and not np.isnan(ema200[i]) and close < ema200[i]:
                    pass  # filtrele — uzun sinyal yok
                else:
                    # Stop: Spring low altı (en son geçerli spring low)
                    spr_low = float(spring_low_fill[i])
                    if np.isnan(spr_low) or spr_low <= 0:
                        spr_low = float(range_low[i]) if not np.isnan(range_low[i]) else (close - 2.0 * atr_i)
                    # Stop biraz altına yerleştir (buffer)
                    sl_price = spr_low - 0.1 * atr_i
                    sl_price = min(sl_price, close - 0.5 * atr_i)  # en az 0.5 ATR uzakta
                    risk = close - sl_price

                    # Hedef: min(3R, range yüksekliği)
                    rh = float(range_high[i])
                    range_target = rh if not np.isnan(rh) else (close + 3.0 * risk)
                    tp_3r = close + primary_R * risk
                    tp_price = min(tp_3r, range_target) if range_target > close else tp_3r

                    sig = self.emit_signal(
                        ts=ts,
                        venue=venue,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction="long",
                        pattern_id="wyckoff_long_sos",
                        confluence_score=2.0,
                        sl_price=float(sl_price),
                        tp_price=float(tp_price),
                        suggested_size_atr=1.0,
                        metadata={
                            "spring_low": spr_low,
                            "range_low": float(range_low[i]),
                            "range_high": float(range_high[i]) if not np.isnan(range_high[i]) else 0.0,
                            "range_mid": float(range_mid[i]) if not np.isnan(range_mid[i]) else 0.0,
                            "vol_z": float(vol_z[i]),
                            "atr14": atr_i,
                            "kaufman_er": float(kaufman_er[i]),
                            "ema200": float(ema200[i]) if not np.isnan(ema200[i]) else 0.0,
                        },
                    )
                    out.append(sig)

            # --- SHORT: SOW sinyali ---
            if sow_arr[i]:
                utad_h = float(utad_high_fill[i])
                if np.isnan(utad_h) or utad_h <= 0:
                    utad_h = float(range_high[i]) if not np.isnan(range_high[i]) else (close + 2.0 * atr_i)
                sl_price = utad_h + 0.1 * atr_i
                sl_price = max(sl_price, close + 0.5 * atr_i)
                risk = sl_price - close

                rl = float(range_low[i])
                range_target = rl if not np.isnan(rl) else (close - 3.0 * risk)
                tp_3r = close - primary_R * risk
                tp_price = max(tp_3r, range_target) if range_target < close else tp_3r

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="wyckoff_short_sow",
                    confluence_score=2.0,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "utad_high": utad_h,
                        "range_low": float(range_low[i]) if not np.isnan(range_low[i]) else 0.0,
                        "range_high": float(range_high[i]) if not np.isnan(range_high[i]) else 0.0,
                        "range_mid": float(range_mid[i]) if not np.isnan(range_mid[i]) else 0.0,
                        "vol_z": float(vol_z[i]),
                        "atr14": atr_i,
                        "kaufman_er": float(kaufman_er[i]),
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("wyckoff_phase_d.signals.generated")
        return out
