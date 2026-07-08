"""F3 korelasyon fix — kapanış sprinti 2026-07-08 (dalga-4 T7 CRIT).

run_correlation_analysis, challenger'ların oos_returns'unu TRADE-İNDEKSİ
üzerinden np.corrcoef'e sokuyordu. oos_returns = returns_R_sample: timestamp'siz
+ first250+last250 SPLICE → A'nın i'inci trade'i ile B'nin i'inci trade'i farklı
zamanlarda → korelasyon ANLAMSIZ. Kanıt: aynı stratejinin 2 SL-varyantı
(aynı havuz, aynı sinyaller) ρ=0.05 (olması gereken ~0.9+).

Fix: KENDİNİ-DOĞRULAYAN sanity gate. Aynı `strategy`'den ≥2 varyant çifti
referans — bunlar ~1 olmalı; medyan ρ < 0.5 ise hizalama KANITLI bozuk →
status=INVALID_METHOD, low_correlation_pairs ÜRETİLMEZ (sahte "diversifier"
onayı yasak). Sanity çifti yoksa UNVERIFIABLE (güvenli taraf: pair üretme).
Gelecekte timestamp'li veri gelirse (sanity geçince) otomatik OK.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.lab.hypothesis_runner import HypothesisRunner, HypothesisSpec  # noqa: E402


def _spec() -> HypothesisSpec:
    return HypothesisSpec(
        hypothesis_id="HYP-TEST-CORR",
        source_path="test.md",
        hypothesis_type="analysis",
        base_strategy="vsa_climax",
        param_grid=None,
        accept_gates=[],
        executable=True,
        reason_if_not="",
    )


def _challenger(cid: str, strategy: str, returns: list[float]) -> dict:
    return {"id": cid, "strategy": strategy, "oos_returns": returns}


def _run_with(challengers):
    runner = HypothesisRunner.__new__(HypothesisRunner)  # __init__ atla (ağır)
    with patch(
        "price_action.lab.sweep_aggregator.top_cells_as_challengers",
        return_value=challengers,
    ):
        return runner.run_correlation_analysis(_spec())


def test_misaligned_same_strategy_flags_invalid():
    """Aynı stratejinin 2 varyantı düşük ρ (splice artefaktı) → INVALID_METHOD."""
    import numpy as np

    rng = np.random.default_rng(0)
    # İki bağımsız gürültü serisi — aynı stratejinin varyantları AMA ρ≈0
    # (gerçek splice/timestamp'siz durumun simülasyonu)
    a = list(rng.normal(0, 1, 200))
    b = list(rng.normal(0, 1, 200))
    challengers = [
        _challenger("vsa-sl1.0", "vsa_climax", a),
        _challenger("vsa-sl1.5", "vsa_climax", b),
    ]
    res = _run_with(challengers)
    assert res["status"] == "INVALID_METHOD"
    assert res.get("sanity_failed") is True
    # Sahte "low-corr diversifier" onayı ÜRETİLMEMELİ
    assert "low_correlation_pairs" not in res or res.get("n_low_corr_pairs", 0) == 0


def test_aligned_same_strategy_allows_result():
    """Sanity geçerse (aynı-strateji varyant ρ yüksek) → OK, low_corr üretilir.

    Gelecekte timestamp-hizalı veri geldiğinde beklenen davranış.
    """
    import numpy as np

    rng = np.random.default_rng(1)
    base = rng.normal(0, 1, 200)
    # Aynı strateji varyantları: yüksek korele (aynı sinyal, farklı ölçek)
    a = list(base + rng.normal(0, 0.05, 200))
    b = list(base * 1.2 + rng.normal(0, 0.05, 200))
    # Farklı strateji: bağımsız → gerçek düşük korelasyon
    c = list(rng.normal(0, 1, 200))
    challengers = [
        _challenger("vsa-sl1.0", "vsa_climax", a),
        _challenger("vsa-sl1.5", "vsa_climax", b),
        _challenger("grimes-sl1.0", "grimes_abc", c),
    ]
    res = _run_with(challengers)
    assert res["status"] == "OK"
    assert res["type"] == "analysis"
    # vsa×grimes gerçek düşük korelasyon çifti yakalanmalı
    assert res["n_low_corr_pairs"] >= 1
    assert res.get("sanity_passed") is True


def test_no_same_strategy_pair_is_unverifiable():
    """Her strateji tek → sanity yapılamaz → UNVERIFIABLE (pair üretme)."""
    import numpy as np

    rng = np.random.default_rng(2)
    challengers = [
        _challenger("vsa-sl1.0", "vsa_climax", list(rng.normal(0, 1, 200))),
        _challenger("grimes-sl1.0", "grimes_abc", list(rng.normal(0, 1, 200))),
    ]
    res = _run_with(challengers)
    assert res["status"] == "UNVERIFIABLE"
    assert res.get("n_low_corr_pairs", 0) == 0


def test_insufficient_challengers_unchanged():
    res = _run_with([_challenger("a", "vsa_climax", [0.1] * 100)])
    assert res["status"] == "INSUFFICIENT_DATA"


def test_short_sample_unchanged():
    challengers = [
        _challenger("a", "vsa_climax", [0.1] * 30),
        _challenger("b", "vsa_climax", [0.2] * 30),
    ]
    res = _run_with(challengers)
    assert res["status"] == "INSUFFICIENT_DATA"


def test_invalid_result_carries_diagnostic():
    """INVALID sonucu, kararı besleyenlere neyin bozuk olduğunu söylemeli."""
    import numpy as np

    rng = np.random.default_rng(3)
    challengers = [
        _challenger("vsa-a", "vsa_climax", list(rng.normal(0, 1, 200))),
        _challenger("vsa-b", "vsa_climax", list(rng.normal(0, 1, 200))),
    ]
    res = _run_with(challengers)
    assert "reason" in res
    assert "hiza" in res["reason"].lower() or "align" in res["reason"].lower()
    assert "same_strategy_median_rho" in res
