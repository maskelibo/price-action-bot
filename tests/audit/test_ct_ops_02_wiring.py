"""T5-02 + T5-01 — CT-OPS-02 wiring + ghost-owner kapanışı (2026-07-10).

T5-02: ct_ops_02_silent_cron dedektörü tanımlı+unit-testliydi ama controls()'a
HİÇ kayıtlı değildi → sessiz-cron kontrolünün kendisi sessizdi (ölü kod).
Fix: run_ct_ops_02_silent_cron (dosya-mtime koşu-izi, SKIP-on-missing) + kayıt.

T5-01: CT-OPS-03/05/06 owner=execution_chief idi — çalışabilir Python agent
sınıfı YOK (yalnız persona/.md) → bulgu remediation dead-end. Fix: ops_engineer.
"""

from __future__ import annotations

import os
import time

from price_action.agents.audit_base import SKIP
from price_action.agents.audit_ops import _LOG_PATTERN_SPECS, AuditOpsAgent


def _bare_agent() -> AuditOpsAgent:
    """__init__ bypass — controls()/runner LLM+memory gerektirmez."""
    return AuditOpsAgent.__new__(AuditOpsAgent)


# ---------------------------------------------------------------------------
# T5-02: kayıt + runner davranışı
# ---------------------------------------------------------------------------


def test_ct_ops_02_registered_in_controls():
    """Wiring kanıtı: CT-OPS-02 artık controls()'ta (eski kod: yoktu → hiç koşmazdı)."""
    ctrls = AuditOpsAgent.controls(_bare_agent())
    assert "CT-OPS-02" in ctrls
    assert callable(ctrls["CT-OPS-02"])


def test_runner_fresh_evidence_no_finding(tmp_path, monkeypatch):
    """Tüm koşu-izleri taze → bulgu YOK (temiz)."""
    agent = _bare_agent()
    monkeypatch.setattr(agent, "_repo_root", lambda: tmp_path, raising=False)
    for _, rel, _max_h in agent._CT_OPS_02_RUN_EVIDENCE:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")  # şimdi-mtime = taze
    assert agent.run_ct_ops_02_silent_cron() is None


def test_runner_stale_evidence_emits_finding(tmp_path, monkeypatch):
    """Bir job'un koşu-izi eşiğin ötesinde bayat → CT-OPS-02 bulgusu."""
    agent = _bare_agent()
    monkeypatch.setattr(agent, "_repo_root", lambda: tmp_path, raising=False)
    job, rel, max_h = agent._CT_OPS_02_RUN_EVIDENCE[0]
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    stale_ts = time.time() - (max_h + 2.0) * 3600.0
    os.utime(p, (stale_ts, stale_ts))
    f = agent.run_ct_ops_02_silent_cron()
    assert f is not None and f is not SKIP
    assert f.control_id == "CT-OPS-02"
    assert job in f.evidence["stale_jobs"]


def test_runner_no_evidence_files_skips(tmp_path, monkeypatch):
    """Hiç koşu-izi dosyası yok → SKIP (veri yetersiz, asla false-fire yok)."""
    agent = _bare_agent()
    monkeypatch.setattr(agent, "_repo_root", lambda: tmp_path, raising=False)
    assert agent.run_ct_ops_02_silent_cron() is SKIP


def test_runner_missing_file_only_skipped_not_stale(tmp_path, monkeypatch):
    """Eksik dosya 'hiç koşmamış' bulgusu ÜRETMEZ (rotasyon false-pozitifi önlenir);
    mevcut+taze dosyalar temiz kalır."""
    agent = _bare_agent()
    monkeypatch.setattr(agent, "_repo_root", lambda: tmp_path, raising=False)
    # yalnız İLK job'un dosyasını yarat (taze), gerisi eksik
    _, rel, _ = agent._CT_OPS_02_RUN_EVIDENCE[0]
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    assert agent.run_ct_ops_02_silent_cron() is None  # eksikler atlandı, taze temiz


# ---------------------------------------------------------------------------
# T5-01: ghost-owner kalıcı kalkanı
# ---------------------------------------------------------------------------


def test_log_pattern_owners_are_runnable_agents():
    """CT-OPS-03..06 owner'ları GERÇEK (çalışabilir) ajanlara route eder.
    execution_chief = yalnız persona (.md), Python agent sınıfı yok → yasak."""
    owners = {spec["owner"] for spec in _LOG_PATTERN_SPECS}
    assert "execution_chief" not in owners  # ghost-owner regresyonu yasak
    assert owners <= {"ops_engineer", "data_engineer"}  # bilinen-gerçek küme
