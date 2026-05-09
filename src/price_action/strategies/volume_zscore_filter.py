"""Volume Z-Score Filter — VSA tabanlı engulfing filtresi.

Konsept (VSA — Volume Spread Analysis):
    Kurumsal katılım olmadan oluşan engulfing sinyalleri (No Demand / No Supply)
    sahte kırılımlara daha yatkındır. Volume Z-Score filtresi, yalnızca hacmin
    20-bar ortalamasının belirgin üzerinde olduğu engulfing'leri geçirir.

Mekanik kural:
    vol_z = (volume_t - mean(volume, 20)) / std(volume, 20)

    - Bullish engulfing → sadece vol_z > threshold ise LONG sinyal
    - Bearish engulfing → sadece vol_z > threshold ise SHORT sinyal
    - vol_z < 0 → No Demand / No Supply → reddedilir

VSA referansı:
    knowledge/books/vsa_volume_spread_analysis.md — Bölüm 8.2
    "bullish_engulfing AND volume_zscore > 0.7  →  HIGH confidence"

Lookahead güvencesi:
    volume z-score tamamen geçmişe bakar (shift'siz, mevcut bar dahil).
    Engulfing sinyali de yalnızca t ve t-1 barı kullanır.
    Sinyal bar kapanışında üretilir; giriş bir sonraki bar açılışında.

Backtest senaryoları (run_backtest_comparison):
    1. Engulfing solo (filtre yok)
    2. Engulfing + vol_z > 0.7
    3. Engulfing + vol_z > 1.0
    4. Engulfing + vol_z > 1.5
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest


# =====================================================================
# Yardımcı hesaplamalar (vektörize, lookahead-free)
# =====================================================================

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range tabanlı ATR (EWM)."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume Z-Score: (vol_t - mean(vol, window)) / std(vol, window).

    VSA kategorisi eşleme:
        z < -1.0        → ultra-low / no-demand / no-supply
        -1.0 ≤ z < 0.5  → average (ortalama)
        0.5 ≤ z < 1.5   → high (kurumsal katılım bölgesi)
        z ≥ 1.5         → climactic (klimaktik hacim)
    """
    vmean = volume.rolling(window, min_periods=window // 2).mean()
    vstd = volume.rolling(window, min_periods=window // 2).std(ddof=1)
    return (volume - vmean) / vstd.replace(0.0, np.nan)


def _swing_sl(df: pd.DataFrame, direction: str, lookback: int = 10) -> pd.Series:
    """Yapısal stop-loss: swing low/high (shifted, lookahead-free)."""
    if direction == "long":
        return df["low"].shift(1).rolling(lookback, min_periods=1).min()
    return df["high"].shift(1).rolling(lookback, min_periods=1).max()


# =====================================================================
# Engulfing tespiti (yeniden — bağımsız, candles.py'ye bağımlı değil)
# =====================================================================

def _bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Bullish engulfing: prev_bar bearish, cur_bar bullish ve sarar."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_bearish = prev_c < prev_o
    cur_bullish = c > o
    engulf = (o <= prev_c) & (c >= prev_o)
    return (prev_bearish & cur_bullish & engulf).fillna(False)


def _bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Bearish engulfing: prev_bar bullish, cur_bar bearish ve sarar."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_bullish = prev_c > prev_o
    cur_bearish = c < o
    engulf = (o >= prev_c) & (c <= prev_o)
    return (prev_bullish & cur_bearish & engulf).fillna(False)


# =====================================================================
# filter_engulfing_with_volume_zscore — standalone filtre fonksiyonu
# =====================================================================

def filter_engulfing_with_volume_zscore(
    signals: list[Signal],
    df: pd.DataFrame,
    *,
    vol_z_threshold: float = 0.7,
    vol_z_window: int = 20,
) -> tuple[list[Signal], int]:
    """Mevcut engulfing sinyallerini volume z-score filtresiyle elek.

    Parametreler
    ----------
    signals:
        Herhangi bir kaynaktan gelen Signal listesi.
    df:
        OHLCV DataFrame (volume kolonu gerekli). ts kolonu datetime UTC.
    vol_z_threshold:
        Minimum volume z-score eşiği. Default 0.7 (VSA "high" bölgesi başlangıcı).
        vol_z < 0 → No Demand/No Supply → kesinlikle reddedilir.
    vol_z_window:
        Z-score hesaplama penceresi (bar). Default 20 (VSA Williams önerisi).

    Döndürür
    -------
    tuple[list[Signal], int]
        (geçen_sinyaller, reddedilen_sayısı)
    """
    if not signals:
        return [], 0

    if "volume" not in df.columns:
        logger.warning("vol_zscore_filter.no_volume_column")
        return signals, 0

    # Z-score hesapla ve ts→z-score lookup tablosu oluştur
    df_sorted = df.sort_values("ts").copy()
    df_sorted["_vol_z"] = _volume_zscore(df_sorted["volume"], window=vol_z_window)

    # ts → vol_z hızlı lookup
    ts_norm = df_sorted["ts"].apply(
        lambda t: pd.Timestamp(t).tz_convert("UTC").normalize()
        if pd.Timestamp(t).tzinfo is not None
        else pd.Timestamp(t).tz_localize("UTC").normalize()
    )
    vol_z_lookup: dict[pd.Timestamp, float] = dict(zip(ts_norm, df_sorted["_vol_z"]))

    passed: list[Signal] = []
    n_rejected = 0

    for sig in signals:
        sig_date = pd.Timestamp(sig.ts)
        if sig_date.tzinfo is None:
            sig_date = sig_date.tz_localize("UTC")
        else:
            sig_date = sig_date.tz_convert("UTC")
        sig_date_norm = sig_date.normalize()

        vol_z_val = vol_z_lookup.get(sig_date_norm, np.nan)

        if np.isnan(vol_z_val):
            # Z-score hesaplanamıyorsa (warmup dönemi): geçir (konservatif)
            passed.append(sig)
            continue

        if vol_z_val < vol_z_threshold:
            n_rejected += 1
            logger.bind(
                ts=str(sig.ts), vol_z=round(float(vol_z_val), 3),
                threshold=vol_z_threshold, direction=sig.direction,
            ).debug("vol_zscore_filter.rejected")
            continue

        passed.append(sig)

    logger.bind(
        total=len(signals),
        passed=len(passed),
        rejected=n_rejected,
        threshold=vol_z_threshold,
    ).info("vol_zscore_filter.applied")

    return passed, n_rejected


# =====================================================================
# Manifest default
# =====================================================================

def _default_vol_zscore_manifest(vol_z_threshold: float = 0.7) -> StrategyManifest:
    raw: dict[str, Any] = {
        "name": "volume_zscore_filter",
        "version": "1.0.0",
        "description": (
            "VSA tabanlı Volume Z-Score filtreli engulfing stratejisi. "
            "Yalnızca kurumsal hacim teyitli engulfing'leri geçirir."
        ),
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_vol_confirmed",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vol_z_threshold": vol_z_threshold,
                        "vol_z_window": 20,
                        "swing_sl_lookback": 10,
                    },
                },
                {
                    "id": "bearish_engulfing_vol_confirmed",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vol_z_threshold": vol_z_threshold,
                        "vol_z_window": 20,
                        "swing_sl_lookback": 10,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 10,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 10,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.002,
                "volume_zscore_min": vol_z_threshold,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,
                "bonus_if_at_sr": 0.0,
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
# VolumeZScoreFilterStrategy
# =====================================================================

class VolumeZScoreFilterStrategy(Strategy):
    """Volume Z-Score filtreli engulfing stratejisi (VSA tabanlı).

    LONG  : bullish_engulfing(t) AND vol_z(t) > vol_z_threshold
    SHORT : bearish_engulfing(t) AND vol_z(t) > vol_z_threshold
    Reddedilir: vol_z(t) < 0 (No Demand / No Supply bölgesi)

    SL    : 10-bar swing low/high (yapısal stop)
    TP    : 2R (R = entry - SL)

    Parametreler
    ----------
    vol_z_threshold:
        Filtre eşiği. Önerilen değerler: 0.7, 1.0, 1.5.
        0.0 → filtre yok (sadece engulfing solo, baseline için).
    vol_z_window:
        Z-score rolling penceresi (bar). Default 20.
    """

    name = "volume_zscore_filter"

    def __init__(
        self,
        manifest: StrategyManifest | None = None,
        *,
        vol_z_threshold: float = 0.7,
        vol_z_window: int = 20,
    ) -> None:
        if manifest is None:
            manifest = _default_vol_zscore_manifest(vol_z_threshold)
        super().__init__(manifest)
        self.vol_z_threshold = vol_z_threshold
        self.vol_z_window = vol_z_window

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # ATR
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)

        # Volume Z-Score (20 bar, VSA penceresi)
        if "volume" in df.columns:
            df["vol_z"] = _volume_zscore(df["volume"], window=self.vol_z_window)
        else:
            df["vol_z"] = np.nan

        # Yapısal stop-loss seviyeleri
        df["struct_sl_long"] = _swing_sl(df, "long", lookback=10)
        df["struct_sl_short"] = _swing_sl(df, "short", lookback=10)

        # Engulfing bayrakları
        df["bull_eng"] = _bullish_engulfing(df)
        df["bear_eng"] = _bearish_engulfing(df)

        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty:
            return []
        if "vol_z" not in df.columns:
            df = self.prepare_features(df)

        venue = str(df["venue"].iloc[0]) if "venue" in df.columns else "unknown"
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        timeframe = str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "1d"
        primary_R = 2.0

        atr_min = float(
            getattr(self.manifest.signals.filters, "atr_min_pct", 0.002) or 0.002
        )

        out: list[Signal] = []

        for i in range(1, len(df)):
            row = df.iloc[i]

            close = float(row["close"])
            atr = float(row.get("atr14") or 0.0)
            if atr <= 0 or np.isnan(atr):
                continue

            atr_pct = float(row.get("atr_pct") or 0.0)
            if atr_min > 0 and (np.isnan(atr_pct) or atr_pct < atr_min):
                continue

            vol_z = float(row.get("vol_z") if row.get("vol_z") is not None else np.nan)

            # Volume Z-Score filtresi
            # threshold=0.0 → filtre yok (solo engulfing baseline modu)
            if self.vol_z_threshold > 0.0:
                if np.isnan(vol_z) or vol_z < self.vol_z_threshold:
                    continue

            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            # --- LONG: Bullish Engulfing + Vol Z-Score ---
            if bool(row.get("bull_eng", False)):
                sl_price = float(row.get("struct_sl_long") or (close - 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close - 2.0 * atr
                sl_price = min(sl_price, close - 1.0 * atr)
                risk = close - sl_price
                if risk <= 0:
                    continue
                tp_price = close + primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="long",
                    pattern_id="bullish_engulfing_vol_confirmed",
                    confluence_score=1.5,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "vol_z": round(float(vol_z), 4) if not np.isnan(vol_z) else None,
                        "vol_z_threshold": self.vol_z_threshold,
                        "atr14": atr,
                        "pattern": "bullish_engulfing",
                    },
                )
                out.append(sig)

            # --- SHORT: Bearish Engulfing + Vol Z-Score ---
            elif bool(row.get("bear_eng", False)):
                sl_price = float(row.get("struct_sl_short") or (close + 2.0 * atr))
                if np.isnan(sl_price) or sl_price <= 0:
                    sl_price = close + 2.0 * atr
                sl_price = max(sl_price, close + 1.0 * atr)
                risk = sl_price - close
                if risk <= 0:
                    continue
                tp_price = close - primary_R * risk

                sig = self.emit_signal(
                    ts=ts,
                    venue=venue,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="short",
                    pattern_id="bearish_engulfing_vol_confirmed",
                    confluence_score=1.5,
                    sl_price=float(sl_price),
                    tp_price=float(tp_price),
                    suggested_size_atr=1.0,
                    metadata={
                        "vol_z": round(float(vol_z), 4) if not np.isnan(vol_z) else None,
                        "vol_z_threshold": self.vol_z_threshold,
                        "atr14": atr,
                        "pattern": "bearish_engulfing",
                    },
                )
                out.append(sig)

        self._log.bind(
            n=len(out),
            bars=len(df),
            threshold=self.vol_z_threshold,
        ).info("volume_zscore_filter.signals.generated")
        return out


# =====================================================================
# Backtest karşılaştırma yardımcısı
# =====================================================================

def run_backtest_comparison(
    df: pd.DataFrame,
    *,
    thresholds: list[float] | None = None,
    initial_capital: float = 10_000.0,
    slippage_bps: float = 5.0,
    fees: dict[str, float] | None = None,
) -> dict[str, Any]:
    """4 senaryoyu çalıştır ve karşılaştırma tablosu döndür.

    Senaryolar:
        0.0  → Engulfing solo (filtre yok) — baseline
        0.7  → vol_z > 0.7 (VSA "high" başlangıcı)
        1.0  → vol_z > 1.0 (orta eşik)
        1.5  → vol_z > 1.5 (VSA "climactic" başlangıcı)

    Döndürür
    -------
    dict keyleri:
        results  : her threshold için BacktestResult
        summary  : pd.DataFrame — sinyal sayısı, win rate, CAGR, Sharpe
        optimal  : en yüksek Sharpe'ı veren threshold
        verdict  : metin özet
    """
    from datetime import datetime, timezone

    from price_action.backtest.engine import BacktestEngine

    if thresholds is None:
        thresholds = [0.0, 0.7, 1.0, 1.5]
    fees = fees or {"taker": 0.00075, "maker": -0.00010}

    # df'den symbol/venue bilgisi
    symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "BTC/USDT"
    if "venue" not in df.columns:
        df = df.copy()
        df["venue"] = "binance"
    if "timeframe" not in df.columns:
        df = df.copy()
        df["timeframe"] = "1d"

    # Tarih aralığı
    ts_series = pd.to_datetime(df["ts"])
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize("UTC")
    start_dt = ts_series.min().to_pydatetime()
    end_dt = ts_series.max().to_pydatetime()

    def _provider(sym: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
        return df.copy()

    results: dict[float, Any] = {}
    summary_rows: list[dict[str, Any]] = []
    engine = BacktestEngine()

    for thr in thresholds:
        strat = VolumeZScoreFilterStrategy(vol_z_threshold=thr)
        res = engine.run(
            strat,
            universe=[symbol],
            start=start_dt,
            end=end_dt,
            fees=fees,
            slippage_bps=slippage_bps,
            initial_capital=initial_capital,
            timeframe="1d",
            ohlcv_provider=_provider,
        )
        results[thr] = res

        # Signal sayısı — direkt sayalım
        strat2 = VolumeZScoreFilterStrategy(vol_z_threshold=thr)
        df_feat = strat2.prepare_features(df.copy())
        sigs = strat2.generate_signals(df_feat)
        n_signals = len(sigs)

        kpis = res.kpis
        win_rate = kpis.get("win_rate", np.nan)
        cagr = kpis.get("cagr", np.nan)
        sharpe = kpis.get("sharpe", np.nan)
        max_dd = kpis.get("max_drawdown", np.nan)
        n_trades = res.n_trades

        row: dict[str, Any] = {
            "threshold": thr,
            "label": "solo (no filter)" if thr == 0.0 else f"vol_z > {thr}",
            "n_signals": n_signals,
            "n_trades": n_trades,
            "win_rate": win_rate,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
        }
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows).set_index("threshold")

    # Sinyal azalma oranı (baseline=0.0)
    baseline_n = summary_df.loc[0.0, "n_signals"] if 0.0 in summary_df.index else 1
    summary_df["signal_reduction_pct"] = (
        (1 - summary_df["n_signals"] / max(baseline_n, 1)) * 100
    ).round(1)

    # Win rate değişimi (baseline'a göre)
    baseline_wr = summary_df.loc[0.0, "win_rate"] if 0.0 in summary_df.index else np.nan
    summary_df["win_rate_uplift_ppt"] = (summary_df["win_rate"] - baseline_wr).round(3)

    # CAGR değişimi
    baseline_cagr = summary_df.loc[0.0, "cagr"] if 0.0 in summary_df.index else np.nan
    summary_df["cagr_change_ppt"] = (summary_df["cagr"] - baseline_cagr).round(4)

    # Optimal: en yüksek Sharpe (sadece filtreli senaryolar, thr > 0)
    filtered_rows = summary_df[summary_df.index > 0.0]
    if not filtered_rows.empty and filtered_rows["sharpe"].notna().any():
        optimal_thr = float(filtered_rows["sharpe"].idxmax())
    else:
        optimal_thr = 0.0

    # Verdict
    opt_row = summary_df.loc[optimal_thr] if optimal_thr in summary_df.index else None
    if opt_row is not None and not np.isnan(opt_row.get("win_rate_uplift_ppt", np.nan)):
        wr_up = float(opt_row["win_rate_uplift_ppt"])
        sig_red = float(opt_row["signal_reduction_pct"])
        cagr_ch = float(opt_row["cagr_change_ppt"])
        if wr_up > 0.02 and opt_row["sharpe"] > summary_df.loc[0.0, "sharpe"]:
            verdict = (
                f"VERDICT: Volume Z-Score filtresi FAYDALI. "
                f"Optimal threshold = {optimal_thr} → "
                f"win rate +{wr_up*100:.1f}pp, sinyal azalma {sig_red:.0f}%, "
                f"CAGR delta {cagr_ch*100:+.1f}pp. "
                f"VSA kurumsal hacim onayı engulfing kalitesini artırıyor."
            )
        elif wr_up > 0:
            verdict = (
                f"VERDICT: Hafif pozitif etki. "
                f"Threshold {optimal_thr} → win rate +{wr_up*100:.1f}pp "
                f"ama sinyal azalma {sig_red:.0f}% ile trade sayısı düşüyor. "
                f"Risk/getiri dengesi piyasa koşullarına bağlı."
            )
        else:
            verdict = (
                f"VERDICT: Volume Z-Score filtresi bu veri setinde NÖTR/NEGATİF. "
                f"Win rate uplift = {wr_up*100:.1f}pp (düşük/negatif). "
                f"Engulfing sinyalleri bu sembolde hacim bağımsız çalışıyor olabilir."
            )
    else:
        verdict = "VERDICT: Yetersiz trade sayısı — sonuç belirsiz."

    logger.bind(
        optimal_threshold=optimal_thr,
        n_scenarios=len(thresholds),
    ).info("vol_zscore_backtest.comparison.done")

    return {
        "results": results,
        "summary": summary_df,
        "optimal": optimal_thr,
        "verdict": verdict,
    }
