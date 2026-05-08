"""Forward-looking Universe Filter for EngulfingContinuationStrategy.

Bu modul EngulfingContinuationStrategy'yi DEGISTIRMEZ.
Sadece sinyalleri filtreleme katmani olarak sarmalamaktadir.

Tasarim prensipleri:
  1. Lookahead-free: Her sinyal icin YALNIZCA t-1 anindaki bilgi kullanilir
  2. Wrap pattern: Orijinal strateji aynen korunur, sadece signal subset secilir
  3. Test edilebilir: filter karar mantigi izole fonksiyonlar halinde

Rejim ozellikleri (t anindaki sinyal icin [t-90..t-1] kullanilir):
  - rolling_90_sharpe    : Son 90 bar Sharpe orani (trend kalitesi)
  - kaufman_er_30        : Son 30 bar Kaufman ER (trend gucu)
  - return_autocorr_30   : Son 30 bar getiri otokorelasyonu (momentum vs chop)
  - bb_width_30          : Son 30 bar Bollinger bant genisligi (volatilite rejimi)

Karar mantigi:
  Engulfing continuation en iyi calisir:
    - Orta Sharpe (0.2 - 1.8): cok trend (SL genis) veya cok chop (momentum yok) degil
    - Orta ER (0.18 - 0.55): yeterli trend ama pullback olabilecek kadar ayarli
    - Pozitif veya hafif negatif otokorelasyon (-0.10 ile +0.15): engulfing momentumu surdurulebilir
    - ATR bant eşiği: ne cok dar (spike sonrasi donme) ne cok genis (regime kırılması)

KULLANIM:
    from price_action.strategies.engulfing_universe_filter import (
        EngulfingFilteredStrategy,
        compute_signal_regime_score,
    )
    filtered = EngulfingFilteredStrategy(manifest, threshold=0.55)
    signals = filtered.generate_filtered_signals(df)
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _default_manifest,
)
from price_action.strategies.base import StrategyManifest


# =====================================================================
# Rejim skoru hesaplama (lookahead-free)
# =====================================================================

def compute_signal_regime_score(
    df: pd.DataFrame,
    signal_bar_idx: int,
    *,
    window_long: int = 90,
    window_short: int = 30,
    autocorr_lag: int = 5,
) -> dict[str, float]:
    """Sinyal bari t = signal_bar_idx icin [t-window_long..t-1] bilgisiyle
    rejim ozellikleri hesapla.

    CRITICAL LOOKAHEAD INVARIANT:
    Bu fonksiyon sadece df.iloc[start:signal_bar_idx] (yani t-1'e kadar) kullanir.
    signal_bar_idx ve sonrasi HIC kullanilmaz.

    Parametreler:
        df              : prepare_features() uygulanmis DataFrame (ema200, atr14, vol_z vs. iceriyor)
        signal_bar_idx  : Sinyalin uretildigi bar indeksi (t)
        window_long     : Uzun pencere (Sharpe icin)
        window_short    : Kisa pencere (ER, autocorr icin)
        autocorr_lag    : Getiri otokorelasyonu lag'i

    Donus:
        {
          'sharpe_90'       : float,  # anualiz Sharpe
          'kaufman_er_30'   : float,  # [0,1]
          'autocorr_30'     : float,  # [-1,1]
          'bb_width_30'     : float,  # normalize
          'regime_score'    : float,  # [0,1] — birlesik skor
          'regime_label'    : str,    # 'tradeable_now' veya 'skip_now'
        }
    """
    if signal_bar_idx < window_short + autocorr_lag:
        return {
            "sharpe_90": 0.0,
            "kaufman_er_30": 0.25,
            "autocorr_30": 0.0,
            "bb_width_30": 0.05,
            "regime_score": 0.50,
            "regime_label": "insufficient_data",
        }

    # t-1'e kadar olan subset — HIÇ t ve sonrasi yok
    t_minus_1 = signal_bar_idx  # exclusive upper bound (Python slice)
    start_long = max(0, t_minus_1 - window_long)
    start_short = max(0, t_minus_1 - window_short)

    sub_long = df.iloc[start_long:t_minus_1]  # [t-90..t-1]
    sub_short = df.iloc[start_short:t_minus_1]  # [t-30..t-1]

    close_long = sub_long["close"] if "close" in sub_long.columns else pd.Series(dtype=float)
    close_short = sub_short["close"] if "close" in sub_short.columns else pd.Series(dtype=float)

    # 1. Sharpe (90-bar)
    if len(close_long) >= 10:
        rets_l = close_long.pct_change().dropna()
        if len(rets_l) > 5 and rets_l.std(ddof=0) > 1e-12:
            sharpe_90 = float(rets_l.mean() / rets_l.std(ddof=0) * np.sqrt(365))
        else:
            sharpe_90 = 0.0
    else:
        sharpe_90 = 0.0

    # 2. Kaufman ER (30-bar)
    if len(close_short) >= 10:
        net_change = abs(float(close_short.iloc[-1]) - float(close_short.iloc[0]))
        path_len = close_short.diff().abs().sum()
        kaufman_er_30 = float(net_change / path_len) if path_len > 1e-12 else 0.0
        kaufman_er_30 = float(np.clip(kaufman_er_30, 0.0, 1.0))
    else:
        kaufman_er_30 = 0.25

    # 3. Return autocorrelation lag-N (30-bar window)
    if len(close_short) >= autocorr_lag + 5:
        rets_s = close_short.pct_change().dropna()
        if len(rets_s) >= autocorr_lag + 3:
            autocorr_30 = float(rets_s.autocorr(lag=autocorr_lag))
            if np.isnan(autocorr_30):
                autocorr_30 = 0.0
        else:
            autocorr_30 = 0.0
    else:
        autocorr_30 = 0.0

    # 4. BB width (30-bar)
    if len(close_short) >= 10:
        ret_std_30 = close_short.pct_change().std(ddof=0)
        c_mean = float(close_short.mean())
        c_last = float(close_short.iloc[-1])
        if c_mean > 1e-12 and c_last > 1e-12:
            bb_width_30 = float(2 * ret_std_30)  # 2*sigma normalized return
        else:
            bb_width_30 = 0.05
    else:
        bb_width_30 = 0.05

    # =====================================================================
    # Scoring: engulfing continuation icin ideal rejim
    # =====================================================================
    # Sharpe score: 0.2-1.8 arasi en iyi
    # <0.2: trend cok zayif / chop  |  >1.8: cok trendi, SL mesafesi buyur
    if 0.20 <= sharpe_90 <= 1.80:
        sharpe_score = 1.0
    elif sharpe_90 < 0.20:
        # -2'den 0.2'ye: sigmoidal artis
        sharpe_score = float(np.clip((sharpe_90 + 2.0) / 2.2, 0.0, 1.0))
    else:
        sharpe_score = float(np.clip(1.0 - (sharpe_90 - 1.80) / 1.50, 0.0, 1.0))

    # ER score: 0.18-0.50 arasi optimal
    # <0.18: cok choppy   |  >0.50: cok trending (pullback olmaz)
    if 0.18 <= kaufman_er_30 <= 0.50:
        er_score = 1.0
    elif kaufman_er_30 < 0.18:
        er_score = float(np.clip(kaufman_er_30 / 0.18, 0.0, 1.0))
    else:
        er_score = float(np.clip(1.0 - (kaufman_er_30 - 0.50) / 0.50, 0.0, 1.0))

    # Autocorr score: -0.10 ile +0.15 arasi optimal
    # Cok negatif autocorr: yuksek mean-reversion, engulfing devam gelmez
    # Cok pozitif: zaten trend suruyor, pullback az
    if -0.10 <= autocorr_30 <= 0.15:
        autocorr_score = 1.0
    elif autocorr_30 < -0.10:
        autocorr_score = float(np.clip(1.0 + (autocorr_30 + 0.10) / 0.30, 0.0, 1.0))
    else:
        autocorr_score = float(np.clip(1.0 - (autocorr_30 - 0.15) / 0.30, 0.0, 1.0))

    # BB width score: orta geniSligi tercih et (0.02-0.08 arasi)
    if 0.02 <= bb_width_30 <= 0.08:
        bb_score = 1.0
    elif bb_width_30 < 0.02:
        bb_score = float(np.clip(bb_width_30 / 0.02, 0.0, 1.0))
    else:
        bb_score = float(np.clip(1.0 - (bb_width_30 - 0.08) / 0.10, 0.0, 1.0))

    # Agirlikli toplam
    regime_score = (
        0.30 * sharpe_score +
        0.35 * er_score +
        0.25 * autocorr_score +
        0.10 * bb_score
    )
    regime_score = float(np.clip(regime_score, 0.0, 1.0))
    regime_label = "tradeable_now" if regime_score >= 0.55 else "skip_now"

    return {
        "sharpe_90": sharpe_90,
        "kaufman_er_30": kaufman_er_30,
        "autocorr_30": autocorr_30,
        "bb_width_30": bb_width_30,
        "sharpe_score": sharpe_score,
        "er_score": er_score,
        "autocorr_score": autocorr_score,
        "bb_score": bb_score,
        "regime_score": regime_score,
        "regime_label": regime_label,
    }


# =====================================================================
# Wrapper strateji
# =====================================================================

class EngulfingFilteredStrategy:
    """EngulfingContinuationStrategy etrafinda rejim filtresi.

    Orijinal strateji DEGISMEZ. Bu sinif:
      1. Orijinal sinyalleri alir
      2. Her sinyal icin compute_signal_regime_score() cagrilir
      3. regime_score >= threshold sinyaller gecilir
      4. Reddedilen sinyaller metadata'ya not edilir (audit)

    Constraints: DO NOT modify engulfing_continuation.py
    """

    def __init__(
        self,
        manifest: StrategyManifest | None = None,
        *,
        threshold: float = 0.55,
        log_rejections: bool = False,
    ) -> None:
        self.threshold = threshold
        self.log_rejections = log_rejections
        self._inner = EngulfingContinuationStrategy(manifest or _default_manifest())
        self._log = logger.bind(component="engulfing_filter")

    @property
    def name(self) -> str:
        return f"engulfing_filtered_t{int(self.threshold * 100)}"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def manifest(self) -> StrategyManifest:
        """BacktestEngine uyumlulugu icin: orijinal strateji manifest'ini aktar."""
        return self._inner.manifest

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Orijinal strateji feature'larini aynen kullan."""
        return self._inner.prepare_features(df)

    def generate_filtered_signals(
        self,
        df: pd.DataFrame,
    ) -> tuple[list[Signal], list[dict[str, Any]]]:
        """Sinyalleri uret ve rejim filtresi uygula.

        Returns:
            (accepted_signals, rejected_audit_records)

        accepted_signals: Signal listesi, normal backtest'e verilir
        rejected_audit_records: Reddedilen sinyal bilgisi (ts, score, reason)
        """
        if "ema20" not in df.columns:
            df = self._inner.prepare_features(df)

        all_signals = self._inner.generate_signals(df)
        ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df["ts"])}

        accepted: list[Signal] = []
        rejected_audit: list[dict[str, Any]] = []

        for sig in all_signals:
            bar_idx = ts_to_idx.get(pd.Timestamp(sig.ts))
            if bar_idx is None:
                # Indeks bulunamazsa kabul et (conservative)
                accepted.append(sig)
                continue

            rf = compute_signal_regime_score(df, bar_idx)
            score = rf["regime_score"]
            label = rf["regime_label"]

            if score >= self.threshold:
                accepted.append(sig)
            else:
                audit_rec = {
                    "ts": sig.ts,
                    "symbol": sig.symbol,
                    "direction": sig.direction,
                    "confluence_score": sig.confluence_score,
                    "regime_score": score,
                    "regime_label": label,
                    "sharpe_90": rf["sharpe_90"],
                    "kaufman_er_30": rf["kaufman_er_30"],
                    "autocorr_30": rf["autocorr_30"],
                    "bb_width_30": rf["bb_width_30"],
                    "rejection_reason": f"regime_score {score:.3f} < threshold {self.threshold}",
                }
                rejected_audit.append(audit_rec)
                if self.log_rejections:
                    self._log.bind(
                        sym=sig.symbol,
                        ts=str(sig.ts),
                        score=score,
                        label=label,
                    ).debug("filter.rejected")

        n_orig = len(all_signals)
        n_acc = len(accepted)
        n_rej = len(rejected_audit)
        self._log.bind(
            total=n_orig, accepted=n_acc, rejected=n_rej,
            rejection_rate=n_rej / max(n_orig, 1),
            threshold=self.threshold,
        ).info("engulfing_filter.applied")

        return accepted, rejected_audit

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """BacktestEngine uyumlulugu icin: sadece accepted sinyalleri dondur."""
        accepted, _ = self.generate_filtered_signals(df)
        return accepted


# =====================================================================
# Lookahead invariant dogrulama yardimcisi
# =====================================================================

def verify_lookahead_invariant(
    df: pd.DataFrame,
    test_idx: int,
    *,
    window_long: int = 90,
    window_short: int = 30,
) -> dict[str, Any]:
    """Lookahead invariantini kontrol et.

    Yontem:
      1. Full df ile test_idx icin skor hesapla -> yalnizca [test_idx-window..test_idx-1] kullanilir
      2. df'yi [0..test_idx] ile truncate et (test_idx dahil) → ayni subset -> ayni sonuc olmali
      3. Skorlar arasindaki fark ~0 olmali (floating point toleransi haric)

    Kritik nokta: compute_signal_regime_score(df, idx) her zaman df.iloc[:idx] kullanir.
    Bu nedenle df_trunc = df.iloc[:idx] olarak kesilirse, ayni cagri ayni sonucu vermeli.

    Bu fonksiyon test paketinde kullanilmak icindir.
    """
    # Full dataframe ile skor — yalnizca [test_idx-window..test_idx-1] kullanilir
    rf_full = compute_signal_regime_score(
        df, test_idx, window_long=window_long, window_short=window_short
    )

    # Truncated dataframe (test_idx sonrasi kesilmis) ile AYNI cagri
    # df_trunc = df[:test_idx] → compute(df_trunc, test_idx) = compute(df, test_idx)
    # cunku ikisi de df.iloc[start:test_idx] kullanir
    df_trunc = df.iloc[:test_idx].copy()
    rf_trunc = compute_signal_regime_score(
        df_trunc, test_idx,  # Ayni test_idx — iloc[:test_idx] yine ayni subsetin
        window_long=window_long, window_short=window_short
    )

    score_full = rf_full["regime_score"]
    score_trunc = rf_trunc["regime_score"]
    diff = abs(score_full - score_trunc)

    return {
        "test_idx": test_idx,
        "score_full": score_full,
        "score_trunc": score_trunc,
        "score_diff": diff,
        "invariant_ok": diff < 0.001,  # Floating point precision toleransi
        "full_details": rf_full,
        "trunc_details": rf_trunc,
    }


__all__ = [
    "EngulfingFilteredStrategy",
    "compute_signal_regime_score",
    "verify_lookahead_invariant",
]
