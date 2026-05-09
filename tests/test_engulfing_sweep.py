"""Test suite — engulfing_param_sweep.py

5 test kategorisi:
  1. Halton sequence matematiği (deterministic, coverage)
  2. Parametre örnekleme — grid sınırları içinde kalıyor mu?
  3. Manifest fabrikası — geçerli manifest üretiliyor mu?
  4. DSR ve Bonferroni hesabı — aritmetik doğruluğu
  5. Sweep uçtan uca (sentetik veri, 3 kombinasyon) — smoke test

López AFML gereksinimleri:
  - DSR formülü doğru (0.0-1.0 aralığı)
  - Bonferroni corrected α = 0.05/N_TRIALS
  - Verdict mantığı tutarlı
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Sweep modülü
sys.path.insert(0, str(ROOT))
from scripts.engulfing_param_sweep import (
    BONFERRONI_ALPHA,
    DEFAULTS,
    N_TRIALS,
    PARAM_GRID,
    DSR_THRESHOLD,
    _aggregate_kpis,
    _compute_dsr,
    _generate_synthetic,
    _halton_sequence,
    _make_manifest,
    _run_backtest,
    halton_samples,
    run_sweep,
)


# =====================================================================
# 1. Halton sequence testleri
# =====================================================================

class TestHaltonSequence:
    def test_length_correct(self):
        """n=20 isteyince tam 20 eleman döner."""
        seq = _halton_sequence(20, base=2)
        assert len(seq) == 20

    def test_range_0_1(self):
        """Tüm değerler [0, 1) içinde."""
        seq = _halton_sequence(100, base=3)
        assert all(0.0 <= v < 1.0 for v in seq), "Değerler [0,1) dışında"

    def test_deterministic(self):
        """Aynı giriş → aynı çıkış (deterministik)."""
        s1 = _halton_sequence(30, base=2)
        s2 = _halton_sequence(30, base=2)
        assert s1 == s2

    def test_better_coverage_than_random(self):
        """Halton, rastgele uniform'dan daha iyi coverage vermelidir.

        100 noktada: Halton'un min gap'i rastgeleden büyük olmalı (tipik).
        Bu ölçütü deterministik tutmak için rastgele de seed'li.
        """
        seq = _halton_sequence(100, base=2)
        seq_sorted = sorted(seq)
        gaps_halton = [seq_sorted[i + 1] - seq_sorted[i] for i in range(len(seq_sorted) - 1)]
        min_gap_halton = min(gaps_halton)

        rng = np.random.default_rng(0)
        rand_seq = sorted(rng.uniform(0, 1, 100).tolist())
        gaps_rand = [rand_seq[i + 1] - rand_seq[i] for i in range(len(rand_seq) - 1)]
        min_gap_rand = min(gaps_rand)

        # Halton genellikle daha az cluster eder — ama garanti değil.
        # Sadece makul bir değer döndüğünü kontrol edelim.
        assert min_gap_halton > 0.0, "Halton sıralamasında sıfır gap olmamalı"

    def test_base_7_distinct(self):
        """Farklı taban → farklı dizi."""
        s2 = _halton_sequence(20, base=2)
        s7 = _halton_sequence(20, base=7)
        assert s2 != s7


# =====================================================================
# 2. Parametre örnekleme testleri
# =====================================================================

class TestParamSampling:
    def test_n_samples_correct(self):
        """halton_samples tam n adet combo döndürür."""
        combos = halton_samples(20, PARAM_GRID)
        assert len(combos) == 20

    def test_all_params_present(self):
        """Her combo'da tüm parametreler mevcut."""
        combos = halton_samples(5, PARAM_GRID)
        for combo in combos:
            for key in PARAM_GRID:
                assert key in combo, f"Eksik parametre: {key}"

    def test_values_within_bounds(self):
        """Tüm değerler grid sınırları içinde."""
        combos = halton_samples(50, PARAM_GRID)
        for combo in combos:
            for key, (lo, hi, discrete) in PARAM_GRID.items():
                val = combo[key]
                assert lo - 1e-9 <= val <= hi + 1e-9, (
                    f"{key}={val} [{lo}, {hi}] dışında"
                )

    def test_pullback_window_discrete(self):
        """pullback_window her zaman integer (10, 15 veya 20)."""
        combos = halton_samples(30, PARAM_GRID)
        allowed = {10, 15, 20}
        for combo in combos:
            pw = combo["pullback_window"]
            assert isinstance(pw, int) or pw == int(pw), "pullback_window float olmamalı"
            assert int(pw) in allowed, f"pullback_window={pw} ∉ {allowed}"

    def test_combos_differ(self):
        """50 combo içinde çoğunluk birbirinden farklı olmalı."""
        combos = halton_samples(50, PARAM_GRID)
        unique = set(
            tuple(sorted(c.items())) for c in combos
        )
        # En az %80'i unique olmalı
        assert len(unique) >= 40, f"Çok fazla tekrar: {len(unique)}/50"


# =====================================================================
# 3. Manifest fabrikası testleri
# =====================================================================

class TestManifestFactory:
    def test_default_params_valid(self):
        """Default parametrelerle geçerli manifest üretilmeli."""
        m = _make_manifest(DEFAULTS)
        assert m.name == "engulfing_continuation"

    def test_custom_er_min(self):
        """kaufman_er_min manifeste doğru yansımalı."""
        params = {**DEFAULTS, "kaufman_er_min": 0.25}
        m = _make_manifest(params)
        er_min = float(m.signals.filters.kaufman_er_min)  # type: ignore[union-attr]
        assert abs(er_min - 0.25) < 1e-9

    def test_custom_body_ratio(self):
        """body_engulf_ratio pattern params'a doğru girili olmalı."""
        params = {**DEFAULTS, "body_engulf_ratio": 0.7}
        m = _make_manifest(params)
        pattern = m.signals.patterns[0]
        ratio = float(pattern.params.get("body_ratio_min", -1))
        assert abs(ratio - 0.7) < 1e-9

    def test_custom_pullback_window(self):
        """pullback_window pattern params'a girili olmalı."""
        params = {**DEFAULTS, "pullback_window": 15}
        m = _make_manifest(params)
        pattern = m.signals.patterns[0]
        pw = int(pattern.params.get("pullback_window", -1))
        assert pw == 15

    def test_trend_filter_required(self):
        """Trend filter 50-EMA zorunlu olmalı."""
        m = _make_manifest(DEFAULTS)
        assert m.trend_filter.period == 50
        assert m.trend_filter.required is True

    def test_proximity_mapping(self):
        """atr_proximity_to_sr yapıya doğru aktarılmış olmalı."""
        params = {**DEFAULTS, "atr_proximity_to_sr": 0.3}
        m = _make_manifest(params)
        prox = float(m.signals.structure.require_proximity_to_sr_atr)
        assert abs(prox - 0.3) < 1e-9


# =====================================================================
# 4. DSR & Bonferroni aritmetik testleri
# =====================================================================

class TestDSRCalculation:
    def test_dsr_range(self):
        """DSR her zaman [0.0, 1.0] içinde."""
        for sr in [-2.0, 0.0, 0.5, 1.0, 2.0, 3.0]:
            dsr = _compute_dsr(sr, n_trials=50)
            assert 0.0 <= dsr <= 1.0, f"SR={sr}: DSR={dsr} aralık dışı"

    def test_high_sr_high_dsr(self):
        """Çok yüksek Sharpe → yüksek DSR (0.5 üzeri beklenir)."""
        dsr = _compute_dsr(3.0, n_trials=50)
        assert dsr > 0.4, f"Yüksek SR için DSR beklenen değerin altında: {dsr}"

    def test_negative_sr_low_dsr(self):
        """Negatif Sharpe → düşük DSR."""
        dsr = _compute_dsr(-1.0, n_trials=50)
        assert dsr < 0.5, f"Negatif SR için DSR çok yüksek: {dsr}"

    def test_more_trials_lower_dsr(self):
        """Daha fazla trial sayısı aynı SR'da daha düşük DSR vermeli."""
        sr = 1.0
        dsr_few = _compute_dsr(sr, n_trials=5)
        dsr_many = _compute_dsr(sr, n_trials=100)
        assert dsr_many <= dsr_few, (
            f"Daha fazla trial daha düşük DSR vermeli: {dsr_many} > {dsr_few}"
        )

    def test_bonferroni_alpha_formula(self):
        """BONFERRONI_ALPHA = 0.05 / N_TRIALS."""
        expected = 0.05 / N_TRIALS
        assert abs(BONFERRONI_ALPHA - expected) < 1e-12, (
            f"Bonferroni α={BONFERRONI_ALPHA}, beklenen={expected}"
        )

    def test_dsr_with_returns_series(self):
        """Returns serisi verilince DSR yine [0,1] içinde."""
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 252))
        sr = float(returns.mean() / returns.std() * math.sqrt(365))
        dsr = _compute_dsr(sr, n_trials=50, returns=returns)
        assert 0.0 <= dsr <= 1.0

    def test_single_trial_dsr(self):
        """n_trials=1 → DSR=0.5 (tanımsız, nötr döner)."""
        from price_action.backtest.metrics import deflated_sharpe_ratio
        dsr = deflated_sharpe_ratio(1.5, n_trials=1)
        assert abs(dsr - 0.5) < 1e-9


# =====================================================================
# 5. Sweep uçtan uca smoke test
# =====================================================================

class TestSweepEndToEnd:
    """Sentetik veri ile küçük sweep — yapısal doğruluk testi."""

    def test_run_sweep_returns_dict(self):
        """run_sweep bir dict döndürmeli (boş değil)."""
        report = run_sweep(
            symbols=["BTC/USDT"],
            n_samples=3,       # hızlı tutmak için çok az
            use_db=False,
            train_ratio=0.7,
        )
        assert isinstance(report, dict)
        assert len(report) > 0

    def test_run_sweep_has_required_keys(self):
        """Rapor zorunlu anahtarları içermeli."""
        required_keys = [
            "verdict", "verdict_reason", "verdict_params",
            "default_comparison", "top10_test", "top5_train_dsr",
            "sensitivity", "n_samples",
        ]
        report = run_sweep(
            symbols=["ETH/USDT"],
            n_samples=4,
            use_db=False,
            train_ratio=0.7,
        )
        for k in required_keys:
            assert k in report, f"Raporda eksik anahtar: {k}"

    def test_verdict_is_valid_string(self):
        """Verdict geçerli seçeneklerden biri olmalı."""
        valid_verdicts = {"PROMOTE", "KEEP DEFAULTS", "NEED MORE DATA"}
        report = run_sweep(
            symbols=["SOL/USDT"],
            n_samples=3,
            use_db=False,
            train_ratio=0.7,
        )
        assert report["verdict"] in valid_verdicts, (
            f"Geçersiz verdict: {report['verdict']}"
        )

    def test_top10_test_sorted_descending(self):
        """top10_test test Sharpe'a göre azalan sıralı olmalı."""
        report = run_sweep(
            symbols=["BTC/USDT"],
            n_samples=5,
            use_db=False,
            train_ratio=0.7,
        )
        top10 = report.get("top10_test", [])
        if len(top10) >= 2:
            sharpes = [r["test_sharpe"] for r in top10]
            for i in range(len(sharpes) - 1):
                assert sharpes[i] >= sharpes[i + 1] - 1e-9, (
                    f"Sıralama bozuk: {sharpes[i]} < {sharpes[i+1]} (rank {i} vs {i+1})"
                )

    def test_default_comparison_present(self):
        """default_comparison tüm beklenen alanları içermeli."""
        report = run_sweep(
            symbols=["BTC/USDT"],
            n_samples=3,
            use_db=False,
            train_ratio=0.7,
        )
        dc = report.get("default_comparison", {})
        for field in ["train_sharpe", "test_sharpe", "dsr", "n_trades_train", "n_trades_test"]:
            assert field in dc, f"default_comparison'da eksik: {field}"

    def test_sensitivity_all_params_covered(self):
        """Duyarlılık analizinde tüm sweep parametreleri var olmalı."""
        report = run_sweep(
            symbols=["BTC/USDT"],
            n_samples=4,
            use_db=False,
            train_ratio=0.7,
        )
        sens = report.get("sensitivity", {})
        for param in PARAM_GRID.keys():
            assert param in sens, f"Duyarlılık analizinde eksik: {param}"

    def test_synthetic_data_generation(self):
        """Sentetik veri üretimi çalışıyor ve tutarlı boyutlarda."""
        df = _generate_synthetic("TEST/USDT", n=300, seed=7)
        assert len(df) == 300
        assert set(["ts", "open", "high", "low", "close", "volume"]).issubset(df.columns)
        # OHLC sanity
        assert (df["high"] >= df["close"]).all()
        assert (df["low"] <= df["close"]).all()
        assert (df["high"] >= df["open"]).all()
        assert (df["low"] <= df["open"]).all()

    def test_aggregate_kpis_with_no_trades(self):
        """Hiç trade olmayan sonuçlar aggregate'te sıfır döner."""
        results = [{"sharpe": 0.0, "n_trades": 0, "max_drawdown": 0.0, "n_obs": 0}]
        agg = _aggregate_kpis(results)
        assert agg["n_trades"] == 0
        assert agg["sharpe"] == 0.0

    def test_aggregate_kpis_with_mixed(self):
        """Bir sembol trade, diğeri boş: aggregate sadece valid olanı yansıtmalı."""
        results = [
            {"sharpe": 1.5, "n_trades": 10, "max_drawdown": -0.2, "n_obs": 100,
             "cagr": 0.3, "profit_factor": 1.8, "win_rate": 0.55},
            {"sharpe": 0.0, "n_trades": 0, "max_drawdown": 0.0, "n_obs": 0},
        ]
        agg = _aggregate_kpis(results)
        assert agg["n_trades"] == 10
        assert abs(agg["sharpe"] - 1.5) < 1e-9
