"""Funding Rate Mean-Reversion Strategy — v2.0.0

Strateji özeti:
  - Binance USDT-perp 8h funding rate aşırı pozitif (rolling 95th percentile üstü) →
    over-leveraged long → bearish reversal sinyali → short
  - Aşırı negatif (rolling 5th percentile altı) → over-leveraged short → bullish reversal → long
  - Adaptive threshold: rolling 60-bar (90 days @ 8h funding) 95th/5th percentile per symbol
    shift(1) ile lookahead-free.
  - Regime filter: Kaufman ER < 0.30 (chop/range ortamı) — mean-rev edge trend sırasında zayıf.
  - BNB hariç tutulur (BNB Vault staking kaynaklı tokenomik negatif funding → edge değil gürültü).
  - Giriş: reversal bar N+1 açılışı
  - Stop: yapısal (son 8 barlık swing)
  - Hedef: 1.5R (mean-reversion için küçük hedef)

v2.0.0 değişiklikleri (baseline v1.0.0 → -5.7% yıllık):
  1. Fixed threshold (±0.0005) → adaptive rolling 60-bar 95th/5th percentile per symbol
  2. Kaufman ER < 0.30 regime filtresi eklendi
  3. BNB_EXCLUDED_SYMBOLS kümesi — BNB sinyallerini üretme veya düşük kalite işaretle

Bu strateji engulfing_continuation ile yapısal olarak dekore edilmiştir:
  - Engulfing: trend-following (EMA pullback + momentum, ER > 0.20)
  - Funding MR: counter-trend (over-leverage fade, ER < 0.30)

Funding verisi `data/funding_ingest.py` üzerinden önce alınmalıdır;
yoksa ohlcv_df içindeki `funding_rate` kolonu da kabul edilir.

Veri birleştirme:
  OHLCV (8h) + funding_rate (8h) → aynı timestamp'e merge edilir.
  funding_rate, her OHLCV barının kapandığı andaki funding'i gösterir.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.data.funding_ingest import FundingStore  # re-exported for convenience
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# Symbols excluded from funding mean-reversion due to tokenomic contamination.
# BNB has systematically negative funding driven by BNB Vault staking yield —
# NOT by over-leveraged shorts.  This creates false "extreme negative" signals
# that do not revert in the expected timeframe.
BNB_EXCLUDED_SYMBOLS: frozenset[str] = frozenset({
    "BNB/USDT:USDT",
    "BNBUSDT",
    "BNB-USDT-SWAP",
})

# Kaufman ER threshold: fire signals only in choppy/ranging regimes.
# Engulfing fires when ER > 0.20 (trending); funding MR fires when ER < 0.30.
# 0.10 overlap zone → minimal cross-strategy conflict.
REGIME_ER_MAX: float = 0.30

# Rolling window for adaptive percentile thresholds (bars @ 8h frequency)
# 60 bars = 20 days ≈ one monthly funding cycle
ADAPTIVE_WINDOW: int = 60

# Percentiles for extreme detection (default if not in manifest)
EXTREME_PCTILE_HIGH: float = 95.0   # 95th → short signal
EXTREME_PCTILE_LOW: float = 5.0    # 5th  → long signal


# ---------------------------------------------------------------------------
# Default manifest
# ---------------------------------------------------------------------------

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "funding_mean_reversion",
        "version": "2.0.0",
        "description": (
            "Fade extreme funding rates on Binance USDT-perp: "
            "adaptive 95th/5th percentile threshold + ER<0.30 regime filter. "
            "BNB excluded (tokenomic contamination)."
        ),
        "timeframes": {"decision": "8h"},
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "funding_fade_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "adaptive_window": ADAPTIVE_WINDOW,
                        "extreme_pctile_high": EXTREME_PCTILE_HIGH,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": REGIME_ER_MAX,
                        "kaufman_er_period": 14,
                    },
                },
                {
                    "id": "funding_fade_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "adaptive_window": ADAPTIVE_WINDOW,
                        "extreme_pctile_low": EXTREME_PCTILE_LOW,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": REGIME_ER_MAX,
                        "kaufman_er_period": 14,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.002,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 8},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# ---------------------------------------------------------------------------
# Feature helpers (all lookahead-free)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range ATR — lookahead-free."""
    hi = df["high"]
    lo = df["low"]
    pc = df["close"].shift(1)
    tr = pd.concat(
        [hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _swing_high_low(
    df: pd.DataFrame, lookback: int = 8
) -> tuple[pd.Series, pd.Series]:
    """Rolling swing high / low over last `lookback` bars (lookahead-free).

    Uses shift(1) so bar t sees [t-lookback, t-1].
    """
    sh = df["high"].shift(1).rolling(lookback, min_periods=1).max()
    sl = df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return sh, sl


def _funding_z_score(funding: pd.Series, window: int = 90) -> pd.Series:
    """Rolling z-score of funding rate.

    window=90 → ~30 days at 8h frequency (3 periods/day).
    shift(1) ensures no lookahead.
    """
    # shift(1): at time t we use funding[t-1] — the settled rate
    fr_lagged = funding.shift(1)
    mean = fr_lagged.rolling(window, min_periods=10).mean()
    std = fr_lagged.rolling(window, min_periods=10).std(ddof=0)
    z = (fr_lagged - mean) / std.replace(0.0, np.nan)
    return z


def _adaptive_funding_bands(
    funding: pd.Series,
    window: int = ADAPTIVE_WINDOW,
    pctile_high: float = EXTREME_PCTILE_HIGH,
    pctile_low: float = EXTREME_PCTILE_LOW,
) -> tuple[pd.Series, pd.Series]:
    """Rolling adaptive thresholds: 95th / 5th percentile per symbol.

    Lookahead-free: rolling window applied on shift(1) series so bar t
    uses [t-window .. t-1] funding values only.

    Returns:
        band_high: rolling 95th percentile (series)
        band_low:  rolling 5th  percentile (series)
    """
    fr_lagged = funding.shift(1)
    band_high = fr_lagged.rolling(window, min_periods=max(10, window // 4)).quantile(
        pctile_high / 100.0
    )
    band_low = fr_lagged.rolling(window, min_periods=max(10, window // 4)).quantile(
        pctile_low / 100.0
    )
    return band_high, band_low


def _kaufman_er(close: pd.Series, period: int = 14) -> pd.Series:
    """Kaufman Efficiency Ratio — lookahead-free.

    ER ≈ 1.0  → strong trend (do NOT fire mean-reversion here)
    ER ≈ 0.0  → choppy/ranging (mean-reversion edge active)
    """
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    er = change / volatility.replace(0, np.nan)
    return er.fillna(0.0).clip(0.0, 1.0)


def _reversal_bar_bearish(df: pd.DataFrame, body_ratio_min: float = 0.35) -> pd.Series:
    """Current bar is bearish with body_ratio >= threshold.

    Lookahead-free: uses current bar OHLC.
    body_ratio = |close - open| / (high - low)
    """
    o = df["open"]
    c = df["close"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = (c - o).abs()
    ratio = body / rng
    bearish = (c < o) & (ratio >= body_ratio_min)
    return bearish.fillna(False)


def _reversal_bar_bullish(df: pd.DataFrame, body_ratio_min: float = 0.35) -> pd.Series:
    """Current bar is bullish with body_ratio >= threshold."""
    o = df["open"]
    c = df["close"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = (c - o).abs()
    ratio = body / rng
    bullish = (c > o) & (ratio >= body_ratio_min)
    return bullish.fillna(False)


def merge_funding_to_ohlcv(
    ohlcv_df: pd.DataFrame,
    funding_df: pd.DataFrame,
    *,
    symbol: str | None = None,
    tolerance_ms: int = 4 * 60 * 60 * 1000,  # ±4h tolerance
) -> pd.DataFrame:
    """OHLCV ve funding rate DataFrame'lerini timestamp'e göre merge eder.

    Her OHLCV barına en yakın (veya eşit) funding rate değerini atar.
    Hem `as_of` (bar kapanışı <= funding timestamp) hem de forward-fill kullanılır.

    Args:
        ohlcv_df: Standart OHLCV (ts, open, high, low, close, volume)
        funding_df: (ts, funding_rate, mark_price) — FundingStore.read() çıktısı
        symbol: filtreleme için; None ise tüm kayıtlar.
        tolerance_ms: eşleşme toleransı (default 4 saat)

    Returns:
        ohlcv_df with 'funding_rate' and 'mark_price' columns added.
        NaN where no funding record is found within tolerance.
    """
    if ohlcv_df.empty or funding_df.empty:
        df = ohlcv_df.copy()
        df["funding_rate"] = float("nan")
        df["mark_price"] = float("nan")
        return df

    if symbol is not None and "symbol" in funding_df.columns:
        funding_df = funding_df[funding_df["symbol"] == symbol]

    # Ensure UTC
    def _to_utc(s: pd.Series) -> pd.Series:
        if not pd.api.types.is_datetime64_any_dtype(s):
            s = pd.to_datetime(s, utc=True, errors="coerce")
        elif s.dt.tz is None:
            s = s.dt.tz_localize("UTC")
        else:
            s = s.dt.tz_convert("UTC")
        return s

    ohlcv = ohlcv_df.copy()
    ohlcv["ts"] = _to_utc(ohlcv["ts"])
    # mark_price is optional — add placeholder if missing
    if "mark_price" not in funding_df.columns:
        funding_df = funding_df.copy()
        funding_df["mark_price"] = float("nan")
    fr = funding_df[["ts", "funding_rate", "mark_price"]].copy()
    fr["ts"] = _to_utc(fr["ts"])
    fr = fr.sort_values("ts").drop_duplicates("ts", keep="last")

    # Merge-asof: for each OHLCV bar, find the latest funding record <= bar ts
    ohlcv_sorted = ohlcv.sort_values("ts")
    merged = pd.merge_asof(
        ohlcv_sorted,
        fr.rename(columns={"ts": "fr_ts"}),
        left_on="ts",
        right_on="fr_ts",
        direction="backward",
        tolerance=pd.Timedelta(milliseconds=tolerance_ms),
    )
    # Restore original index order
    merged = merged.set_index(ohlcv_sorted.index)
    # Drop helper column if present
    if "fr_ts" in merged.columns:
        merged = merged.drop(columns=["fr_ts"])
    return merged


# ---------------------------------------------------------------------------
# Strategy implementation
# ---------------------------------------------------------------------------

class FundingMeanReversionStrategy(Strategy):
    """Fade extreme funding rates on Binance USDT-perp — v2.0.0.

    Key improvements over v1.0.0:
      1. Adaptive threshold: rolling 60-bar 95th/5th percentile per symbol
         (replaces fixed ±0.0005 which generated too few signals and missed
         symbol-specific funding regime levels).
      2. Regime filter: Kaufman ER < 0.30 — mean-reversion edge is weakest
         during strong trending phases where funding spikes are NOT reverting.
      3. BNB excluded: BNB Vault staking creates structurally negative funding
         unrelated to over-leverage; produces false long signals.

    Veri hazırlığı:
        prepare_features() hem saf OHLCV hem de OHLCV+funding_rate içeren
        DataFrame'i kabul eder. Eğer 'funding_rate' kolonu yoksa feature'lar
        hesaplanamaz ve strateji sinyal üretmez.

    Backtest:
        ohlcv_provider'a `funding_rate` kolonu eklenmiş DataFrame dönmesi
        beklenir. Bunu sağlamak için BacktestEngine'e özel bir ohlcv_provider
        wrap'i gerekir (bkz. test örneği / CLI entegrasyon).
    """

    name = "funding_mean_reversion"

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # Swing high / low for structural stop
        p = self._get_params()
        swing_lb = int(p.get("swing_lookback", 8))
        sh, sl = _swing_high_low(df, lookback=swing_lb)
        df["swing_high_8"] = sh
        df["swing_low_8"] = sl

        # Kaufman ER — regime filter (lookahead-free, uses close history only)
        er_period = int(p.get("kaufman_er_period", 14))
        df["kaufman_er"] = _kaufman_er(df["close"], period=er_period)
        # Lag by 1 bar so bar t uses ER computed through bar t-1
        df["kaufman_er_lag1"] = df["kaufman_er"].shift(1)

        # Funding features — only if funding_rate column present
        if "funding_rate" in df.columns:
            df["funding_rate"] = pd.to_numeric(df["funding_rate"], errors="coerce")
            df["funding_z"] = _funding_z_score(df["funding_rate"], window=90)

            # Shifted funding (lagged 1 bar — confirmed rate at bar open)
            # We use shift(1) so that bar N's decision uses bar N-1's funding rate
            df["funding_rate_lag1"] = df["funding_rate"].shift(1)
            df["funding_z_lag1"] = df["funding_z"].shift(1)

            # Adaptive thresholds — lookahead-free rolling percentiles on lagged series
            adaptive_window = int(p.get("adaptive_window", ADAPTIVE_WINDOW))
            pctile_high = float(p.get("extreme_pctile_high", EXTREME_PCTILE_HIGH))
            pctile_low = float(p.get("extreme_pctile_low", EXTREME_PCTILE_LOW))
            band_high, band_low = _adaptive_funding_bands(
                df["funding_rate"],
                window=adaptive_window,
                pctile_high=pctile_high,
                pctile_low=pctile_low,
            )
            df["funding_band_high"] = band_high  # already shift(1)-based inside helper
            df["funding_band_low"] = band_low
        else:
            df["funding_z"] = float("nan")
            df["funding_rate_lag1"] = float("nan")
            df["funding_z_lag1"] = float("nan")
            df["funding_band_high"] = float("nan")
            df["funding_band_low"] = float("nan")

        # Reversal bar flags
        body_ratio_min = float(p.get("reversal_body_ratio_min", 0.35))
        df["reversal_bear"] = _reversal_bar_bearish(df, body_ratio_min)
        df["reversal_bull"] = _reversal_bar_bullish(df, body_ratio_min)

        return df

    def _get_params(self) -> dict[str, Any]:
        """Manifest'teki ilk pattern'den parametreleri çek."""
        for pat in self.manifest.signals.patterns:
            if pat.id in ("funding_fade_short", "funding_fade_long"):
                return pat.params
        return {}

    def _is_bnb_symbol(self, symbol: str) -> bool:
        """BNB tokenomic contamination check."""
        return symbol in BNB_EXCLUDED_SYMBOLS or symbol.upper().startswith("BNB")

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "atr14" not in df.columns:
            df = self.prepare_features(df)

        # Funding kolonu hiç yoksa sinyal üretemeyiz
        if "funding_rate_lag1" not in df.columns or df["funding_rate_lag1"].isna().all():
            self._log.warning("funding_mr.no_funding_data.skip")
            return []

        p = self._get_params()
        er_max = float(p.get("kaufman_er_max", REGIME_ER_MAX))
        swing_lb = int(p.get("swing_lookback", 8))
        atr_min_pct = float(
            getattr(self.manifest.signals.filters, "atr_min_pct", 0.002) or 0.002
        )
        primary_r = float(
            self.manifest.risk.get("take_profit", {}).get("primary_R", 1.5)
        )

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "binance"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"

        # BNB exclusion — skip entirely, no signals produced
        if self._is_bnb_symbol(symbol):
            self._log.bind(symbol=symbol).info(
                "funding_mr.bnb_excluded.skip — tokenomic contamination"
            )
            return []

        # Signal.timeframe is a Literal["1m","5m","15m","1h","4h","1d","1w"].
        # 8h is not in the enum; map to "4h" (nearest supported, 2 bars = 1 funding period).
        raw_tf = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "4h"
        timeframe = "4h" if raw_tf == "8h" else raw_tf

        out: list[Signal] = []

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)

            # ATR filter
            atr_pct = float(row.get("atr_pct") or 0.0)
            if np.isnan(atr) or atr <= 0 or atr_pct < atr_min_pct:
                continue

            # --- REGIME FILTER: skip strong trends ---
            # Use lagged ER so bar t only sees history through bar t-1
            er_lag = row.get("kaufman_er_lag1")
            if er_lag is None or np.isnan(float(er_lag)):
                # Not enough history — skip conservatively
                continue
            er_val = float(er_lag)
            if er_val >= er_max:
                # Trending regime — funding extremes are momentum, not mean-rev
                continue

            # Funding values — use lag1 (lookahead-free)
            fr = row.get("funding_rate_lag1")
            fz = row.get("funding_z_lag1")
            band_high = row.get("funding_band_high")
            band_low = row.get("funding_band_low")

            if fr is None or np.isnan(float(fr)):
                continue
            fr = float(fr)
            fz = float(fz) if (fz is not None and not np.isnan(float(fz))) else 0.0

            # Adaptive bands — fall back to NaN check
            if band_high is None or np.isnan(float(band_high)):
                # Insufficient history for adaptive bands
                continue
            if band_low is None or np.isnan(float(band_low)):
                continue
            band_high = float(band_high)
            band_low = float(band_low)

            # i + 1 must exist for next-bar entry
            if i + 1 >= len(df):
                continue

            # --- SHORT signal: funding > adaptive 95th percentile + bearish reversal bar ---
            if fr > band_high and bool(row.get("reversal_bear", False)):
                # SL = recent swing high (structural)
                sl_price = float(row.get("swing_high_8") or (close + 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close + 2.0 * atr
                sl_price = max(sl_price, close + 0.3 * atr)  # Minimum distance
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_r * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="funding_fade_short",
                    confluence_score=float(abs(fz)) if fz != 0.0 else float(fr / max(abs(band_high), 1e-10)),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "funding_rate": fr,
                        "funding_z": fz,
                        "funding_band_high": band_high,
                        "kaufman_er": er_val,
                        "atr14": atr,
                        "swing_high_8": float(row.get("swing_high_8") or 0.0),
                        "reversal_bar": "bear",
                    },
                )
                out.append(sig)

            # --- LONG signal: funding < adaptive 5th percentile + bullish reversal bar ---
            elif fr < band_low and bool(row.get("reversal_bull", False)):
                # SL = recent swing low (structural)
                sl_price = float(row.get("swing_low_8") or (close - 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close - 2.0 * atr
                sl_price = min(sl_price, close - 0.3 * atr)  # Minimum distance
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_r * risk

                ts = pd.Timestamp(row["ts"]).to_pydatetime()
                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="funding_fade_long",
                    confluence_score=float(abs(fz)) if fz != 0.0 else float(abs(fr) / max(abs(band_low), 1e-10)),
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "funding_rate": fr,
                        "funding_z": fz,
                        "funding_band_low": band_low,
                        "kaufman_er": er_val,
                        "atr14": atr,
                        "swing_low_8": float(row.get("swing_low_8") or 0.0),
                        "reversal_bar": "bull",
                    },
                )
                out.append(sig)

        self._log.bind(n=len(out), bars=len(df), symbol=symbol).info(
            "funding_mr.signals.generated"
        )
        return out


__all__ = [
    "FundingMeanReversionStrategy",
    "FundingStore",
    "BNB_EXCLUDED_SYMBOLS",
    "REGIME_ER_MAX",
    "ADAPTIVE_WINDOW",
    "merge_funding_to_ohlcv",
    "_default_manifest",
    "_atr",
    "_swing_high_low",
    "_funding_z_score",
    "_adaptive_funding_bands",
    "_kaufman_er",
    "_reversal_bar_bearish",
    "_reversal_bar_bullish",
]
