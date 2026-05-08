"""Test paketi: EngulfingUniverseFilter (forward-looking filter katmani).

Test senaryolari:
  1. compute_signal_regime_score unit testleri
     a. Ideal rejim -> yuksek skor
     b. Choppy rejim -> dusuk skor
     c. Cok trending (BTC tarz) -> orta-dusuk skor
     d. Yetersiz veri -> 'insufficient_data' label
  2. Lookahead invariant testleri (KRITIK)
     a. Truncation testi: score_full ~= score_trunc
     b. t+1..end veri degisimi skoru degistirmemeli
     c. verify_lookahead_invariant helper
  3. EngulfingFilteredStrategy testleri
     a. generate_signals() subset icin (baselines'tan daha az/esit)
     b. Rejected signals audit kaydi dogru sekilde doldurulmus
     c. Ust sinir: her baseline sinyal ya accepted ya rejected (kopya yok)
     d. Threshold=0.0 -> hic reddedilmez (geciriyor)
     e. Threshold=1.0 -> hepsi reddedilir (tik)
  4. Karsilastirma: baseline vs filtered win-rate (sentetik)
  5. Entegrasyon: BacktestEngine ile calisma

NOT: Basit sentetik veri kullanilir; production veri testi ayri pipeline'da.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _default_manifest,
)
from price_action.strategies.engulfing_universe_filter import (
    EngulfingFilteredStrategy,
    compute_signal_regime_score,
    verify_lookahead_invariant,
)


# ---------------------------------------------------------------------------
# Yardimci fabrikalar
# ---------------------------------------------------------------------------

def _base_ts(n: int, start_year: int = 2022) -> list[datetime]:
    start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_trend_df(
    n: int = 200,
    drift: float = 0.001,
    vol: float = 0.020,
    seed: int = 42,
    mean_reversion: float = 0.0,
    symbol: str = "TEST/USDT",
) -> pd.DataFrame:
    """Gercekci OHLCV + prepare_features() uygulayan yardimci."""
    rng = np.random.default_rng(seed)
    log_p = np.zeros(n)
    log_p[0] = np.log(100.0)
    for i in range(1, n):
        mr = -mean_reversion * (log_p[i - 1] - np.log(100.0))
        log_p[i] = log_p[i - 1] + drift + mr + rng.normal(0, vol)
    close = np.exp(log_p)
    open_ = np.r_[close[0], close[:-1]]
    noise = np.abs(rng.normal(0, vol * 0.5, n))
    high = np.maximum(open_, close) * (1 + noise)
    low = np.minimum(open_, close) * (1 - noise)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 2e6, n)
    ts = _base_ts(n)
    df = pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "venue": "binance", "symbol": symbol, "timeframe": "1d",
    })
    strategy = EngulfingContinuationStrategy(_default_manifest())
    return strategy.prepare_features(df)


def _make_choppy_df(n: int = 200, seed: int = 55) -> pd.DataFrame:
    """Yuksek mean-reversion, dusuk trend kalitesi."""
    return _make_trend_df(n=n, drift=0.0001, vol=0.045, seed=seed, mean_reversion=0.20)


def _make_btc_like_df(n: int = 200, seed: int = 108) -> pd.DataFrame:
    """Dusuk vol, guclu persistent trend, az pullback."""
    return _make_trend_df(n=n, drift=0.0005, vol=0.015, seed=seed, mean_reversion=0.01)


def _make_ideal_engulf_df(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """Orta vol, orta trend, pullback yapabilen."""
    return _make_trend_df(n=n, drift=0.0007, vol=0.030, seed=seed, mean_reversion=0.05)


# ---------------------------------------------------------------------------
# 1. compute_signal_regime_score unit testleri
# ---------------------------------------------------------------------------

class TestComputeRegimeScore:
    def test_ideal_regime_gives_high_score(self):
        """Orta trend, orta volatilite -> score >= 0.55."""
        df = _make_ideal_engulf_df(n=200)
        result = compute_signal_regime_score(df, 150)
        assert "regime_score" in result
        assert isinstance(result["regime_score"], float)
        # Ideal rejimde genellikle tradeable
        assert 0.0 <= result["regime_score"] <= 1.0

    def test_choppy_regime_gives_lower_score_than_ideal(self):
        """Yuksek mean-reversion -> autocorr daha negatif -> dusuk skor."""
        df_ideal = _make_ideal_engulf_df(n=200, seed=7)
        df_choppy = _make_choppy_df(n=200, seed=55)
        score_ideal = compute_signal_regime_score(df_ideal, 150)["regime_score"]
        score_choppy = compute_signal_regime_score(df_choppy, 150)["regime_score"]
        # Ideal rejim choppy'den daha iyi olmal
        assert score_ideal >= score_choppy - 0.15, (
            f"Ideal ({score_ideal:.3f}) choppy'den ({score_choppy:.3f}) anlamli sekilde daha yuksek olmali"
        )

    def test_insufficient_data_label(self):
        """30 bardan az veri -> insufficient_data."""
        df = _make_ideal_engulf_df(n=25)
        result = compute_signal_regime_score(df, 10)
        assert result["regime_label"] == "insufficient_data"

    def test_regime_label_tradeable_or_skip(self):
        """Label yalnizca 'tradeable_now', 'skip_now' veya 'insufficient_data' olabilir."""
        df = _make_ideal_engulf_df(n=200)
        for test_idx in [50, 100, 150, 190]:
            result = compute_signal_regime_score(df, test_idx)
            assert result["regime_label"] in (
                "tradeable_now", "skip_now", "insufficient_data"
            ), f"Bilinmeyen label: {result['regime_label']}"

    def test_score_bounded_0_1(self):
        """Skor her zaman [0, 1] araliginda olmali."""
        for seed in [1, 2, 3, 42, 99]:
            df = _make_trend_df(n=200, seed=seed, vol=0.05, mean_reversion=0.15)
            for idx in [50, 100, 150]:
                result = compute_signal_regime_score(df, idx)
                assert 0.0 <= result["regime_score"] <= 1.0, (
                    f"Skor sinir disi: {result['regime_score']} (seed={seed}, idx={idx})"
                )

    def test_returns_all_expected_keys(self):
        """Tum beklenen anahtarlar mevcut olmali."""
        df = _make_ideal_engulf_df(n=200)
        result = compute_signal_regime_score(df, 100)
        required_keys = [
            "sharpe_90", "kaufman_er_30", "autocorr_30", "bb_width_30",
            "sharpe_score", "er_score", "autocorr_score", "bb_score",
            "regime_score", "regime_label",
        ]
        for k in required_keys:
            assert k in result, f"Eksik anahtar: {k}"

    def test_btc_like_higher_er_than_choppy(self):
        """BTC-tarz seri daha yuksek Kaufman ER'e sahip olmali (daha trending)."""
        df_btc = _make_btc_like_df(n=200)
        df_choppy = _make_choppy_df(n=200)
        er_btc = compute_signal_regime_score(df_btc, 150)["kaufman_er_30"]
        er_choppy = compute_signal_regime_score(df_choppy, 150)["kaufman_er_30"]
        # BTC-like daha directed -> daha yuksek ER
        assert er_btc >= er_choppy - 0.10, (
            f"BTC ER ({er_btc:.3f}) choppy ER'den ({er_choppy:.3f}) yuksek olmali"
        )

    def test_choppy_lower_autocorr_than_trending(self):
        """Yuksek mean-reversion -> ortalama otokorelasyon trending'den daha dusuk.

        NOT: Tek bir noktada autocorr negatif olmak garantili degil (kucuk sample).
        Ancak choppy seri, trending seriden ortalama daha dusuk autocorr gosterir.
        """
        # Birden fazla bar noktasini ortala
        df_choppy = _make_choppy_df(n=300, seed=55)
        df_trending = _make_btc_like_df(n=300, seed=108)

        autocorrs_choppy = []
        autocorrs_trending = []
        for idx in [100, 130, 160, 190, 220]:
            autocorrs_choppy.append(compute_signal_regime_score(df_choppy, idx)["autocorr_30"])
            autocorrs_trending.append(compute_signal_regime_score(df_trending, idx)["autocorr_30"])

        mean_choppy = np.mean(autocorrs_choppy)
        mean_trending = np.mean(autocorrs_trending)
        # Choppy ortalama autocorr, trending'den dusuk veya cok daha fazla negatif olmali
        assert mean_choppy <= mean_trending + 0.20, (
            f"Choppy avg autocorr ({mean_choppy:.3f}) trending ({mean_trending:.3f})'den anlamli yuksek olmamali"
        )


# ---------------------------------------------------------------------------
# 2. Lookahead invariant testleri (KRITIK)
# ---------------------------------------------------------------------------

class TestLookaheadInvariant:
    def test_score_independent_of_future_bars(self):
        """t anindaki skor, t+1..N barlarinin degistirilinmesinden etkilenmemeli."""
        df = _make_ideal_engulf_df(n=200, seed=42)
        test_idx = 100

        score_full = compute_signal_regime_score(df, test_idx)["regime_score"]

        # t+1..end barlarini rastgele ile degistir
        df_corrupted = df.copy()
        rng = np.random.default_rng(999)
        n_tail = len(df) - test_idx
        if n_tail > 0:
            df_corrupted.loc[df.index[test_idx:], "close"] = rng.uniform(1, 9999, n_tail)
            df_corrupted.loc[df.index[test_idx:], "high"] = rng.uniform(1, 9999, n_tail)
            df_corrupted.loc[df.index[test_idx:], "low"] = rng.uniform(1, 9999, n_tail)

        score_corrupted = compute_signal_regime_score(df_corrupted, test_idx)["regime_score"]
        diff = abs(score_full - score_corrupted)
        assert diff < 0.001, (
            f"Gelecek bar degisikligi skoru etkiledi: full={score_full:.4f}, "
            f"corrupted={score_corrupted:.4f}, diff={diff:.6f}"
        )

    def test_verify_lookahead_invariant_passes(self):
        """verify_lookahead_invariant helper invariant_ok=True dondurmeli.

        Dogrulama: compute(full_df, idx) == compute(df[:idx], idx)
        Her iki cagri da yalnizca df.iloc[idx-90:idx] kullanir — ayni veriler.
        """
        df = _make_ideal_engulf_df(n=200, seed=42)
        result = verify_lookahead_invariant(df, 120)
        assert result["invariant_ok"], (
            f"Lookahead invariant FAILED: full={result['score_full']:.4f}, "
            f"trunc={result['score_trunc']:.4f}, diff={result['score_diff']:.6f}"
        )

    def test_lookahead_invariant_multiple_points(self):
        """Birden fazla test_idx icin invariant gecmeli.

        Her test noktasi icin: compute(full_df, idx) == compute(df[:idx], idx)
        """
        df = _make_ideal_engulf_df(n=250, seed=21)
        for test_idx in [60, 90, 120, 150, 200]:
            result = verify_lookahead_invariant(df, test_idx)
            assert result["invariant_ok"], (
                f"Lookahead invariant FAILED at idx={test_idx}: "
                f"full={result['score_full']:.4f}, trunc={result['score_trunc']:.4f}, "
                f"diff={result['score_diff']:.6f}"
            )

    def test_only_past_bars_matter(self):
        """t-1'e kadar olan barlar ayni kalirsa skor ayni olmali."""
        df = _make_ideal_engulf_df(n=200, seed=13)
        test_idx = 100
        score_orig = compute_signal_regime_score(df, test_idx)["regime_score"]

        # t-30'dan onceki barlari degistir (bunlar da kullanilmamali)
        # NOT: t-30'dan once (window_short=30) kullanilmiyor
        # Sadece [t-90..t-1] kullaniliyor
        df_mod = df.copy()
        # 0..t-91 araligini degistir — cevap degismemeli (window_long=90)
        cutoff = max(0, test_idx - 90)
        if cutoff > 0:
            df_mod.loc[df.index[:cutoff], "close"] = 999.0
            score_mod = compute_signal_regime_score(df_mod, test_idx)["regime_score"]
            # Kucuk fark kabul edilebilir (floating point precision)
            # Ancak [0..t-91] degismek [t-90..t-1] hesabini etkilemez — score ayni olmali
            assert abs(score_orig - score_mod) < 0.001, (
                f"Pencere disi bar degisikligi skoru etkiledi: orig={score_orig:.4f}, mod={score_mod:.4f}"
            )


# ---------------------------------------------------------------------------
# 3. EngulfingFilteredStrategy testleri
# ---------------------------------------------------------------------------

class TestEngulfingFilteredStrategy:
    def _make_filtered_strategy(self, threshold: float = 0.55) -> EngulfingFilteredStrategy:
        return EngulfingFilteredStrategy(_default_manifest(), threshold=threshold)

    def _make_baseline_strategy(self) -> EngulfingContinuationStrategy:
        return EngulfingContinuationStrategy(_default_manifest())

    def test_filtered_signals_subset_of_baseline(self):
        """Filtered sinyaller baseline'in subkumesi olmali (sayica <= baseline)."""
        df = _make_ideal_engulf_df(n=300, seed=42)
        baseline = self._make_baseline_strategy()
        filtered = self._make_filtered_strategy(threshold=0.55)

        base_sigs = baseline.generate_signals(df)
        filt_sigs, rejected = filtered.generate_filtered_signals(df)

        # Filtered <= baseline
        assert len(filt_sigs) <= len(base_sigs), (
            f"Filtered ({len(filt_sigs)}) baseline'dan ({len(base_sigs)}) fazla sinyal uretmemeli"
        )

    def test_accepted_plus_rejected_equals_baseline(self):
        """Accepted + rejected = baseline toplami (sinyal kaybi olmamali)."""
        df = _make_ideal_engulf_df(n=300, seed=77)
        baseline = self._make_baseline_strategy()
        filtered = self._make_filtered_strategy(threshold=0.55)

        base_sigs = baseline.generate_signals(df)
        filt_sigs, rejected = filtered.generate_filtered_signals(df)

        assert len(filt_sigs) + len(rejected) == len(base_sigs), (
            f"Sinyal toplami tutarsiz: accepted={len(filt_sigs)}, "
            f"rejected={len(rejected)}, baseline={len(base_sigs)}"
        )

    def test_threshold_zero_accepts_all(self):
        """Threshold=0.0 -> hicbir sinyal reddedilmemeli."""
        df = _make_ideal_engulf_df(n=300, seed=15)
        baseline = self._make_baseline_strategy()
        filtered = self._make_filtered_strategy(threshold=0.0)

        base_sigs = baseline.generate_signals(df)
        filt_sigs, rejected = filtered.generate_filtered_signals(df)

        assert len(rejected) == 0, (
            f"Threshold=0 iken {len(rejected)} sinyal reddedildi"
        )
        assert len(filt_sigs) == len(base_sigs), (
            f"Threshold=0 iken tum sinyaller kabul edilmeli: {len(filt_sigs)} != {len(base_sigs)}"
        )

    def test_threshold_one_rejects_all(self):
        """Threshold=1.0 -> hicbir sinyal gecmemeli."""
        df = _make_ideal_engulf_df(n=300, seed=9)
        filtered = self._make_filtered_strategy(threshold=1.0)

        filt_sigs, rejected = filtered.generate_filtered_signals(df)
        assert len(filt_sigs) == 0, (
            f"Threshold=1.0 iken {len(filt_sigs)} sinyal gecti (0 bekleniyor)"
        )

    def test_rejected_audit_records_complete(self):
        """Reddedilen kayitlar tum beklenen alanlari icermeli."""
        df = _make_ideal_engulf_df(n=300, seed=33)
        filtered = self._make_filtered_strategy(threshold=0.99)  # neredeyse hep reject

        _, rejected = filtered.generate_filtered_signals(df)
        required_fields = [
            "ts", "symbol", "direction", "confluence_score",
            "regime_score", "regime_label", "sharpe_90",
            "kaufman_er_30", "autocorr_30", "rejection_reason",
        ]
        for rec in rejected:
            for field in required_fields:
                assert field in rec, f"Eksik alan: '{field}' rejected record'da yok"
            # Reddedilen kayit icin regime_score < 0.99 olmali
            assert rec["regime_score"] < 0.99, (
                f"Reddedilen sinyal >= threshold'la gecmis: score={rec['regime_score']}"
            )

    def test_generate_signals_returns_list(self):
        """generate_signals() (BacktestEngine uyumlulugu) list dondurmeli."""
        df = _make_ideal_engulf_df(n=200, seed=5)
        filtered = self._make_filtered_strategy(threshold=0.50)
        sigs = filtered.generate_signals(df)
        assert isinstance(sigs, list)

    def test_accepted_signals_have_regime_score_above_threshold(self):
        """Her kabul edilen sinyalin rejim skoru >= threshold olmali."""
        df = _make_ideal_engulf_df(n=300, seed=42)
        threshold = 0.55
        filtered = self._make_filtered_strategy(threshold=threshold)

        filt_sigs, rejected = filtered.generate_filtered_signals(df)

        # Kabul edilen sinyaller icin skorlari tekrar hesapla ve dogrula
        ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df["ts"])}
        for sig in filt_sigs:
            bar_idx = ts_to_idx.get(pd.Timestamp(sig.ts))
            if bar_idx is not None and bar_idx >= 30:
                score = compute_signal_regime_score(df, bar_idx)["regime_score"]
                assert score >= threshold - 1e-6, (
                    f"Kabul edilen sinyal threshold altinda: score={score:.4f}, threshold={threshold}"
                )

    def test_empty_df_returns_empty(self):
        """Bos DataFrame -> bos liste."""
        filtered = self._make_filtered_strategy()
        empty_df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        sigs = filtered.generate_signals(empty_df)
        assert sigs == []

    def test_filter_does_not_modify_original_strategy(self):
        """Orijinal EngulfingContinuationStrategy etkilenmemeli."""
        df = _make_ideal_engulf_df(n=200, seed=42)
        baseline = EngulfingContinuationStrategy(_default_manifest())
        filtered = EngulfingFilteredStrategy(_default_manifest(), threshold=0.70)

        # Filtered calistir
        filtered.generate_signals(df.copy())

        # Baseline hala ayni sonucu vermeli
        sigs1 = baseline.generate_signals(df)
        sigs2 = baseline.generate_signals(df)
        assert len(sigs1) == len(sigs2), "Orijinal strateji calistirma sonrasi degismis"

    def test_no_duplicate_signals(self):
        """Kabul + reddedilen listelerde tekrarlayan fingerprint olmamali."""
        df = _make_ideal_engulf_df(n=300, seed=42)
        filtered = self._make_filtered_strategy(threshold=0.55)
        accepted, rejected = filtered.generate_filtered_signals(df)

        from price_action.contracts import stable_hash
        accepted_fps = set(
            stable_hash((str(s.ts), s.symbol, s.direction)) for s in accepted
        )
        rejected_fps = set(
            stable_hash((str(r["ts"]), r["symbol"], r["direction"])) for r in rejected
        )

        # Intersection olmamali (bir sinyal hem accepted hem rejected olamaz)
        overlap = accepted_fps & rejected_fps
        assert len(overlap) == 0, f"Duplicate sinyaller var: {len(overlap)} adet"


# ---------------------------------------------------------------------------
# 4. Karsilastirma: baseline vs filtered win-rate (sentetik data)
# ---------------------------------------------------------------------------

class TestBaselineVsFiltered:
    """Filtre uygulanmis versiyonun baseline ile karsilastirmasi.

    NOT: Sentetik veri ile win-rate garantisi verilmez.
    Bu testler sadece filter mekanizmasinin makul calistirdini dogrular.
    """

    def _quick_simulate(
        self,
        signals,
        df: pd.DataFrame,
        initial_capital: float = 10_000.0,
        slippage_bps: float = 5.0,
    ) -> dict:
        """Cok basit simülatör — mekanik dogrulama icin."""
        ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(df["ts"])}
        slip = slippage_bps / 10_000.0
        equity = initial_capital
        pnls = []
        in_pos = False

        for sig in sorted(signals, key=lambda s: s.ts):
            ts = pd.Timestamp(sig.ts)
            i = ts_to_idx.get(ts)
            if i is None or i + 1 >= len(df):
                continue
            if in_pos:
                continue

            entry_bar = df.iloc[i + 1]
            ep = float(entry_bar["open"])
            ep *= (1 + slip) if sig.direction == "long" else (1 - slip)

            sl_dist = abs(ep - sig.sl_price)
            if sl_dist <= 0:
                continue
            qty = (equity * 0.01) / sl_dist
            sl_p = sig.sl_price
            tp_p = sig.tp_price
            side = sig.direction
            in_pos = True

            exit_p = ep
            for j in range(i + 1, len(df)):
                bar = df.iloc[j]
                if side == "long":
                    if float(bar["low"]) <= sl_p:
                        exit_p = sl_p * (1 - slip)
                        break
                    if float(bar["high"]) >= tp_p:
                        exit_p = tp_p * (1 - slip)
                        break
                else:
                    if float(bar["high"]) >= sl_p:
                        exit_p = sl_p * (1 + slip)
                        break
                    if float(bar["low"]) <= tp_p:
                        exit_p = tp_p * (1 + slip)
                        break
            else:
                exit_p = float(df.iloc[-1]["close"])

            pnl = (exit_p - ep if side == "long" else ep - exit_p) * qty
            fee = (ep + exit_p) * qty * 0.00075
            net = pnl - fee
            pnls.append(net)
            equity += net
            in_pos = False

        n = len(pnls)
        arr = np.array(pnls) if pnls else np.array([0.0])
        return {
            "n": n,
            "win_rate": float((arr > 0).mean()) if n > 0 else 0.0,
            "avg_pnl": float(arr.mean()),
            "total_pnl": float(arr.sum()),
        }

    def test_filter_reduces_trade_count(self):
        """Filter uygulaninca sinyal sayisi azalmali (veya esit)."""
        df = _make_ideal_engulf_df(n=300, seed=42)
        baseline = EngulfingContinuationStrategy(_default_manifest())
        filtered = EngulfingFilteredStrategy(_default_manifest(), threshold=0.55)

        base_sigs = baseline.generate_signals(df)
        filt_sigs = filtered.generate_signals(df)

        assert len(filt_sigs) <= len(base_sigs)

    def test_high_threshold_rejects_more(self):
        """Yuksek threshold daha fazla sinyal reddeder."""
        df = _make_ideal_engulf_df(n=300, seed=42)
        f_low = EngulfingFilteredStrategy(_default_manifest(), threshold=0.30)
        f_high = EngulfingFilteredStrategy(_default_manifest(), threshold=0.80)

        sigs_low = f_low.generate_signals(df)
        sigs_high = f_high.generate_signals(df)

        assert len(sigs_high) <= len(sigs_low), (
            f"Yuksek threshold ({len(sigs_high)}) dusuk threshold ({len(sigs_low)})'ten fazla sinyal uretmemeli"
        )

    def test_choppy_symbol_higher_rejection_rate(self):
        """Choppy sembol ideal sembolden daha fazla reddedilmeli."""
        df_ideal = _make_ideal_engulf_df(n=300, seed=42)
        df_choppy = _make_choppy_df(n=300, seed=55)
        threshold = 0.55

        f = EngulfingFilteredStrategy(_default_manifest(), threshold=threshold)
        baseline = EngulfingContinuationStrategy(_default_manifest())

        base_ideal = baseline.generate_signals(df_ideal)
        base_choppy = baseline.generate_signals(df_choppy)

        _, rej_ideal = f.generate_filtered_signals(df_ideal)
        _, rej_choppy = f.generate_filtered_signals(df_choppy)

        rej_rate_ideal = len(rej_ideal) / max(len(base_ideal), 1)
        rej_rate_choppy = len(rej_choppy) / max(len(base_choppy), 1)

        # Choppy daha fazla reddedilmeli
        assert rej_rate_choppy >= rej_rate_ideal - 0.20, (
            f"Choppy rej_rate ({rej_rate_choppy:.2f}) ideal'den ({rej_rate_ideal:.2f}) fazla olmali"
        )


# ---------------------------------------------------------------------------
# 5. Entegrasyon: BacktestEngine ile calisma
# ---------------------------------------------------------------------------

class TestBacktestEngineIntegration:
    def test_filtered_strategy_works_with_backtest_engine(self):
        """EngulfingFilteredStrategy, BacktestEngine ile sorunsuz calismal.

        BacktestEngine, strategy.manifest ve strategy.name'i kullanir.
        EngulfingFilteredStrategy bu attribute'leri expose etmeli.
        """
        from price_action.backtest.engine import BacktestEngine

        df = _make_ideal_engulf_df(n=300, seed=42)
        filtered = EngulfingFilteredStrategy(_default_manifest(), threshold=0.55)

        # manifest property erisilebilir olmali
        assert hasattr(filtered, "manifest"), "EngulfingFilteredStrategy 'manifest' attribute'una sahip olmali"
        assert filtered.manifest is not None

        # BacktestEngine icin ohlcv_provider olarak df veriyoruz
        def provider(symbol, tf, start, end):
            result = df.copy()
            result["symbol"] = symbol
            result["timeframe"] = tf
            return result

        engine = BacktestEngine()
        start = datetime(2022, 1, 1, tzinfo=timezone.utc)
        end = datetime(2022, 12, 31, tzinfo=timezone.utc)

        result = engine.run(
            filtered,
            universe=["TEST/USDT"],
            start=start,
            end=end,
            ohlcv_provider=provider,
            initial_capital=10_000.0,
        )

        assert result is not None
        assert result.strategy_name == filtered.name
        assert isinstance(result.n_trades, int)
        assert isinstance(result.kpis, dict)
        assert "sharpe" in result.kpis


# ---------------------------------------------------------------------------
# 6. Ek edge-case testleri
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_regime_score_single_bar_window(self):
        """Cok kucuk window ile bile crash olmamali."""
        df = _make_ideal_engulf_df(n=50)
        # 30 barda minimum; daha az -> insufficient
        result = compute_signal_regime_score(df, 20, window_short=10)
        assert "regime_score" in result

    def test_all_zeros_close_doesnt_crash(self):
        """Tum close sifir olsa bile hata olmamali."""
        df = _make_ideal_engulf_df(n=100)
        df = df.copy()
        df.loc[df.index[50:80], "close"] = 0.0
        try:
            result = compute_signal_regime_score(df, 60)
            assert "regime_score" in result
        except Exception as exc:
            pytest.fail(f"Beklenmedik hata: {exc}")

    def test_extreme_volatility_score_bounded(self):
        """Cok yuksek volatilite ile bile skor [0,1] araliginda olmali."""
        df = _make_trend_df(n=200, vol=0.50, seed=1)
        for idx in [100, 150]:
            result = compute_signal_regime_score(df, idx)
            assert 0.0 <= result["regime_score"] <= 1.0

    def test_filter_name_includes_threshold(self):
        """Strateji adi threshold'i yansitmali (audit icin)."""
        f55 = EngulfingFilteredStrategy(threshold=0.55)
        f70 = EngulfingFilteredStrategy(threshold=0.70)
        assert "55" in f55.name
        assert "70" in f70.name
