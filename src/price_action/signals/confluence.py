"""Confluence skoru ve Signal event üretimi.

`emit_signals(df, manifest_config)` strateji manifest'inden okunan
ağırlıklarla çalışır ve `Signal` listesi döner.

KRITIK: Karar `t-1` close'a dayalıdır. Pattern flag'leri `t`'de
hesaplandığında, sinyal `t+1`'in açılışında giriş için emit edilir;
ts olarak bar kapanış zamanı (yani `t`'nin ts'i) kullanılır.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal, stable_hash
from price_action.logging_config import logger
from price_action.signals.candles import (
    bearish_engulfing,
    bearish_pin_bar,
    bullish_engulfing,
    bullish_pin_bar,
    doji,
    evening_star,
    inside_bar_breakout,
    morning_star,
)
from price_action.signals.filters import (
    always_in_flags,
    kaufman_efficiency_ratio,
    rolling_sharpe,
)
from price_action.signals.filters import (
    atr_threshold,
    ema_trend_filter,
    volume_zscore,
)
from price_action.signals.structure import atr, support_resistance

# pattern_id → (detector, default direction)
_BULLISH_PATTERNS = {
    "bullish_pin_bar": ("long", bullish_pin_bar),
    "bullish_engulfing": ("long", bullish_engulfing),
    "morning_star": ("long", morning_star),
}
_BEARISH_PATTERNS = {
    "bearish_pin_bar": ("short", bearish_pin_bar),
    "bearish_engulfing": ("short", bearish_engulfing),
    "evening_star": ("short", evening_star),
}


def score(
    signal_flags: dict[str, pd.Series],
    weights: dict[str, float],
) -> pd.Series:
    """Ağırlıklı toplam skor. Aynı indeksli boolean Series'leri ağırlıklarıyla topla."""
    if not signal_flags:
        return pd.Series(dtype=float)
    idx = next(iter(signal_flags.values())).index
    total = pd.Series(0.0, index=idx)
    for key, flag in signal_flags.items():
        w = float(weights.get(key, 1.0))
        total = total + flag.astype(float) * w
    return total


def add_proximity_to_sr(
    score_series: pd.Series,
    prices: pd.Series,
    sr_levels: pd.DataFrame,
    atr_series: pd.Series,
    *,
    bonus: float = 0.5,
    max_dist_atr: float = 1.0,
) -> pd.Series:
    """Fiyat S/R seviyesine `max_dist_atr * ATR` mesafede ise skoru `bonus` artır."""
    if sr_levels is None or sr_levels.empty:
        return score_series.copy()
    levels = sr_levels["level"].astype(float).to_numpy()
    p = prices.astype(float).to_numpy()
    a = atr_series.astype(float).to_numpy()
    # Vektörize: her bar için en yakın level mesafesi
    dist = np.abs(p[:, None] - levels[None, :])
    min_dist = dist.min(axis=1)
    threshold = max_dist_atr * a
    near = min_dist <= threshold
    bonus_arr = np.where(near, bonus, 0.0)
    return score_series + pd.Series(bonus_arr, index=score_series.index)


def _ts_to_datetime(ts: Any) -> datetime:
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.to_pydatetime()
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return pd.Timestamp(ts, tz="UTC").to_pydatetime()


def emit_signals(
    df: pd.DataFrame,
    manifest_config: dict[str, Any],
    *,
    venue: str = "binance",
    symbol: str = "",
    timeframe: str = "1d",
) -> list[Signal]:
    """Manifest'e göre sinyal üret.

    Beklenen manifest yapısı (classic_pa.yaml ile uyumlu):
        signals.patterns: [{id, enabled, weight, params}, ...]
        signals.structure.support_resistance: {lookback_bars, min_touches, cluster_atr_multiplier, ...}
        signals.confluence: {min_score, bonus_if_at_sr}
        signals.filters: {atr_min_pct, volume_zscore_min, ...}
        trend_filter: {type=ema, period, required}
    """
    if df is None or df.empty:
        return []
    if "ts" not in df.columns:
        raise ValueError("DataFrame 'ts' kolonu içermeli (UTC tz-aware)")

    df = df.sort_values("ts").reset_index(drop=True).copy()

    sigs_cfg = manifest_config.get("signals", {}) or {}
    patterns_cfg: list[dict[str, Any]] = list(sigs_cfg.get("patterns", []) or [])
    structure_cfg = sigs_cfg.get("structure", {}) or {}
    confluence_cfg = sigs_cfg.get("confluence", {}) or {}
    filters_cfg = sigs_cfg.get("filters", {}) or {}
    trend_cfg = manifest_config.get("trend_filter", {}) or {}

    # Pattern flags
    flags: dict[str, pd.Series] = {}
    weights: dict[str, float] = {}
    directions: dict[str, str] = {}
    for entry in patterns_cfg:
        pid = entry.get("id")
        if not entry.get("enabled", True) or not pid:
            continue
        params = entry.get("params") or {}
        weight = float(entry.get("weight", 1.0))
        if pid in _BULLISH_PATTERNS:
            direction, fn = _BULLISH_PATTERNS[pid]
            flags[pid] = fn(df, params)
            directions[pid] = direction
        elif pid in _BEARISH_PATTERNS:
            direction, fn = _BEARISH_PATTERNS[pid]
            flags[pid] = fn(df, params)
            directions[pid] = direction
        elif pid == "inside_bar_breakout":
            ib = inside_bar_breakout(df)
            long_flag = (ib == "long")
            short_flag = (ib == "short")
            flags["inside_bar_breakout_long"] = long_flag
            directions["inside_bar_breakout_long"] = "long"
            weights["inside_bar_breakout_long"] = weight
            flags["inside_bar_breakout_short"] = short_flag
            directions["inside_bar_breakout_short"] = "short"
            weights["inside_bar_breakout_short"] = weight
            continue
        elif pid == "doji_at_extreme":
            flags[pid] = doji(df, params)
            directions[pid] = "long"  # tek başına yönsüz, downstream S/R yakınlığıyla yorumlanır
        else:
            logger.bind(pattern_id=pid).warning("confluence.unknown_pattern")
            continue
        weights[pid] = weight

    if not flags:
        return []

    # ATR + S/R
    a_series = atr(df, period=int(structure_cfg.get("atr_period", 14)))
    sr_cfg = structure_cfg.get("support_resistance", {}) or {}
    sr_levels = support_resistance(
        df,
        lookback=int(sr_cfg.get("lookback_bars", 200)),
        min_touches=int(sr_cfg.get("min_touches", 2)),
        cluster_atr_mult=float(sr_cfg.get("cluster_atr_multiplier", 0.5)),
        n_swing=int((structure_cfg.get("swing") or {}).get("fractal_n", 2)),
    )

    # Yön bazlı skor
    long_keys = [k for k, d in directions.items() if d == "long"]
    short_keys = [k for k, d in directions.items() if d == "short"]
    long_score = score({k: flags[k] for k in long_keys}, weights) if long_keys else pd.Series(0.0, index=df.index)
    short_score = score({k: flags[k] for k in short_keys}, weights) if short_keys else pd.Series(0.0, index=df.index)

    bonus = float(confluence_cfg.get("bonus_if_at_sr", 0.5))
    proximity_atr = float(structure_cfg.get("require_proximity_to_sr_atr", 1.0))
    long_score = add_proximity_to_sr(long_score, df["close"], sr_levels, a_series, bonus=bonus, max_dist_atr=proximity_atr)
    short_score = add_proximity_to_sr(short_score, df["close"], sr_levels, a_series, bonus=bonus, max_dist_atr=proximity_atr)

    # Filtreler
    atr_min_pct = float(filters_cfg.get("atr_min_pct", 0.0))
    atr_ok = atr_threshold(a_series, atr_min_pct, df["close"])
    vol_min_z = float(filters_cfg.get("volume_zscore_min", 0.0))
    vol_ok = volume_zscore(df["volume"], min_z=vol_min_z) if "volume" in df.columns else pd.Series(True, index=df.index)

    # Trend filtre
    if trend_cfg.get("required", False) and trend_cfg.get("type", "ema") == "ema":
        period = int(trend_cfg.get("period", 50))
        long_trend_ok = ema_trend_filter(df["close"], period=period, side="long")
        short_trend_ok = ema_trend_filter(df["close"], period=period, side="short")
    else:
        long_trend_ok = pd.Series(True, index=df.index)
        short_trend_ok = pd.Series(True, index=df.index)

    min_score = float(confluence_cfg.get("min_score", 1.0))
    long_take = (long_score >= min_score) & atr_ok & vol_ok & long_trend_ok
    short_take = (short_score >= min_score) & atr_ok & vol_ok & short_trend_ok

    # === Aşama B forward-looking filters ===
    # 1) Kaufman ER min — chop reject
    er_min = float(filters_cfg.get("kaufman_er_min", 0.0) or 0.0)
    if er_min > 0:
        er = kaufman_efficiency_ratio(
            df["close"], period=int(filters_cfg.get("kaufman_er_period", 14) or 14)
        )
        er_ok = (er >= er_min).fillna(False)
        long_take = long_take & er_ok
        short_take = short_take & er_ok
    # 2) Brooks always-in zorunlu mu?
    if bool(filters_cfg.get("always_in_required", False)):
        ai_n = int(filters_cfg.get("always_in_n_confirm", 3) or 3)
        ai_long, ai_short = always_in_flags(df, n_confirm=ai_n)
        long_take = long_take & ai_long
        short_take = short_take & ai_short
    # 3) Rolling per-symbol Sharpe min
    rs_min_raw = filters_cfg.get("rolling_sharpe_min", None)
    if rs_min_raw is not None:
        rs_period = int(filters_cfg.get("rolling_sharpe_period", 60) or 60)
        rs = rolling_sharpe(df["close"], period=rs_period)
        rs_ok = (rs >= float(rs_min_raw)).fillna(False)
        long_take = long_take & rs_ok
        short_take = short_take & rs_ok
    # 4) 200-EMA bear regime — sembol kendi 200-EMA'sının altında ise long reject
    bear_factor = float(filters_cfg.get("bear_regime_size_factor", 1.0) or 1.0)
    if bear_factor < 1.0:
        from price_action.signals.structure import ema as _ema_fn
        ema200 = _ema_fn(df["close"].astype(float), period=200)
        below_200 = df["close"] < ema200
        # bear_factor < 1 ise basit yaklaşım: 200-altında long sinyalleri reddet
        long_take = long_take & ~below_200
    # 5) Confluence sweet-spot upper bound
    conf_max = float(confluence_cfg.get("max_score", 0.0) or 0.0)
    if conf_max > 0:
        long_take = long_take & (long_score <= conf_max)
        short_take = short_take & (short_score <= conf_max)

    # Risk seviyesi: SL = swing low/high; basitleştirme: low - 1*ATR / high + 1*ATR
    # Support both flat key ("stop_loss_atr_mult") and nested key ("stop_loss.atr_multiplier")
    risk_cfg = manifest_config.get("risk", {}) or {}
    sl_cfg = risk_cfg.get("stop_loss", {}) if isinstance(risk_cfg.get("stop_loss"), dict) else {}
    tp_cfg = risk_cfg.get("take_profit", {}) if isinstance(risk_cfg.get("take_profit"), dict) else {}
    sl_atr_mult = float(
        sl_cfg.get("atr_multiplier") or risk_cfg.get("stop_loss_atr_mult") or 1.5
    )
    tp_r = float(
        tp_cfg.get("primary_R") or risk_cfg.get("take_profit_r") or 2.0
    )

    config_hash = stable_hash(manifest_config)

    out: list[Signal] = []
    for i, take in enumerate(long_take.values):
        if not take:
            continue
        a_val = float(a_series.iloc[i]) if not np.isnan(a_series.iloc[i]) else 0.0
        if a_val <= 0:
            continue
        close_val = float(df["close"].iloc[i])
        sl = close_val - sl_atr_mult * a_val
        tp = close_val + sl_atr_mult * a_val * tp_r
        ts = _ts_to_datetime(df["ts"].iloc[i])
        active_patterns = sorted([k for k in long_keys if bool(flags[k].iloc[i])])
        if not active_patterns:
            continue
        pid = active_patterns[0]
        out.append(
            Signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,  # type: ignore[arg-type]
                direction="long",
                pattern_id=pid,
                confluence_score=float(long_score.iloc[i]),
                sl_price=float(sl),
                tp_price=float(tp),
                suggested_size_atr=float(sl_atr_mult),
                metadata={
                    "bar_index": int(i),
                    "atr": a_val,
                    "active_patterns": active_patterns,
                    "close": close_val,
                },
                manifest_hash=config_hash,
            )
        )

    for i, take in enumerate(short_take.values):
        if not take:
            continue
        a_val = float(a_series.iloc[i]) if not np.isnan(a_series.iloc[i]) else 0.0
        if a_val <= 0:
            continue
        close_val = float(df["close"].iloc[i])
        sl = close_val + sl_atr_mult * a_val
        tp = close_val - sl_atr_mult * a_val * tp_r
        ts = _ts_to_datetime(df["ts"].iloc[i])
        active_patterns = sorted([k for k in short_keys if bool(flags[k].iloc[i])])
        if not active_patterns:
            continue
        pid = active_patterns[0]
        out.append(
            Signal(
                ts=ts,
                venue=venue,
                symbol=symbol,
                timeframe=timeframe,  # type: ignore[arg-type]
                direction="short",
                pattern_id=pid,
                confluence_score=float(short_score.iloc[i]),
                sl_price=float(sl),
                tp_price=float(tp),
                suggested_size_atr=float(sl_atr_mult),
                metadata={
                    "bar_index": int(i),
                    "atr": a_val,
                    "active_patterns": active_patterns,
                    "close": close_val,
                },
                manifest_hash=config_hash,
            )
        )
    return out
