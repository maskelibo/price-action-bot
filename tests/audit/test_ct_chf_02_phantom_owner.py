"""T5-01 — CT-CHF-02 phantom-owner kontrolü (2026-07-10).

audit_universe.yaml'daki owner_agent'lar ÇALIŞABILIR ajan kümesinde
(src/price_action/agents/*.py gerçek Agent sınıfları) olmalı. Persona-only
owner (örn. execution_chief, portfolio_manager) = remediation dead-end:
bulgu route edilir ama koşacak Python sınıfı yok → SLA sessizce dolar.

Coverage:
1. Phantom içeren sahte universe → TEK toplu Finding (düşük-gürültü)
2. Temiz universe → None
3. owner_agent hiç yok → phantom SAYILMAZ (CT-CHF-01'in işi, çift bulgu yok)
4. controls() kaydı (wiring kanıtı — kayıtsız dedektör ölü koddur, T5-02 dersi)
5. Runner: universe okunamaz/boş → SKIP (yanlışlıkla auto-close yok)
6. Kaynak-pin: RUNNABLE_AGENT_NAMES kod tabanından türetilen kümeyle birebir
   (yeni ajan eklenince/persona silinince bu test kırmızı → frozenset güncelle)
"""

from __future__ import annotations

import re
from pathlib import Path

from price_action.agents.audit_base import SKIP
from price_action.agents.audit_chief import (
    RUNNABLE_AGENT_NAMES,
    AuditChiefAgent,
    phantom_owner,
)


def _bare_agent() -> AuditChiefAgent:
    """__init__ bypass — controls()/runner LLM+memory gerektirmez."""
    return AuditChiefAgent.__new__(AuditChiefAgent)


# ---------------------------------------------------------------------------
# 1. Phantom universe → tek toplu bulgu
# ---------------------------------------------------------------------------
def test_phantom_owner_emits_single_aggregated_finding():
    universe = {
        "exec.order_lifecycle": {"owner_agent": "execution_chief", "auditor": "audit_execution"},
        "exec.reconcile": {"owner_agent": "execution_chief", "auditor": "audit_execution"},
        "risk.allocator": {"owner_agent": "portfolio_manager", "auditor": "audit_risk"},
        "data.ingest": {"owner_agent": "data_engineer", "auditor": "audit_data"},
    }
    f = phantom_owner(universe)
    assert f is not None
    assert f.control_id == "CT-CHF-02"
    assert f.severity == "med"
    assert f.owner == "ops_engineer"
    # Toplu bulgu: iki phantom owner, üç etkilenen süreç
    assert f.evidence["n_phantom_owners"] == 2
    assert f.evidence["n_affected_processes"] == 3
    assert "execution_chief" in f.evidence["phantom_owners"]
    assert "portfolio_manager" in f.evidence["phantom_owners"]
    assert "exec.reconcile" in f.evidence["phantom_owners"]
    # Temiz owner bulguya sızmamalı
    assert "data_engineer" not in f.evidence["phantom_owners"]


def test_clean_universe_no_finding():
    universe = {
        "data.ingest": {"owner_agent": "data_engineer", "auditor": "audit_data"},
        "risk.sizing": {"owner_agent": "risk_officer", "auditor": "audit_risk"},
        "research.backtest": {"owner_agent": "lab_scientist", "auditor": "audit_research"},
    }
    assert phantom_owner(universe) is None


def test_missing_owner_is_not_phantom():
    # owner_agent YOK → kapsama açığı (CT-CHF-01) — phantom kontrolü karışmaz.
    universe = {
        "orphan.process": {"owner_agent": None, "auditor": "audit_ops"},
        "orphan.process2": {"auditor": "audit_ops"},
    }
    assert phantom_owner(universe) is None


def test_empty_universe_no_finding():
    assert phantom_owner({}) is None
    assert phantom_owner(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. Wiring — controls() kaydı
# ---------------------------------------------------------------------------
def test_ct_chf_02_registered_in_controls():
    ctrls = AuditChiefAgent.controls(_bare_agent())
    assert "CT-CHF-02" in ctrls
    assert callable(ctrls["CT-CHF-02"])


# ---------------------------------------------------------------------------
# 5. Runner davranışı — SKIP vs Finding vs None
# ---------------------------------------------------------------------------
def test_runner_skip_when_universe_unreadable(monkeypatch):
    agent = _bare_agent()
    monkeypatch.setattr(agent, "_load_universe", lambda: {}, raising=False)
    assert agent.run_ct_chf_02_phantom_owner() is SKIP


def test_runner_finding_on_phantom_universe(monkeypatch):
    agent = _bare_agent()
    monkeypatch.setattr(
        agent,
        "_load_universe",
        lambda: {"x.proc": {"owner_agent": "ghost_agent", "auditor": "audit_ops"}},
        raising=False,
    )
    f = agent.run_ct_chf_02_phantom_owner()
    assert f is not None and f is not SKIP
    assert f.control_id == "CT-CHF-02"
    assert "ghost_agent" in f.evidence["phantom_owners"]


def test_runner_none_on_clean_universe(monkeypatch):
    agent = _bare_agent()
    monkeypatch.setattr(
        agent,
        "_load_universe",
        lambda: {"x.proc": {"owner_agent": "ops_engineer", "auditor": "audit_ops"}},
        raising=False,
    )
    assert agent.run_ct_chf_02_phantom_owner() is None


# ---------------------------------------------------------------------------
# 6. Kaynak-pin — frozenset kod tabanıyla birebir
# ---------------------------------------------------------------------------
def test_runnable_agent_names_pinned_to_source():
    """RUNNABLE_AGENT_NAMES ile src/price_action/agents/*.py'daki gerçek
    ``name: ClassVar[str] = "..."`` kümesi birebir aynı olmalı.

    Kırmızıysa: yeni Agent sınıfı eklendi/silindi → audit_chief.py'daki
    frozenset'i güncelle (soyut tabanlar 'agent' ve 'audit_base' hariç).
    """
    import price_action.agents.audit_chief as chief_mod

    src_dir = Path(chief_mod.__file__).parent
    pattern = re.compile(r'name:\s*ClassVar\[str\]\s*=\s*"([^"]+)"')
    derived: set[str] = set()
    for py in src_dir.glob("*.py"):
        derived.update(pattern.findall(py.read_text(encoding="utf-8")))
    derived -= {"agent", "audit_base"}  # soyut tabanlar — çalıştırılabilir ajan değil

    assert derived == set(RUNNABLE_AGENT_NAMES), (
        "RUNNABLE_AGENT_NAMES kod tabanından sapmış. "
        f"Kodda olup frozenset'te olmayan: {sorted(derived - RUNNABLE_AGENT_NAMES)}; "
        f"frozenset'te olup kodda olmayan: {sorted(RUNNABLE_AGENT_NAMES - derived)}"
    )
