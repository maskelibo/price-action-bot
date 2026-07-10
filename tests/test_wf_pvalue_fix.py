"""WF p-değeri sqrt(365)=19.1× şişme tamiri — P2 lab-istatistik 2026-07-10.

Kök-neden: _approx_pvalues `t = sr * sqrt(n)` kullanıyordu ama `sr` YILLIK
(compute_kpis ppy=365 zorlar) ve `n` GÜNLÜK bar sayısı. Geçerli Sharpe
t-istatistiği PER-PERIOD sharpe ister; yıllık sr'yi koymak annualization
sqrt'ini iki kez uygular → t sqrt(365)≈19.1× şişer → tüm ham p→0 → downstream
BH-FDR her şeyi "anlamlı" onaylar (canlıya temassız; yalnız araştırma terfi
kapısını gevşetiyordu — hiç bot terfi etmediği için gözlemlenen tek etki daha
sıkı/doğru anlamlılık).

Fix: t = sr * sqrt(n / 365) (per-period'e de-annualize). p'leri BÜYÜTÜR =
güvenli yön (yanlış-pozitif adayları reddeder, hiçbir tüketici crash etmez).
"""

from __future__ import annotations

import sys
from datetime import datetime
from math import erf, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.walk_forward import FoldResult, WalkForward  # noqa: E402


def _fold(sharpe: float, n_obs: float) -> FoldResult:
    return FoldResult(
        fold_id=0,
        train_start=datetime(2023, 1, 1),
        train_end=datetime(2025, 1, 1),
        test_start=datetime(2025, 1, 1),
        test_end=datetime(2025, 7, 1),
        best_params={},
        train_kpis={},
        test_kpis={"sharpe": sharpe, "n_obs": n_obs},
    )


def test_modest_annualized_sharpe_not_significant():
    """Yıllık SR=1.0, 180 günlük bar → per-period SR küçük → ANLAMLI DEĞİL.
    Eski kod: p≈1e-40 (t=13.4). Yeni: p≈0.24 > 0.10."""
    p = WalkForward._approx_pvalues([_fold(1.0, 180.0)])[0]
    assert p > 0.10, f"yıllık sharpe per-period t-teste ham girdi → sahte p={p!r}"


def test_inflation_factor_exactly_removed():
    """sharpe=1.0, n_obs=365 → per-period t=1.0 → p=0.1587 (erf ile).
    Eski kod t=sqrt(365)=19.105 → p~0. Şişme faktörü tam sqrt(365)."""
    p = WalkForward._approx_pvalues([_fold(1.0, 365.0)])[0]
    expected = 0.5 * (1 - erf(1.0 / sqrt(2)))  # per-period t=1.0
    assert abs(p - expected) < 1e-6, f"p={p!r}, beklenen {expected!r}"


def test_pvalue_larger_than_old_buggy_formula():
    """Fix her zaman p'yi BÜYÜTÜR (güvenli yön) — eski şişik formülle kıyas."""
    sr, n = 0.8, 200.0
    p_fixed = WalkForward._approx_pvalues([_fold(sr, n)])[0]
    t_old = sr * sqrt(n)  # eski hatalı
    p_old = 0.5 * (1 - erf(t_old / sqrt(2)))
    assert p_fixed > p_old


def test_source_pins_deannualization():
    src = (ROOT / "src" / "price_action" / "backtest" / "walk_forward.py").read_text(
        encoding="utf-8"
    )
    assert "_WF_ANNUALIZATION_PPY" in src
    assert "np.sqrt(n / _WF_ANNUALIZATION_PPY)" in src
    assert "t = sr * np.sqrt(n)\n" not in src  # eski şişik formül gitti
