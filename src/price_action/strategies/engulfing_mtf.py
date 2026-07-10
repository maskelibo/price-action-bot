"""Engulfing Multi-Timeframe (MTF) Confluence stratejisi.

Hipotez: 1d engulfing_continuation + 4h Brooks always-in flip teyidi.

Kural ozeti:
  - 1d engulfing_continuation sinyali tetiklenir (parent strateji kurallari).
  - 1d sinyal aninda, geriye donuk son N 4h barinda (default 4-6) ayni yonde
    Brooks 'always-in flip' kontrol edilir.
  - 4h teyit VAR:    confidence_score *= 1.3 (max 1.0 cap kaldiriliyor, ham carpim)
  - 4h teyit KARSI:  sinyal REDDEDILIR (confidence=0, cikti yok)
  - 4h NOTRAL:       sinyal degismeden gecir (parent confidence)

Brooks always-in flip (4h) operasyonel tanim:
  Son `h4_lookback` (4-6) 4h barinda:
    Long flip : en az `n_confirm` bar bullish kapanmis (close > close.shift(1))
                VE son bar'in close'u, o penceredeki en yuksek close'un >= %90'i
                (yani yeni lokal HH yapmis veya cok yakin)
    Short flip: simetrik

Lookahead-free garantisi:
  - 1d bar t kapaninca, son tam 4h bar bar-t icindedir
    (UTC: 1d bar 00:00 UTC kapanir; son 4h bar 20:00 UTC onceki gundur)
  - 4h verisi, 1d ts anina gore filtrelenir: df_4h[ts < 1d_bar_ts]
"""
# ruff: noqa: F841, N806  (pre-existing; 2026-07-10 batch-D dokunuşunda yüzeye çıktı — davranış-nötr)

from __future__ import annotations

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Paylasilmis yardimcilar
from price_action.strategies.classic_pa import (
    _always_in_flags,
    _atr,
    _ema,
    _fractal_swings,
    _kaufman_efficiency_ratio,
    _rolling_sharpe,
    _sr_levels,
)
from price_action.strategies.engulfing_continuation import (
    _pullback_to_ema_flag,
    _strict_engulfing,
    _swing_sl,
)

# =====================================================================
# 4h always-in detection (lookahead-free)
# =====================================================================


def detect_4h_always_in(
    df_4h: pd.DataFrame,
    cutoff_ts: pd.Timestamp,
    direction: str,
    lookback: int = 6,
    n_confirm: int = 3,
    strong_close_pct: float = 0.90,
) -> str:
    """Son `lookback` 4h barinda Brooks always-in flip tespit et.

    Parameters
    ----------
    df_4h        : 4h OHLCV DataFrame (ts, open, high, low, close, volume)
    cutoff_ts    : 1d bar'in kapanma timestamps (bu tse kadar olan 4h barlar)
    direction    : 'long' veya 'short' — kontrol edilecek yon
    lookback     : Son kac 4h bar incelenir (4-6 onerilir)
    n_confirm    : Kac bar trend yonunde kapanmali (minimum)
    strong_close_pct : Son bar'in close'u penceredeki peak close'un ne kadari olmali

    Returns
    -------
    'confirm'  — 4h always-in ayni yonde
    'against'  — 4h always-in karsi yonde
    'neutral'  — belirsiz
    """
    if df_4h is None or df_4h.empty:
        return "neutral"

    ts_4h = pd.to_datetime(df_4h["ts"], utc=True)
    cutoff = pd.Timestamp(cutoff_ts).tz_localize("UTC") if cutoff_ts.tzinfo is None else cutoff_ts

    # Sadece cutoff oncesi 4h barlar — lookahead-free
    mask = ts_4h < cutoff
    avail = df_4h[mask]
    if len(avail) < lookback:
        return "neutral"

    window = avail.iloc[-lookback:].reset_index(drop=True)
    close = window["close"]
    n = len(window)

    # Trend yonunde kapanma sayisi
    bullish_closes = int((close > close.shift(1)).sum())  # shift(1) NaN icin 0 sayilmaz
    bearish_closes = int((close < close.shift(1)).sum())

    last_close = float(close.iloc[-1])
    peak_close = float(close.max())
    trough_close = float(close.min())

    if direction == "long":
        # Long teyit: n_confirm bar yukari kapanmis VE son bar peak'e yakin
        is_confirm = bullish_closes >= n_confirm and (
            peak_close <= 0 or last_close >= strong_close_pct * peak_close
        )
        # Karsi: n_confirm bar asagi kapanmis VE son bar trough'a yakin
        is_against = bearish_closes >= n_confirm and (
            trough_close >= 0 and last_close <= (1 + (1 - strong_close_pct)) * trough_close
        )
    else:  # direction == 'short'
        is_confirm = bearish_closes >= n_confirm and (
            trough_close >= 0 and last_close <= (1 + (1 - strong_close_pct)) * trough_close
        )
        is_against = bullish_closes >= n_confirm and (
            peak_close <= 0 or last_close >= strong_close_pct * peak_close
        )

    if is_confirm and not is_against:
        return "confirm"
    if is_against and not is_confirm:
        return "against"
    return "neutral"


# =====================================================================
# 4h features (once per symbol, not per bar)
# =====================================================================


def _load_4h_data(symbol: str, venue: str = "binance") -> pd.DataFrame | None:
    """DuckDB'den 4h veri yukle. Yoksa None doner."""
    try:
        from pathlib import Path

        import duckdb

        db_path = (
            Path(__file__).resolve().parents[3] / "data" / "market.duckdb"
        )  # G24 fix: Price Action kökü (eskiden parents[4]=projeler — proje dışı, 4h MTF sessizce ölüydü)
        if not db_path.exists():
            return None
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            df = con.execute(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE venue=? AND symbol=? AND timeframe='4h' ORDER BY ts",
                [venue, symbol],
            ).fetchdf()
        finally:
            con.close()
        if df.empty:
            return None
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["symbol"] = symbol
        df["timeframe"] = "4h"
        df["venue"] = venue
        return df
    except Exception as exc:
        logger.bind(symbol=symbol, err=str(exc)).warning("engulfing_mtf.4h_load_fail")
        return None


# =====================================================================
# Default manifest (engulfing_continuation uzantisi)
# =====================================================================


def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "engulfing_mtf",
        "version": "1.0.0",
        "description": "Engulfing 1d + 4h Brooks always-in confluence filter",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
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
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "bear_regime_size_factor": 0.5,
                # MTF-specific params
                "h4_lookback": 6,
                "h4_n_confirm": 3,
                "h4_strong_close_pct": 0.90,
                "h4_confirm_boost": 1.3,
                "h4_reject_against": True,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy implementation
# =====================================================================


class EngulfingMTFStrategy(Strategy):
    """Engulfing 1d + 4h Brooks always-in confluence.

    Parent logic: EngulfingContinuationStrategy tam olarak tekrar kullanilir.
    Ek filtre: her sinyal icin 4h always-in teyidi kontrol edilir.

    Confidence boost:
      - confirm  -> score *= h4_confirm_boost (default 1.3)
      - against  -> sinyal reddedilir (h4_reject_against=True ise)
      - neutral  -> degismeden gecir

    4h veri: sembol basina tek seferlik yukle, ts-indexed lookup ile O(log n).
    """

    name = "engulfing_mtf"

    def __init__(self, manifest: StrategyManifest, df_4h: pd.DataFrame | None = None) -> None:
        super().__init__(manifest)
        self._df_4h_cache: dict[str, pd.DataFrame | None] = {}
        if df_4h is not None:
            # Dis'tan inject edilmis 4h veri (test amacli)
            sym = str(df_4h["symbol"].iloc[0]) if "symbol" in df_4h.columns else "__test__"
            self._df_4h_cache[sym] = df_4h

    # ------------------------------------------------------------------
    # Internal: 4h data lookup
    # ------------------------------------------------------------------

    def _get_4h(self, symbol: str, venue: str = "binance") -> pd.DataFrame | None:
        key = f"{venue}:{symbol}"
        if key not in self._df_4h_cache:
            self._df_4h_cache[key] = _load_4h_data(symbol, venue)
        return self._df_4h_cache[key]

    # ------------------------------------------------------------------
    # prepare_features: delegate to parent + store 4h ref
    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """1d feature'lari hazirla (parent strateji ile ayni)."""
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # EMA'lar
        df["ema20"] = _ema(df["close"], 20)
        df["ema14"] = _ema(df["close"], 14)
        df["ema50"] = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]

        # Volume z-score
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)

        # Swing fractal
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl

        # Pullback to 20-EMA
        pb_window = 10
        pb_touch = 0.5
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                pb_window = int(p.params.get("pullback_window", 10))
                pb_touch = float(p.params.get("pullback_touch_atr", 0.5))
                break
        df["pullback_to_20ema"] = _pullback_to_ema_flag(
            df, ema_col="ema20", window=pb_window, touch_atr_factor=pb_touch
        )

        # Strict engulfing flags
        body_ratio_min = 0.6
        for p in self.manifest.signals.patterns:
            if p.id in ("bullish_engulfing_cont", "bearish_engulfing_cont"):
                body_ratio_min = float(p.params.get("body_ratio_min", 0.6))
                break
        df["strict_bull_engulf"] = _strict_engulfing(
            df, body_ratio_min=body_ratio_min, bullish=True
        )
        df["strict_bear_engulf"] = _strict_engulfing(
            df, body_ratio_min=body_ratio_min, bullish=False
        )

        # Structural SL
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Kaufman ER
        filters_cfg = self.manifest.signals.filters
        er_period = int(getattr(filters_cfg, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)

        # Brooks always-in (1d)
        ai_n = int(getattr(filters_cfg, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai

        # Rolling Sharpe
        rs_period = int(getattr(filters_cfg, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)

        return df

    # ------------------------------------------------------------------
    # generate_signals: parent logic + 4h MTF filter
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "ema20" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance

        # 4h config
        h4_lookback = int(getattr(filters, "h4_lookback", 6) or 6)
        h4_n_confirm = int(getattr(filters, "h4_n_confirm", 3) or 3)
        h4_strong_close_pct = float(getattr(filters, "h4_strong_close_pct", 0.90) or 0.90)
        h4_confirm_boost = float(getattr(filters, "h4_confirm_boost", 1.3) or 1.3)
        h4_reject_against = bool(getattr(filters, "h4_reject_against", True))

        primary_R = float(self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0))

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "binance"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # 4h veri al (sembol basina cached)
        df_4h = self._get_4h(symbol, venue)

        # --- Score series (parent mantigi ile ayni) ---
        long_score = pd.Series(0.0, index=df.index)
        short_score = pd.Series(0.0, index=df.index)

        bull_weight = 1.5
        bear_weight = 1.5
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_engulfing_cont":
                bull_weight = p.weight
            elif p.id == "bearish_engulfing_cont":
                bear_weight = p.weight

        pullback = df["pullback_to_20ema"].fillna(False)
        bull_engulf = df["strict_bull_engulf"].fillna(False)
        bear_engulf = df["strict_bear_engulf"].fillna(False)

        long_score = long_score.where(~(pullback & bull_engulf), bull_weight)
        short_score = short_score.where(~(pullback & bear_engulf), bear_weight)

        # Trend filter (50-EMA)
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema50"]
            down_ok = df["close"] < df["ema50"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # ATR min
        atr_min = float(getattr(filters, "atr_min_pct", 0.005) or 0.005)
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Volume z-score
        vol_min = float(getattr(filters, "volume_zscore_min", 0.0) or 0.0)
        if vol_min > 0:
            mask = df["vol_z"].fillna(-np.inf) >= vol_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Kaufman ER
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # Always-in (1d, optional)
        if bool(getattr(filters, "always_in_required", False)):
            long_score = long_score.where(df["always_in_long"], 0.0)
            short_score = short_score.where(df["always_in_short"], 0.0)

        # Rolling Sharpe size factor
        rs_min = float(getattr(filters, "rolling_sharpe_min", -1e9))
        rs_size_factor = float(getattr(filters, "rolling_sharpe_size_factor", 1.0) or 1.0)
        if rs_min > -1e8 and "rolling_sharpe" in df.columns:
            poor_regime = df["rolling_sharpe"] < rs_min
            long_score = long_score.where(~poor_regime, long_score * rs_size_factor)
            short_score = short_score.where(~poor_regime, short_score * rs_size_factor)

        # 200-EMA bear regime
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            long_score = long_score.where(~below_200, long_score * bear_factor)

        # S/R levels
        cluster_tol = df["atr14"].fillna(0) * sr_cfg.cluster_atr_multiplier
        sr_records = _sr_levels(
            df,
            lookback_bars=sr_cfg.lookback_bars,
            cluster_tol=cluster_tol,
            min_touches=sr_cfg.min_touches,
        )
        sr_by_bar: dict[int, list[float]] = {}
        for i, lvl, _t in sr_records:
            sr_by_bar.setdefault(i, []).append(lvl)

        proximity_atr = signals_cfg.structure.require_proximity_to_sr_atr
        bonus = float(getattr(confluence, "bonus_if_at_sr", 0.0) or 0.0)
        min_score = float(confluence.min_score)

        out: list[Signal] = []
        h4_stats = {"confirm": 0, "against": 0, "neutral": 0, "no_data": 0}

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            levels = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            # 1d bar timestamp (lookahead-free 4h cutoff)
            bar_ts = pd.Timestamp(row["ts"])
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.tz_localize("UTC")

            for direction, score_series, pattern_id_name in (
                ("long", long_score, "bullish_engulfing_cont"),
                ("short", short_score, "bearish_engulfing_cont"),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue

                # S/R adjustment
                final_score = base_score + (bonus if near_sr else 0.0)
                if proximity_atr > 0 and not near_sr:
                    final_score = max(0.0, final_score - 0.25)
                if final_score < min_score:
                    continue

                # ---- 4h MTF confluence check ----
                if df_4h is not None:
                    h4_verdict = detect_4h_always_in(
                        df_4h,
                        cutoff_ts=bar_ts,
                        direction=direction,
                        lookback=h4_lookback,
                        n_confirm=h4_n_confirm,
                        strong_close_pct=h4_strong_close_pct,
                    )
                else:
                    h4_verdict = "neutral"
                    h4_stats["no_data"] += 1

                if h4_verdict == "confirm":
                    final_score = final_score * h4_confirm_boost
                    h4_stats["confirm"] += 1
                elif h4_verdict == "against":
                    h4_stats["against"] += 1
                    if h4_reject_against:
                        continue  # sinyal reddedildi
                    # h4_reject_against=False: gecir ama boost yok
                else:
                    h4_stats["neutral"] += 1

                # Structural SL
                if direction == "long":
                    sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close - 2.0 * atr
                    sl_price = min(sl_price, close - 0.5 * atr)
                    risk = close - sl_price
                    tp_price = close + primary_R * risk
                else:
                    sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                    if np.isnan(sl_price) or sl_price <= 0:
                        sl_price = close + 2.0 * atr
                    sl_price = max(sl_price, close + 0.5 * atr)
                    risk = sl_price - close
                    tp_price = close - primary_R * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
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
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema20": float(row.get("ema20") or 0.0),
                        "ema50": float(row.get("ema50") or 0.0),
                        "pullback_to_20ema": bool(row.get("pullback_to_20ema", False)),
                        "kaufman_er": float(row.get("kaufman_er") or 0.0),
                        "h4_verdict": h4_verdict,
                        "h4_boost_applied": h4_verdict == "confirm",
                    },
                )
                out.append(sig)

        self._log.bind(
            n=len(out),
            bars=len(df),
            h4_confirm=h4_stats["confirm"],
            h4_against=h4_stats["against"],
            h4_neutral=h4_stats["neutral"],
        ).info("engulfing_mtf.signals.generated")
        return out
