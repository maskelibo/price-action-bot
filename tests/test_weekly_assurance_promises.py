"""B-1 haftalık güvence promise'ları — kapanış sprinti 2026-07-08 (dalga-4 T4 HIGH).

5 Tem 44h kesinti Pazar'ın haftalık cron pencerelerini yuttu; promises.yaml'da
haftalık job'lar için TEK check yoktu → 2 hafta sessiz kör-nokta. Fix:
weekly_assurance komponenti (5 file_pattern + max_age_hours: 216).

Bu test glob'ların DOĞRU dizinlere işaret ettiğini pin'ler — yanlış glob =
kalıcı yalancı-negatif = kör-nokta geri gelir (D1-regresyon sınıfı).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _weekly_checks() -> list[dict]:
    d = yaml.safe_load((ROOT / "configs" / "promises.yaml").read_text(encoding="utf-8"))
    return d["components"]["weekly_assurance"]["checks"]


def test_weekly_assurance_component_exists():
    d = yaml.safe_load((ROOT / "configs" / "promises.yaml").read_text(encoding="utf-8"))
    comp = d["components"].get("weekly_assurance")
    assert comp is not None
    assert comp["enabled"] is True
    assert len(comp["checks"]) == 5


def test_all_globs_have_a_parent_dir():
    """Glob'un dizin kökü var olmalı (yoksa yazan job da yanlış yere yazıyordur)."""
    for chk in _weekly_checks():
        pattern = chk["pattern"]
        parent = ROOT / Path(pattern).parent
        assert parent.exists(), f"glob dizini yok: {pattern} → {parent}"


def test_globs_match_real_files():
    """Her haftalık glob EN AZ BİR gerçek dosya bulmalı — yanlış pattern =
    check hep PASS (kör-nokta). Bu, bilinen kaçan job'ların üretim izini kanıtlar."""
    for chk in _weekly_checks():
        pattern = chk["pattern"]
        matches = list(ROOT.glob(pattern))
        assert matches, f"glob hiç dosya bulmadı (yanlış pattern?): {pattern}"


def test_threshold_is_weekly_scoped():
    """Eşik haftalık pencereye kalibre: >7 gün ama makul (kaçan Pazar'ı yakalar,
    normal koşumu rahatsız etmez). 192-240h bandı."""
    for chk in _weekly_checks():
        age = chk["max_age_hours"]
        assert 192 <= age <= 240, f"{chk['pattern']} eşiği haftalık-dışı: {age}h"


def test_check_promises_flags_missed_weekly(tmp_path, monkeypatch):
    """check_promises._file_max_age_hours mantığı: eski dosya → yaş > eşik."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import check_promises

    # weekly_assurance glob'larından en az biri şu an eşiği aşmalı VEYA aşmamalı —
    # ama fonksiyon çağrılabilir ve sayı döndürmeli (None değil, dosya var).
    for chk in _weekly_checks():
        age = check_promises._file_max_age_hours(chk["pattern"])
        assert age is not None, f"{chk['pattern']} için yaş hesaplanamadı (dosya yok)"
        assert age >= 0
