"""Classic Price Action stratejisi.

Manifest: configs/strategies/classic_pa.yaml
Signals layer'ından detector'ları çağırır (gerçek runtime), import edilemezse
in-house basit pattern detection ile devam eder (test/sandbox modu).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest


# =====================================================================
# Yardımcı: ATR & EMA & swing fractal & S/R kümeleme (vektorize)
# =====================================================================

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _kaufman_efficiency_ratio(close: pd.Series, period: int = 14) -> pd.Series:
    """Kaufman Efficiency Ratio: net change / sum(abs(daily changes)).

    ER ≈ 1.0 → strong directional move (trend)
    ER ≈ 0.0 → choppy / random
    Forward-looking-safe: t-period ile t arası bilgisi.
    """
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    er = change / volatility.replace(0, np.nan)
    return er.fillna(0.0).clip(0.0, 1.0)


def _always_in_flags(df: pd.DataFrame, n_confirm: int = 3) -> tuple[pd.Series, pd.Series]:
    """Brooks 'always-in' trend confirmation.

    Long: son n_confirm bar trend yönünde (close > close.shift(1)) AND
          close > prev_n_high (last bar yeni HH yapmış)
    Short: tersine.
    Forward-looking-safe: sadece geçmiş bar bilgisi.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    # Son n_confirm bar boyunca cumulative bullish closes
    bullish = (close > close.shift(1)).rolling(n_confirm).sum()
    bearish = (close < close.shift(1)).rolling(n_confirm).sum()
    # n önceki bar high/low
    prev_high = high.shift(1).rolling(n_confirm).max()
    prev_low = low.shift(1).rolling(n_confirm).min()
    long_flag = (bullish >= n_confirm - 1) & (close > prev_high)
    short_flag = (bearish >= n_confirm - 1) & (close < prev_low)
    return long_flag.fillna(False), short_flag.fillna(False)


def _rolling_sharpe(close: pd.Series, period: int = 60) -> pd.Series:
    """Rolling Sharpe ratio of daily returns over `period` bars.

    Annualized × sqrt(365). Forward-looking-safe (uses only past `period` bars).
    """
    rets = close.pct_change()
    mean_r = rets.rolling(period, min_periods=period // 2).mean()
    std_r = rets.rolling(period, min_periods=period // 2).std(ddof=0)
    sharpe = (mean_r / std_r.replace(0, np.nan)) * np.sqrt(365)
    return sharpe.fillna(0.0)


def _fractal_swings(df: pd.DataFrame, n: int = 2) -> tuple[pd.Series, pd.Series]:
    """N-bar fractal swing high/low. Sağ taraf bilgisi içerdiği için
    backtest sırasında sadece bar t-n için kullanılabilir (lookahead yok)."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n_bars = len(df)
    is_swing_high = np.zeros(n_bars, dtype=bool)
    is_swing_low = np.zeros(n_bars, dtype=bool)
    for i in range(n, n_bars - n):
        window_h = highs[i - n : i + n + 1]
        window_l = lows[i - n : i + n + 1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            is_swing_high[i] = True
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            is_swing_low[i] = True
    return (
        pd.Series(is_swing_high, index=df.index, name="swing_high"),
        pd.Series(is_swing_low, index=df.index, name="swing_low"),
    )


def _sr_levels(
    df: pd.DataFrame,
    *,
    lookback_bars: int,
    cluster_tol: pd.Series,
    min_touches: int,
) -> list[tuple[int, float, int]]:
    """Bar bazlı dinamik S/R seviyeleri.

    Her bar `i` için, [i-lookback, i-1] aralığındaki swing'ler `cluster_tol[i]` (ATR*k)
    içinde kümelenir. (i, level_price, touches) listesi döner — sadece o
    bar'a kadar bilinen geçmiş kullanıldığı için lookahead yoktur.

    Performans için her 5 barda bir yeniden hesaplanır; aradaki barlarda
    önceki kümeleme tekrar kullanılır (yeterince hızlı, vektorel).
    """
    out: list[tuple[int, float, int]] = []
    swing_h, swing_l = _fractal_swings(df, n=2)
    swing_prices = pd.concat(
        [df["high"][swing_h], df["low"][swing_l]]
    ).sort_index()
    levels_cache: list[tuple[float, int]] = []
    last_recompute = -10**9
    for i in range(len(df)):
        if i - last_recompute >= 5:
            window = swing_prices.loc[: df.index[i - 1]] if i > 0 else swing_prices.iloc[:0]
            if len(window) >= 2:
                window = window.tail(lookback_bars)
                tol = float(cluster_tol.iloc[i] or 0.0)
                vals = window.to_numpy()
                vals_sorted = np.sort(vals)
                clusters: list[list[float]] = []
                for v in vals_sorted:
                    if clusters and abs(v - np.mean(clusters[-1])) <= tol:
                        clusters[-1].append(float(v))
                    else:
                        clusters.append([float(v)])
                levels_cache = [
                    (float(np.mean(c)), len(c))
                    for c in clusters
                    if len(c) >= min_touches
                ]
            last_recompute = i
        for lvl, touches in levels_cache:
            out.append((i, lvl, touches))
    return out


# =====================================================================
# Pattern detection (vektorel, lookahead-free)
# =====================================================================

def _detect_pin_bars(df: pd.DataFrame, params: dict[str, Any], bullish: bool) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    upper_wick = df["high"] - df[["close", "open"]].max(axis=1)
    lower_wick = df[["close", "open"]].min(axis=1) - df["low"]
    body_ratio = body / rng
    if bullish:
        cond = (
            (body_ratio <= params.get("body_to_range_max", 0.33))
            & ((lower_wick / rng) >= params.get("lower_wick_to_range_min", 0.6))
            & ((upper_wick / rng) <= params.get("upper_wick_to_range_max", 0.15))
        )
    else:
        cond = (
            (body_ratio <= params.get("body_to_range_max", 0.33))
            & ((upper_wick / rng) >= params.get("upper_wick_to_range_min", 0.6))
            & ((lower_wick / rng) <= params.get("lower_wick_to_range_max", 0.15))
        )
    return cond.fillna(False)


def _detect_engulfing(df: pd.DataFrame, params: dict[str, Any], bullish: bool) -> pd.Series:
    open_ = df["open"]
    close = df["close"]
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    prev_body = (prev_close - prev_open).abs()
    prev_body_ratio = prev_body / rng.shift(1)
    body_min = params.get("prev_body_min_range_pct", 0.2)
    if bullish:
        cond = (
            (close > open_)
            & (prev_close < prev_open)
            & (close >= prev_open)
            & (open_ <= prev_close)
            & (prev_body_ratio >= body_min)
        )
    else:
        cond = (
            (close < open_)
            & (prev_close > prev_open)
            & (close <= prev_open)
            & (open_ >= prev_close)
            & (prev_body_ratio >= body_min)
        )
    return cond.fillna(False)


def _detect_inside_bar_breakout(
    df: pd.DataFrame, params: dict[str, Any]
) -> tuple[pd.Series, pd.Series]:
    """Inside bar formasyonu sonrası kırılım. Hem long hem short olarak döner."""
    inside = (df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))
    confirm = params.get("confirm_with_close", True)
    prev_inside = inside.shift(1).fillna(False)
    bullish = prev_inside & (
        (df["close"] > df["high"].shift(1)) if confirm else (df["high"] > df["high"].shift(1))
    )
    bearish = prev_inside & (
        (df["close"] < df["low"].shift(1)) if confirm else (df["low"] < df["low"].shift(1))
    )
    return bullish.fillna(False), bearish.fillna(False)


# =====================================================================
# External signals layer entegrasyonu
# =====================================================================

def _try_external_emit_signals(
    df: pd.DataFrame, manifest: StrategyManifest
) -> list[Signal] | None:
    """Eğer Signal Chief'in confluence emitter'ı yüklüyse onu kullan."""
    try:
        from price_action.signals.confluence import emit_signals  # type: ignore
    except Exception:
        return None
    try:
        venue = str(df["venue"].iloc[0]) if "venue" in df.columns and not df.empty else "binance"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns and not df.empty else ""
        timeframe = (
            str(df["timeframe"].iloc[0]) if "timeframe" in df.columns and not df.empty else "1d"
        )
        return list(
            emit_signals(
                df,
                manifest.model_dump(),
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,
            )
        )  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - emit_signals'ın imzası değişirse
        logger.bind(err=str(exc)).warning("classic_pa.external_emit_failed")
        return None


# =====================================================================
# Strategy implementation
# =====================================================================

class ClassicPriceActionStrategy(Strategy):
    """Klasik PA: pin bar / engulfing / inside bar + S/R + EMA trend filter."""

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()
        period = self.manifest.trend_filter.period
        df["ema_trend"] = _ema(df["close"], period)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"]
        # Volume z-score (60 bar)
        vol = df["volume"]
        vmean = vol.rolling(60, min_periods=10).mean()
        vstd = vol.rolling(60, min_periods=10).std(ddof=0)
        df["vol_z"] = (vol - vmean) / vstd.replace(0, np.nan)
        # Swings
        n = self.manifest.signals.structure.swing.fractal_n
        sh, sl = _fractal_swings(df, n=n)
        df["swing_high"] = sh
        df["swing_low"] = sl
        # === Forward-looking filter features (Aşama B) ===
        # Kaufman Efficiency Ratio — chop / trend ayırımı
        er_period = int(getattr(self.manifest.signals.filters, "kaufman_er_period", 14) or 14)
        df["kaufman_er"] = _kaufman_efficiency_ratio(df["close"], period=er_period)
        # Brooks always-in flags
        ai_n = int(getattr(self.manifest.signals.filters, "always_in_n_confirm", 3) or 3)
        long_ai, short_ai = _always_in_flags(df, n_confirm=ai_n)
        df["always_in_long"] = long_ai
        df["always_in_short"] = short_ai
        # Rolling per-symbol Sharpe (kendi kendine performans referansı)
        rs_period = int(getattr(self.manifest.signals.filters, "rolling_sharpe_period", 60) or 60)
        df["rolling_sharpe"] = _rolling_sharpe(df["close"], period=rs_period)
        # 200-EMA — bear regime proxy (per-symbol)
        df["ema200"] = _ema(df["close"], 200)
        return df

    # ----- core -----
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        external = _try_external_emit_signals(df, self.manifest)
        if external is not None:
            self._log.bind(n=len(external)).info("classic_pa.signals.external")
            return external

        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        signals_cfg = self.manifest.signals
        filters = signals_cfg.filters
        confluence = signals_cfg.confluence
        sr_cfg = signals_cfg.structure.support_resistance
        atr_mult_for_sl = float(
            self.manifest.risk.get("stop_loss", {}).get("atr_multiplier", 2.0)
        )
        primary_R = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 2.0)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"

        # Pattern detections
        pattern_long = pd.DataFrame(index=df.index)
        pattern_short = pd.DataFrame(index=df.index)
        for p in signals_cfg.patterns:
            if not p.enabled:
                continue
            if p.id == "bullish_pin_bar":
                pattern_long[p.id] = _detect_pin_bars(df, p.params, bullish=True) * p.weight
            elif p.id == "bearish_pin_bar":
                pattern_short[p.id] = _detect_pin_bars(df, p.params, bullish=False) * p.weight
            elif p.id == "bullish_engulfing":
                pattern_long[p.id] = _detect_engulfing(df, p.params, bullish=True) * p.weight
            elif p.id == "bearish_engulfing":
                pattern_short[p.id] = _detect_engulfing(df, p.params, bullish=False) * p.weight
            elif p.id == "inside_bar_breakout":
                bull, bear = _detect_inside_bar_breakout(df, p.params)
                pattern_long[p.id] = bull * p.weight
                pattern_short[p.id] = bear * p.weight

        long_score = pattern_long.sum(axis=1) if not pattern_long.empty else pd.Series(
            0.0, index=df.index
        )
        short_score = pattern_short.sum(axis=1) if not pattern_short.empty else pd.Series(
            0.0, index=df.index
        )

        # Trend filter (EMA50)
        if self.manifest.trend_filter.required:
            up_ok = df["close"] > df["ema_trend"]
            down_ok = df["close"] < df["ema_trend"]
            long_score = long_score.where(up_ok, 0.0)
            short_score = short_score.where(down_ok, 0.0)

        # Filters
        atr_min = filters.atr_min_pct
        if atr_min > 0:
            mask = df["atr_pct"] >= atr_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)
        if filters.volume_zscore_min > 0:
            mask = df["vol_z"].fillna(-np.inf) >= filters.volume_zscore_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)

        # === Aşama B forward-looking filterları ===
        # 1) Kaufman ER min (chop reject)
        er_min = float(getattr(filters, "kaufman_er_min", 0.0) or 0.0)
        if er_min > 0 and "kaufman_er" in df.columns:
            mask = df["kaufman_er"] >= er_min
            long_score = long_score.where(mask, 0.0)
            short_score = short_score.where(mask, 0.0)
        # 2) Brooks always-in zorunlu mu?
        if bool(getattr(filters, "always_in_required", False)):
            long_score = long_score.where(df["always_in_long"], 0.0)
            short_score = short_score.where(df["always_in_short"], 0.0)
        # 3) Rolling sembol Sharpe min (negatif rejimde size azaltma)
        rs_min = float(getattr(filters, "rolling_sharpe_min", -1e9))
        rs_size_factor = float(getattr(filters, "rolling_sharpe_size_factor", 1.0) or 1.0)
        if rs_min > -1e8 and "rolling_sharpe" in df.columns:
            poor_regime = df["rolling_sharpe"] < rs_min
            # poor regime'da skor x faktör (yarıya indir vs.)
            long_score = long_score.where(~poor_regime, long_score * rs_size_factor)
            short_score = short_score.where(~poor_regime, short_score * rs_size_factor)
        # 4) Confluence sweet-spot upper bound (Analyst paradoxa karşı)
        conf_max = float(getattr(confluence, "max_score", 0.0) or 0.0)
        # confluence_max bandı bar bazında değil signal bazında uygulanacak — aşağıda
        # 5) 200-EMA bear regime — symbol kendi 200-EMA'sının altındaysa long size azalt
        bear_factor = float(getattr(filters, "bear_regime_size_factor", 1.0) or 1.0)
        if bear_factor < 1.0 and "ema200" in df.columns:
            below_200 = df["close"] < df["ema200"]
            long_score = long_score.where(~below_200, long_score * bear_factor)

        # S/R levels (bar bazlı, lookahead-free)
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
        bonus = confluence.bonus_if_at_sr
        min_score = confluence.min_score

        out: list[Signal] = []
        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            # S/R proximity
            levels = sr_by_bar.get(i, [])
            near_sr = False
            if levels and proximity_atr > 0:
                tol = proximity_atr * atr
                near_sr = any(abs(close - lvl) <= tol for lvl in levels)

            for direction, score_series, picks in (
                ("long", long_score, pattern_long),
                ("short", short_score, pattern_short),
            ):
                base_score = float(score_series.iat[i])
                if base_score <= 0:
                    continue
                final_score = base_score + (bonus if near_sr else 0.0)
                if proximity_atr > 0 and not near_sr:
                    # S/R'a yakın değilse min_score'u zorlaştır
                    final_score = max(0.0, final_score - 0.25)
                if final_score < min_score:
                    continue
                # Confluence sweet-spot upper bound (Analyst stop-hunt paradoxu)
                if conf_max > 0 and final_score > conf_max:
                    continue
                # SL & TP
                if direction == "long":
                    sl_price = close - atr_mult_for_sl * atr
                    tp_price = close + primary_R * (close - sl_price)
                else:
                    sl_price = close + atr_mult_for_sl * atr
                    tp_price = close - primary_R * (sl_price - close)
                # Pattern id
                if not picks.empty:
                    contrib = picks.iloc[i]
                    pattern_id = str(contrib.idxmax()) if contrib.max() > 0 else "unknown"
                else:
                    pattern_id = "unknown"

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    pattern_id=pattern_id,
                    confluence_score=float(final_score),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=atr_mult_for_sl,
                    metadata={
                        "near_sr": near_sr,
                        "atr14": atr,
                        "ema_trend": float(row["ema_trend"]) if not np.isnan(row["ema_trend"]) else None,
                        "score_components": {
                            k: float(v) for k, v in contrib.items() if v > 0
                        }
                        if not picks.empty
                        else {},
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df)).info("classic_pa.signals.generated")
        return out
