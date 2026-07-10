"""feature_sweep p-şişmesi tamiri — P2 lab-istatistik 2026-07-10.

Kök-neden: sweep_symbol scipy'nin i.i.d. Spearman p'sini ham n≈31k ile
kullanıyordu ama fwd_4h/24h/72h target'ları ÖRTÜŞEN (komşu satır h-1/h bar
paylaşır) + feature'lar rolling/ffill autokorele → p deflate → %74 FDR-pass
(imkânsız). BH ayrıca bağımsızlık varsayar; testler korele.

Fix: (1) _deoverlapped_p etkin-N ile (n_eff=n//h_bars), (2) bh_fdr → BY
(harmonic böler). İkisi de MONOTON sıkılaştırma → BH'nin geçirdiğinden fazlasını
geçirmez; canlıya temassız (yalnız araştırma aday akışı, boş listeye toleranslı).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.feature_sweep as fsw  # noqa: E402

# ---------------------------------------------------------------------------
# _target_horizon_bars
# ---------------------------------------------------------------------------


def test_horizon_parse():
    assert fsw._target_horizon_bars("fwd_4h") == 4
    assert fsw._target_horizon_bars("fwd_24h") == 24
    assert fsw._target_horizon_bars("fwd_72h") == 72


def test_horizon_parse_unknown_defaults_one():
    assert fsw._target_horizon_bars("weird_col") == 1


# ---------------------------------------------------------------------------
# _deoverlapped_p — etkin-N deflate'i düzeltir
# ---------------------------------------------------------------------------


def test_deoverlap_kills_spurious_significance():
    """Zayıf IC + dev ham n: i.i.d. p anlamlı, de-overlap p ANLAMLI DEĞİL."""
    from scipy import stats

    ic, n_raw, h = 0.02, 30_000, 24
    # i.i.d. (eski) — anlamlı çıkardı
    n = n_raw
    t_iid = ic * (((n - 2) / (1 - ic * ic)) ** 0.5)
    p_iid = float(2.0 * stats.t.sf(abs(t_iid), n - 2))
    assert p_iid < 0.05  # eski hata: anlamlı
    # de-overlap (yeni) — dürüst, anlamlı DEĞİL
    p_fixed = fsw._deoverlapped_p(ic, n_raw, h)
    assert p_fixed > 0.05


def test_deoverlap_small_neff_guard():
    """n_eff<=2 → p=1.0 (div-by-zero/negatif df yok)."""
    assert fsw._deoverlapped_p(0.5, 10, 24) == 1.0  # n_eff=0


def test_deoverlap_perfect_ic_guard():
    assert fsw._deoverlapped_p(1.0, 30_000, 4) == 1.0


def test_deoverlap_strong_signal_still_significant():
    """Gerçekten güçlü IC de-overlap sonrası da anlamlı kalır (over-tighten yok)."""
    p = fsw._deoverlapped_p(0.20, 30_000, 24)  # güçlü + bol n_eff
    assert p < 0.01


# ---------------------------------------------------------------------------
# bh_fdr — Benjamini-Yekutieli (bağımlılık altında FDR)
# ---------------------------------------------------------------------------


def _bh_pass_count_reference(pvals, alpha=0.05):
    """Karşılaştırma için düz BH (eski)."""
    ps = sorted(pvals)
    m = len(ps)
    thresh = 0
    for rank, p in enumerate(ps, start=1):
        if p <= alpha * rank / m:
            thresh = rank
    return thresh


def test_by_tightens_vs_bh():
    """BY, BH'nin geçirdiği sınırdaki adayları reddeder (harmonic sıkılaştırma)."""
    results = [{"p_is": 0.01} for _ in range(10)] + [{"p_is": 0.9} for _ in range(10)]
    bh_pass = _bh_pass_count_reference([r["p_is"] for r in results])
    assert bh_pass == 10  # düz BH hepsini geçirirdi
    out = fsw.bh_fdr([dict(r) for r in results])
    by_pass = sum(1 for r in out if r["fdr_pass"])
    assert by_pass == 0  # BY sıkılaştırınca sınırdakiler düşer
    assert by_pass <= bh_pass  # monoton: BY ⊆ BH


def test_by_keeps_genuinely_strong_signal():
    """Çok güçlü p (1e-9) BY altında da geçer — sistem tamamen kilitlenmez."""
    results = [{"p_is": 1e-9}] + [{"p_is": 0.9} for _ in range(19)]
    out = fsw.bh_fdr(results)
    assert out[0]["fdr_pass"] is True
    assert sum(1 for r in out if r["fdr_pass"]) == 1


def test_by_empty_safe():
    assert fsw.bh_fdr([]) == []


# ---------------------------------------------------------------------------
# Kaynak-pin
# ---------------------------------------------------------------------------


def test_source_pins_both_fixes():
    src = (ROOT / "scripts" / "feature_sweep.py").read_text(encoding="utf-8")
    assert "_deoverlapped_p(" in src
    assert "h_m = sum(1.0 / k for k in range(1, m + 1))" in src
    assert "alpha * rank / (m * h_m)" in src
    assert "ic_is, p_is = stats.spearmanr" not in src  # eski ham i.i.d. p gitti
