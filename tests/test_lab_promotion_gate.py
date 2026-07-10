"""T5-03(b) — lab promote enforcement gate (2026-07-10).

İstatistiksel gate'leri (DSR/effect/MaxDD) geçen aday, şu iki iz olmadan
``promote_candidate`` OLAMAZ (deterministik kod kapısı, LLM'siz):
  1. risk_officer ENDORSE dokümanı (memory/risk_officer/decisions/*endorse*.md)
  2. adversary kill-probe PASS izi (reports/adversary/, "Passed: **True**")

Coverage:
1. Gate saf fonksiyon: yok→blok, yalnız-endorse→blok, probe-FAIL→blok,
   endorse+PASS→geçer, boş id→fail-closed
2. weekly_tournament uçtan uca (PA_LLM_DRY_RUN): endorse yok →
   'blocked_pending_endorsement' (rapor 'promote_candidate' İÇERMEZ);
   endorse+PASS var → 'promote_candidate'
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from price_action.agents.lab_scientist import (
    LabScientistAgent,
    promotion_enforcement_gate,
)

CAND = "hyp-2026-07-10-gate-test-kaufman-band"


# ---------------------------------------------------------------------------
# Yardımcılar — sahte kanıt doc'ları
# ---------------------------------------------------------------------------
def _write_endorse(decisions_dir: Path, candidate_id: str = CAND) -> Path:
    decisions_dir.mkdir(parents=True, exist_ok=True)
    p = decisions_dir / "2026-07-10T000000-endorse-gate-test.md"
    p.write_text(
        "---\ndoc_type: endorse\nagent_id: risk_officer\n"
        f'depends_on: ["{candidate_id}"]\n---\n\n'
        f"# Endorse: {candidate_id}\n\n## Why I Endorse\nkosullar saglandi.\n",
        encoding="utf-8",
    )
    return p


def _write_kill_probe(adv_dir: Path, candidate_id: str = CAND, *, passed: bool = True) -> Path:
    adv_dir.mkdir(parents=True, exist_ok=True)
    verdict = "True" if passed else "False"
    p = adv_dir / f"adversary_engineer-20260710T000000-probe-{'pass' if passed else 'fail'}.md"
    p.write_text(
        "---\ndoc_type: endorse\nagent_id: adversary_engineer\n"
        f'tags: ["kill_probe", "adversarial", "{"pass" if passed else "fail"}"]\n---\n\n'
        f"# Kill Probe — {candidate_id}\n\n## Probe Result\n"
        f"- Passed: **{verdict}**\n- Fails: []\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# 1. Gate saf fonksiyon
# ---------------------------------------------------------------------------
def test_gate_blocks_without_any_evidence(tmp_path: Path):
    g = promotion_enforcement_gate(
        CAND,
        risk_decisions_dir=tmp_path / "memory" / "risk_officer" / "decisions",
        adversary_reports_dir=tmp_path / "reports" / "adversary",
    )
    assert g["allowed"] is False
    assert len(g["missing"]) == 2  # endorse + kill-probe ikisi de eksik
    assert g["risk_endorsement"] is None and g["kill_probe_pass"] is None


def test_gate_blocks_with_endorse_but_no_kill_probe(tmp_path: Path):
    dec = tmp_path / "decisions"
    _write_endorse(dec)
    g = promotion_enforcement_gate(
        CAND, risk_decisions_dir=dec, adversary_reports_dir=tmp_path / "adversary"
    )
    assert g["allowed"] is False
    assert g["risk_endorsement"] is not None
    assert g["kill_probe_pass"] is None
    assert len(g["missing"]) == 1


def test_gate_blocks_when_kill_probe_failed(tmp_path: Path):
    dec, adv = tmp_path / "decisions", tmp_path / "adversary"
    _write_endorse(dec)
    _write_kill_probe(adv, passed=False)  # "Passed: **False**" izi kanıt DEĞİL
    g = promotion_enforcement_gate(CAND, risk_decisions_dir=dec, adversary_reports_dir=adv)
    assert g["allowed"] is False
    assert g["kill_probe_pass"] is None


def test_gate_passes_with_endorse_and_kill_probe_pass(tmp_path: Path):
    dec, adv = tmp_path / "decisions", tmp_path / "adversary"
    _write_endorse(dec)
    _write_kill_probe(adv, passed=True)
    g = promotion_enforcement_gate(CAND, risk_decisions_dir=dec, adversary_reports_dir=adv)
    assert g["allowed"] is True
    assert g["missing"] == []
    assert g["risk_endorsement"] is not None and g["kill_probe_pass"] is not None


def test_gate_ignores_endorse_for_other_candidate(tmp_path: Path):
    dec, adv = tmp_path / "decisions", tmp_path / "adversary"
    _write_endorse(dec, candidate_id="baska-bir-aday-2026")
    _write_kill_probe(adv, candidate_id="baska-bir-aday-2026")
    g = promotion_enforcement_gate(CAND, risk_decisions_dir=dec, adversary_reports_dir=adv)
    assert g["allowed"] is False
    assert len(g["missing"]) == 2


def test_gate_fail_closed_on_empty_candidate_id(tmp_path: Path):
    g = promotion_enforcement_gate(
        "", risk_decisions_dir=tmp_path, adversary_reports_dir=tmp_path
    )
    assert g["allowed"] is False and g["missing"]


# ---------------------------------------------------------------------------
# 2. weekly_tournament uçtan uca (DRY_RUN)
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ROOT_DIR'i tmp'ye al — audit/adversary test deseni."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "lab_scientist.md").write_text("# stub\n", encoding="utf-8")
    memdir = tmp_path / "memory"
    (memdir / "lab_scientist").mkdir(parents=True)
    (memdir / "shared" / "facts").mkdir(parents=True)
    (memdir / "shared" / "lessons").mkdir(parents=True)
    (memdir / "protocol").mkdir(parents=True)
    (tmp_path / "reports" / "lab").mkdir(parents=True)
    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    from price_action import settings as _s

    _s.get_settings.cache_clear()
    monkeypatch.setattr(_s, "ROOT_DIR", tmp_path)
    return tmp_path


def _make_lab(root: Path) -> LabScientistAgent:
    from price_action.memory import MemoryStore

    return LabScientistAgent(memory_store=MemoryStore(base_dir=root / "memory"))


def _statistically_promotable() -> tuple[dict, list[dict]]:
    """İstatistiksel gate'leri (effect≥0.15, dsr_p<0.05, maxdd) KESIN geçen aday.

    60 obs, mean 0.5 / std ~0.1 → sr_obs≈5, z>>0 → dsr_p≈0;
    effect=(2.0-1.0)/1.0=1.0; maxdd 0.10 ≤ 0.17+0.05.
    """
    champion = {
        "id": "champ-live",
        "oos_returns": [],
        "oos_sharpe": 1.0,
        "oos_maxdd": 0.17,
        "n_trials": 5,
    }
    challenger = {
        "id": CAND,
        "oos_returns": [0.4, 0.6] * 30,
        "oos_sharpe": 2.0,
        "oos_maxdd": 0.10,
        "n_trials": 1,
    }
    return champion, [challenger]


def test_tournament_blocks_promote_without_endorsement(isolated_env: Path):
    """0-endorse ortamında istatistiksel kazanan BLOKLANIR (canlı etki yok)."""
    champion, challengers = _statistically_promotable()
    lab = _make_lab(isolated_env)
    path = asyncio.run(lab.weekly_tournament(champion=champion, challengers=challengers))
    text = Path(path).read_text(encoding="utf-8")
    assert "blocked_pending_endorsement" in text
    # Blok = terfi DEĞİL: audit_ops churn grep'i ('promote_candidate') tetiklenmemeli
    assert "promote_candidate" not in text


def test_tournament_promotes_with_endorsement_and_kill_probe(isolated_env: Path):
    champion, challengers = _statistically_promotable()
    _write_endorse(isolated_env / "memory" / "risk_officer" / "decisions")
    _write_kill_probe(isolated_env / "reports" / "adversary")
    lab = _make_lab(isolated_env)
    path = asyncio.run(lab.weekly_tournament(champion=champion, challengers=challengers))
    text = Path(path).read_text(encoding="utf-8")
    assert "promote_candidate" in text
    assert "blocked_pending_endorsement" not in text


def test_tournament_reject_path_untouched(isolated_env: Path):
    """İstatistiksel kaybeden: gate HİÇ değerlendirilmez, karar 'reject' kalır."""
    champion, _ = _statistically_promotable()
    loser = {
        "id": "loser-flat",
        "oos_returns": [0.0] * 40,
        "oos_sharpe": 0.1,
        "oos_maxdd": 0.5,
        "n_trials": 3,
    }
    lab = _make_lab(isolated_env)
    path = asyncio.run(lab.weekly_tournament(champion=champion, challengers=[loser]))
    text = Path(path).read_text(encoding="utf-8")
    assert "'decision': 'reject'" in text
    assert "enforcement_gate" not in text  # gate yalnız istatistik-geçenlere koşar
