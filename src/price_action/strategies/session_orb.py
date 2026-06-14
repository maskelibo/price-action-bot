"""Session Opening Range Breakout (ORB) — 00:00 UTC anchored intraday momentum.

Mekanizma (vsa_climax_test'in fade'inden YAPISAL olarak farkli):
  - vsa_climax_test = kapitulasyon/climax FADE (mean-reversion).
  - session_orb       = gun-aci range KIRILIM momentum (trend-burst continuation).

Bu yapisal fark sayesinde sinyaller farkli zamanlarda ve farkli rejim
kosullarinda atesler -> dusuk korelasyon hipotezi.

Kurallar (Trade-That-Swing / QuantifiedStrategies ORB tarifi, kripto adaptasyonu):
  - Session anchor: 00:00 UTC (kripto 24/7 -> gun acilisi referans).
  - Opening Range (OR): gunun ilk `or_bars` 15m bari -> OR_high / OR_low.
  - Long sinyal : bar CLOSE > OR_high (OR penceresi KAPANDIKTAN sonra),
                  RVOL >= rvol_min, ATR_pct >= atr_min, gun-ici ilk kirilim.
  - Short sinyal: bar CLOSE < OR_low (simetrik).
  - Cutoff: gunun son `cutoff_frac` kismindan sonra yeni giris yok
            (gec-seans whipsaw'i ele).
  - Giris : sinyal barindan SONRAKI bar acilisi (engine t+1 open) — causal.
  - SL    : long -> OR_low (ATR tabani ile), short -> OR_high.
  - TP    : primary_R * risk.

LOOKAHEAD GUVENLIGI (kanit):
  - OR_high/OR_low yalnizca pencere KAPANDIKTAN sonra (bar pozisyonu >= or_bars)
    gorunur kilinir; pencere ici barlarda NaN -> o barlarda sinyal uretilemez.
  - OR degerleri o-ana-kadar (cumulative within-day, sadece tamamlanmis OR
    barlari) hesaplanir; gelecek bar kullanilmaz. shift(-1) / center=True YOK.
  - Sinyal bar t'nin KENDI close'u ile dogrular; giris engine tarafindan
    t+1 open'da yapilir (vsa ile ayni execution semantik).
  - RVOL = volume / rolling(vol_lookback).mean().shift(1) -> shift(1) ile
    su anki bar hacmi ortalamaya dahil DEGIL (causal).

Referans:
  - https://www.quantifiedstrategies.com/opening-range-breakout-strategy/
  - https://tradethatswing.com/opening-range-breakout-strategy-up-400-this-year/
Sablon: src/price_action/strategies/donchian_breakout.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Vektorize OR hesabi (lookahead-safe)
# =====================================================================

def _compute_session_orb(
    df: pd.DataFrame,
    *,
    bars_per_day: int = 96,    # 96 × 15m = 24h
    or_bars: int = 4,          # ilk 1 saat (4 × 15m)
) -> pd.DataFrame:
    """Her bar icin gun-aci OR_high/OR_low + within-day bar indeksi ekler.

    Lookahead-safe:
      - day_id = ts'nin UTC gunu (groupby anahtari).
      - bar_in_day = gun-ici siralama (0-based).
      - OR_high/OR_low = SADECE bar_in_day < or_bars olan barlardan,
        ve sadece bar_in_day >= or_bars iken gorunur (oncesinde NaN).
      - Hesap o gunun ilk or_bars bari KAPANDIKTAN sonra sabittir
        (gelecek bilgisi yok).

    Dondurur: df + ['or_high','or_low','bar_in_day']
    """
    out = df.copy()
    ts = pd.to_datetime(out["ts"], utc=True)
    # Gun anahtari (00:00 UTC anchor)
    day_id = ts.dt.floor("D")
    out["_day_id"] = day_id.values

    # Gun-ici 0-based sira
    out["bar_in_day"] = out.groupby("_day_id").cumcount()

    # OR penceresi maskesi
    in_or = out["bar_in_day"] < or_bars

    # OR_high/OR_low: gun-ici, sadece OR barlarindan running max/min.
    # cummax/cummin within-day -> her bar icin "su ana kadarki OR" degeri;
    # OR penceresi disindaki barlarin high/low'u OR hesabina KATILMAZ
    # (NaN'a maskeleyerek). bar_in_day >= or_bars iken bu deger sabitlenir.
    or_high_src = out["high"].where(in_or, other=-np.inf)
    or_low_src = out["low"].where(in_or, other=np.inf)

    out["or_high"] = or_high_src.groupby(out["_day_id"]).cummax()
    out["or_low"] = or_low_src.groupby(out["_day_id"]).cummin()

    # OR penceresi henuz kapanmadiysa (bar_in_day < or_bars) OR'u gizle (NaN).
    # Bu sayede pencere ici barlarda sinyal uretilemez (causal).
    mask_window_open = out["bar_in_day"] < or_bars
    out.loc[mask_window_open, "or_high"] = np.nan
    out.loc[mask_window_open, "or_low"] = np.nan
    # -inf/inf temizligi (OR'da hic bar yoksa)
    out["or_high"] = out["or_high"].replace([np.inf, -np.inf], np.nan)
    out["or_low"] = out["or_low"].replace([np.inf, -np.inf], np.nan)

    out = out.drop(columns=["_day_id"])
    return out


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "session_orb",
        "version": "1.0.0",
        "description": "Session Opening Range Breakout — 00:00 UTC anchored intraday momentum.",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "orb_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "or_bars": 4,
                        "bars_per_day": 96,
                        "rvol_min": 1.3,
                        "vol_lookback": 96,
                        "cutoff_frac": 0.75,
                    },
                },
            ],
            "filters": {"atr_min_pct": 0.003},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "stop_loss": {"method": "or_opposite", "atr_buffer": 0.0},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
        "backtest": {
            "warmup_bars": 96,
            "fees": {"taker": 0.00075, "maker": -0.00010},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10_000.0,
        },
    }
    return StrategyManifest.model_validate(raw)


class SessionORBStrategy(Strategy):
    """Session Opening Range Breakout (long+short)."""

    name = "session_orb"

    def _params(self) -> dict:
        for p in self.manifest.signals.patterns:
            if p.id == "orb_long":
                return dict(p.params)
        return {}

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        self.apply_tf_manifest(df)
        df = df.sort_values("ts").reset_index(drop=True).copy()

        p = self._params()
        or_bars = int(p.get("or_bars", 4))
        bars_per_day = int(p.get("bars_per_day", 96))
        vol_lookback = int(p.get("vol_lookback", 96))

        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # RVOL: causal — su anki bar hacmi ortalamaya dahil edilmez (shift(1)).
        vol_ma = df["volume"].rolling(vol_lookback, min_periods=max(1, vol_lookback // 2)).mean().shift(1)
        df["rvol"] = df["volume"] / vol_ma.replace(0, np.nan)

        df = _compute_session_orb(df, bars_per_day=bars_per_day, or_bars=or_bars)
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "or_high" not in df.columns:
            df = self.prepare_features(df)

        p = self._params()
        or_bars = int(p.get("or_bars", 4))
        bars_per_day = int(p.get("bars_per_day", 96))
        rvol_min = float(p.get("rvol_min", 1.3))
        cutoff_frac = float(p.get("cutoff_frac", 0.75))

        primary_R = float(self.manifest.risk.get("take_profit", {}).get("primary_R", 1.5))
        atr_buffer = float(self.manifest.risk.get("stop_loss", {}).get("atr_buffer", 0.0))
        atr_min = float(getattr(self.manifest.signals.filters, "atr_min_pct", 0.003) or 0.003)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "15m"

        close = df["close"]
        or_high = df["or_high"]
        or_low = df["or_low"]
        rvol = df["rvol"].fillna(0.0)
        atr_pct = df["atr_pct"].fillna(0.0)
        bar_in_day = df["bar_in_day"]

        cutoff_bar = int(cutoff_frac * bars_per_day)

        # Vektorel kosullar (hepsi t barinin KENDI verisi -> causal)
        window_closed = bar_in_day >= or_bars
        before_cutoff = bar_in_day <= cutoff_bar
        rvol_ok = rvol >= rvol_min
        atr_ok = atr_pct >= atr_min

        long_brk = (close > or_high.fillna(np.inf)) & window_closed & before_cutoff & rvol_ok & atr_ok & or_high.notna()
        short_brk = (close < or_low.fillna(-np.inf)) & window_closed & before_cutoff & rvol_ok & atr_ok & or_low.notna()

        # Gun-ici ILK kirilim (her gun her yon icin tek sinyal).
        # day_id'yi tekrar uret (prepare_features icinde drop edildi).
        ts = pd.to_datetime(df["ts"], utc=True)
        day_id = ts.dt.floor("D")
        # cumsum > 1 olanlari ele (gun-ici sonraki kirilimlar)
        long_first = long_brk & (long_brk.groupby(day_id).cumsum() == 1)
        short_first = short_brk & (short_brk.groupby(day_id).cumsum() == 1)

        atr14 = df["atr14"].fillna(0.0)
        out: list[Signal] = []

        for i in range(len(df)):
            atr = float(atr14.iat[i])
            if atr <= 0 or np.isnan(atr):
                continue
            entry_close = float(close.iat[i])

            if bool(long_first.iat[i]):
                orl = float(or_low.iat[i])
                sl_raw = orl - atr_buffer * atr if not np.isnan(orl) else entry_close - 1.0 * atr
                sl_price = min(sl_raw, entry_close - 0.5 * atr)
                risk = entry_close - sl_price
                if risk <= 0:
                    continue
                tp_price = entry_close + primary_R * risk
                ts_i = pd.Timestamp(df["ts"].iat[i]).to_pydatetime()
                out.append(self.emit_signal(
                    ts=ts_i, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="long", pattern_id="orb_long", confluence_score=1.0,
                    sl_price=float(sl_price), tp_price=float(tp_price), suggested_size_atr=1.0,
                    metadata={"or_high": float(or_high.iat[i]), "or_low": orl, "atr14": atr,
                              "entry_close": entry_close, "rvol": float(rvol.iat[i])},
                ))

            if bool(short_first.iat[i]):
                orh = float(or_high.iat[i])
                sl_raw = orh + atr_buffer * atr if not np.isnan(orh) else entry_close + 1.0 * atr
                sl_price = max(sl_raw, entry_close + 0.5 * atr)
                risk = sl_price - entry_close
                if risk <= 0:
                    continue
                tp_price = entry_close - primary_R * risk
                ts_i = pd.Timestamp(df["ts"].iat[i]).to_pydatetime()
                out.append(self.emit_signal(
                    ts=ts_i, venue=venue, symbol=symbol, timeframe=timeframe,
                    direction="short", pattern_id="orb_short", confluence_score=1.0,
                    sl_price=float(sl_price), tp_price=float(tp_price), suggested_size_atr=1.0,
                    metadata={"or_high": orh, "or_low": float(or_low.iat[i]), "atr14": atr,
                              "entry_close": entry_close, "rvol": float(rvol.iat[i])},
                ))

        self._log.bind(n=len(out), bars=len(df)).info("session_orb.signals.generated")
        return out
