"""İç Denetim Departmanı — kabul testleri (Faz 1).

Her test, bu seansta ELLE bulunan bir bug'ı yeniden enjekte eder ve denetçinin
finding ürettiğini iddia eder. Deterministik çekirdek (LLM'siz) → `PA_LLM_DRY_RUN`.

Coverage:
1. CT-EXE-01 journal↔borsa drift (XLM phantom + NEAR qty drift)
2. CT-RSK-01 MaxDD sıfır-baz şişmesi (%43 bug)
3. CT-DAT-01 ingest↔trading evren uyumsuzluğu (3538-vs-14 + 14-vs-19)
4. CT-DAT-04 DuckDB kilit-çakışması (öngörü — ingest15m exit-1)
5. CT-CHF-01 kapsama-boşluğu haritası (uncovered process)
6. Finding lifecycle: emit→OPEN, verify pass→CLOSED, recurrence→severity escalate
7. Independence invariant: denetçi read-only (Write/Edit yok)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from price_action.agents.audit_chief import coverage_gap
from price_action.agents.audit_data import ct_dat_01_universe, ct_dat_04_duckdb_lock
from price_action.agents.audit_execution import ct_exe_01_journal_drift, ct_exe_02_pnl_recon
from price_action.agents.audit_ops import ct_ops_01_mute_drift, ct_ops_02_silent_cron
from price_action.agents.audit_research import ct_res_01_sharpe
from price_action.agents.audit_risk import ct_rsk_01_maxdd_base


# ---------------------------------------------------------------------------
# 1. CT-EXE-01 — journal↔borsa drift
# ---------------------------------------------------------------------------
def test_audit_execution_catches_journal_drift():
    # Bu seansın gerçek durumu: journal XLM açık sanıyor (phantom) + NEAR 291 vs 219
    f = ct_exe_01_journal_drift(
        journal_open={"XLM/USDT": 1448.0, "NEAR/USDT": 291.0, "AVAX/USDT": 84.0},
        exchange_open={"NEAR/USDT": 219.0, "AVAX/USDT": 84.0},
    )
    assert f is not None
    assert f.control_id == "CT-EXE-01"
    assert f.severity == "high"
    assert f.owner == "execution_chief"


def test_audit_execution_catches_pnl_inflation():
    # Bu seansın gerçeği: journal +57.73 vs borsa -11.58; DOT işaret-ters (+28.73 vs -3.52)
    journal = {"DOT/USDT": 28.73, "AVAX/USDT": 15.25, "ADA/USDT": 17.14,
               "XLM/USDT": -23.24, "XRP/USDT": 3.93}
    exchange = {"DOT/USDT": -3.52, "AVAX/USDT": -1.92, "ADA/USDT": -0.31,
                "XLM/USDT": -23.24, "XRP/USDT": 0.88}
    f = ct_exe_02_pnl_recon(journal, exchange)
    assert f is not None
    assert f.control_id == "CT-EXE-02"
    assert f.severity == "critical"   # toplam fark > 5×tol → critical
    assert "DOT" in f.evidence["offenders"]
    assert "İŞARET TERS" in f.evidence["offenders"]


def test_audit_execution_pnl_match_no_finding():
    # journal = borsa → bulgu yok
    j = {"BTC/USDT": 10.0, "ETH/USDT": -5.0}
    e = {"BTC/USDT": 10.2, "ETH/USDT": -5.1}
    assert ct_exe_02_pnl_recon(j, e) is None


def test_audit_execution_clean_no_finding():
    f = ct_exe_01_journal_drift(
        journal_open={"AVAX/USDT": 84.0, "NEAR/USDT": 219.0},
        exchange_open={"AVAX/USDT": 84.0, "NEAR/USDT": 219.0},
    )
    assert f is None


# ---------------------------------------------------------------------------
# 2. CT-RSK-01 — MaxDD sıfır-baz şişmesi
# ---------------------------------------------------------------------------
def test_audit_risk_catches_maxdd_zero_base():
    # +100 yapıp 43 geri ver: sıfır-baz DD=%43, hesap(10000)-baz DD=%0.43
    f = ct_rsk_01_maxdd_base([100.0, -43.0, 20.0], account_equity=10000.0, reported_dd_pct=0.4339)
    assert f is not None
    assert f.control_id == "CT-RSK-01"
    assert f.severity == "high"
    assert f.evidence["correct_dd_pct"] < 0.01  # gerçek DD küçük
    assert f.evidence["zero_base_dd_pct"] > 0.4  # şişmiş baz


def test_audit_risk_correct_base_no_finding():
    # Sistem doğru baz raporluyorsa (account-equity) → bulgu yok
    f = ct_rsk_01_maxdd_base([100.0, -43.0, 20.0], account_equity=10000.0, reported_dd_pct=0.0043)
    assert f is None


# ---------------------------------------------------------------------------
# 3. CT-DAT-01 — evren uyumsuzluğu (iki yön)
# ---------------------------------------------------------------------------
def test_audit_data_catches_universe_oversized():
    f = ct_dat_01_universe(ingest_count=3538, trading_count=14)
    assert f is not None and f.control_id == "CT-DAT-01"
    assert f.severity == "med"  # israf


def test_audit_data_catches_universe_missing():
    # Trading 19, ingest 14 → 5 sembol eksik (bu seansta yaşandı)
    f = ct_dat_01_universe(ingest_count=14, trading_count=19)
    assert f is not None and f.severity == "high"  # eksik veri daha kritik


def test_audit_data_universe_consistent_no_finding():
    f = ct_dat_01_universe(ingest_count=19, trading_count=19)
    assert f is None


# ---------------------------------------------------------------------------
# 4. CT-DAT-04 — DuckDB kilit (öngörü)
# ---------------------------------------------------------------------------
def test_audit_data_catches_duckdb_lock():
    log = "blah\nIO Error: Conflicting lock is held in PID 95676\nmore\nConflicting lock\n"
    f = ct_dat_04_duckdb_lock(log, max_allowed=0)
    assert f is not None and f.control_id == "CT-DAT-04"


def test_audit_data_no_lock_no_finding():
    f = ct_dat_04_duckdb_lock("clean log no errors", max_allowed=0)
    assert f is None


def test_audit_data_catches_duckdb_invalidation_critical():
    """REGRESYON — 2026-06-01 saatlik ingest invalidation'ı (CT-DAT-04 kör noktası).

    Eski dedektör yalnız lock string'i arıyordu; bu gerçek hata satırını (allocator
    bozulması / handle invalidation) KAÇIRIYORDU. Artık FATAL sınıfı → critical.
    """
    real_err = (
        "scheduler.ingest_skip: FATAL Error: Failed: database has been invalidated "
        "because of a previous fatal error. The database must be restarted prior to "
        'being used again.\nOriginal error: "Invalid bitmask for FixedSizeAllocator"'
    )
    f = ct_dat_04_duckdb_lock(real_err, max_allowed=0)
    assert f is not None and f.control_id == "CT-DAT-04"
    assert f.severity == "critical", "invalidation = veri kaybı/restart → critical olmalı"


# ---------------------------------------------------------------------------
# 5. CT-CHF-01 — kapsama-boşluğu
# ---------------------------------------------------------------------------
def test_chief_coverage_gap_map():
    universe = {
        "data.ingest": {
            "owner_agent": "data_engineer",
            "auditor": "audit_data",
            "controls": ["CT-DAT-01"],
        },  # tam → bulgu yok
        "research.backtest": {
            "owner_agent": "lab_scientist",
            "auditor": None,
            "controls": [],
        },  # denetçi+kontrol yok
    }
    findings = coverage_gap(universe)
    assert len(findings) == 1
    assert findings[0].control_id == "CT-CHF-01"
    assert "research.backtest" in findings[0].title


def test_chief_empty_controls_is_not_a_gap():
    # Faz 3: sahip+denetçi var ama controls boş → bulgu DEĞİL (backlog metriği)
    universe = {
        "data.snapshot": {"owner_agent": "data_engineer", "auditor": "audit_data",
                          "controls": []},
    }
    assert coverage_gap(universe) == []


# ---------------------------------------------------------------------------
# 5b. CT-RES-01 — Sharpe annualization şişmesi (research)
# ---------------------------------------------------------------------------
def test_audit_research_catches_sharpe_inflation():
    f = ct_res_01_sharpe(17.3, mean_r=0.5, std_r=1.0, n_trades=6814)
    assert f is not None and f.control_id == "CT-RES-01" and f.severity == "high"
    assert f.owner == "lab_scientist"


def test_audit_research_plausible_sharpe_no_finding():
    f = ct_res_01_sharpe(3.6)  # takvim-günü bazlı makul
    assert f is None


# ---------------------------------------------------------------------------
# 5c. CT-OPS-01 / CT-OPS-02 — mute drift + silent cron (ops)
# ---------------------------------------------------------------------------
def test_audit_ops_catches_mute_drift():
    f = ct_ops_01_mute_drift(
        ["dms_stale_", "regime_cache_stale_warn"], ["scheduler_stuck_doc"], run_mode="paper"
    )
    assert f is not None and f.control_id == "CT-OPS-01"


def test_audit_ops_live_mute_is_critical():
    f = ct_ops_01_mute_drift(["dms_stale_"], [], run_mode="live")
    assert f is not None and f.severity == "critical"


def test_audit_ops_no_mute_no_finding():
    # Bu seansta unmute edildi → boş listeler → temiz
    f = ct_ops_01_mute_drift([], [], run_mode="paper")
    assert f is None


def test_audit_ops_catches_silent_cron():
    f = ct_ops_02_silent_cron(
        job_ages_hours={"ingest_data": 30.0, "audit_execution": 2.0},
        expected_max_age_hours={"ingest_data": 2.0, "audit_execution": 26.0},
    )
    assert f is not None and f.control_id == "CT-OPS-02"
    assert "ingest_data" in f.evidence["stale_jobs"]


# ---------------------------------------------------------------------------
# 6. Finding lifecycle (emit → OPEN → verify → CLOSED/recurrence)
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ROOT_DIR'i tmp'ye al → register + reports izole (adversary testi deseni)."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "audit_execution.md").write_text("# stub\n", encoding="utf-8")
    memdir = tmp_path / "memory"
    (memdir / "audit").mkdir(parents=True)
    (memdir / "shared" / "facts").mkdir(parents=True)
    (memdir / "shared" / "lessons").mkdir(parents=True)
    (memdir / "protocol").mkdir(parents=True)
    (tmp_path / "reports" / "audit").mkdir(parents=True)
    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    from price_action import settings as _s

    _s.get_settings.cache_clear()
    monkeypatch.setattr(_s, "ROOT_DIR", tmp_path)
    return tmp_path


def _make_exec_agent(memdir_root: Path):
    from price_action.agents.audit_execution import AuditExecutionAgent
    from price_action.memory import MemoryStore

    return AuditExecutionAgent(memory_store=MemoryStore(base_dir=memdir_root / "memory"))


def test_finding_lifecycle_recurrence(isolated_env):
    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)

    f = ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {})  # phantom
    path1 = agent.emit_finding(f)
    assert path1.exists()
    latest = agent._latest_state()
    assert len(latest) == 1
    fid = next(iter(latest))
    assert latest[fid]["status"] == "OPEN"
    assert latest[fid]["recurrence_count"] == 0

    # remediation doğrula → CLOSED
    agent.verify_remediation(fid, passed=True, remediation_doc="fix-doc")
    assert agent._latest_state()[fid]["status"] == "CLOSED"

    # AYNI control tekrar açılırsa → recurrence + severity escalate
    f2 = ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {})
    base_sev = f2.severity  # "high"
    agent.emit_finding(f2)
    # yeni bulgu recurrence_count>0 ve severity escalate (high→critical)
    states = list(agent._latest_state().values())
    new_open = [s for s in states if s["status"] == "OPEN"]
    assert len(new_open) == 1
    assert new_open[0]["recurrence_count"] >= 1
    assert new_open[0]["severity"] == "critical"  # high→critical


# ---------------------------------------------------------------------------
# 6b. AUTO-VERIFY — run_controls: problem→emit, temiz→CLOSE, SKIP→dokunma
# ---------------------------------------------------------------------------
def test_auto_verify_closes_resolved_finding(isolated_env):
    import asyncio

    from price_action.agents.audit_base import SKIP
    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)
    state = {"mode": "problem"}

    def fake_runner():
        if state["mode"] == "problem":
            return ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {})  # phantom
        if state["mode"] == "clean":
            return None
        return SKIP

    agent.controls = lambda: {"CT-EXE-01": fake_runner}  # type: ignore

    # 1) problem → emit (OPEN)
    r1 = asyncio.run(agent.run_controls())
    assert len(r1["emitted"]) == 1 and not r1["closed"]
    fid = next(iter(agent._latest_state()))
    assert agent._latest_state()[fid]["status"] == "OPEN"

    # 2) tekrar problem → dedup (yeni emit YOK, hâlâ açık)
    r2 = asyncio.run(agent.run_controls())
    assert not r2["emitted"] and not r2["closed"]

    # 3) SKIP → dokunma (açık kalır, kapanmaz)
    state["mode"] = "skip"
    r3 = asyncio.run(agent.run_controls())
    assert not r3["closed"]
    assert agent._latest_state()[fid]["status"] == "OPEN"

    # 4) temiz → AUTO-VERIFY → CLOSED
    state["mode"] = "clean"
    r4 = asyncio.run(agent.run_controls())
    assert fid in r4["closed"]
    assert agent._latest_state()[fid]["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# 6c. SLA + owner-close + audit-verify döngüsü (kullanıcı şartı 2026-06-02)
# ---------------------------------------------------------------------------
def test_finding_default_sla_is_one_day(isolated_env):
    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)
    agent.emit_finding(ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {}))
    row = next(iter(agent._latest_state().values()))
    from datetime import datetime

    opened = datetime.strptime(row["opened_at"], "%Y-%m-%dT%H:%M:%SZ")
    due = datetime.strptime(row["due_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert (due - opened).days == 1, "SLA 1 gün olmalı"


def test_owner_remediation_then_audit_verify_closes(isolated_env):
    """Owner 'kapatıldı raporu' verir → denetçi testi yeniden koşar → temizse CLOSED."""
    import asyncio

    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)
    mode = {"v": "problem"}
    agent.controls = lambda: {  # type: ignore
        "CT-EXE-01": lambda: (
            ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {}) if mode["v"] == "problem" else None
        )
    }
    asyncio.run(agent.run_controls())  # OPEN
    fid = next(iter(agent._latest_state()))

    # owner closure raporu → REMEDIATION_FILED (kapanmaz, denetçi doğrulamadı)
    agent.record_remediation(fid, remediation_doc="reports/exec-fix.md", by="execution_chief")
    assert agent._latest_state()[fid]["status"] == "REMEDIATION_FILED"

    # denetçi yeniden koşar, artık TEMİZ → CLOSED (owner raporu referanslı)
    mode["v"] = "clean"
    r = asyncio.run(agent.run_controls())
    assert fid in r["closed"]
    closed = agent._latest_state()[fid]
    assert closed["status"] == "CLOSED"
    assert closed["remediation_doc"] == "reports/exec-fix.md"


def test_owner_claims_fixed_but_test_still_fails_reopens(isolated_env):
    """Owner 'düzelttim' der ama kontrol hâlâ kırıksa → REOPENED (boş iddia yakalanır)."""
    import asyncio

    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)
    agent.controls = lambda: {  # type: ignore
        "CT-EXE-01": lambda: ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {})
    }
    asyncio.run(agent.run_controls())  # OPEN
    fid = next(iter(agent._latest_state()))
    agent.record_remediation(fid, remediation_doc="reports/bogus.md", by="execution_chief")

    r = asyncio.run(agent.run_controls())  # problem hâlâ var
    assert fid in r["reopened"]
    assert agent._latest_state()[fid]["status"] == "REOPENED"


def test_escalate_overdue_is_idempotent(isolated_env):
    """1-gün SLA aşan açık bulgu → escalate (bir kez); ikinci çağrı tekrar etmez."""
    from datetime import UTC, datetime, timedelta

    from price_action.agents.audit_execution import ct_exe_01_journal_drift

    agent = _make_exec_agent(isolated_env)
    agent.emit_finding(ct_exe_01_journal_drift({"XLM/USDT": 1448.0}, {}))
    fid = next(iter(agent._latest_state()))

    # due_at'i geçmişe çek (SLA aşıldı)
    row = dict(agent._latest_state()[fid])
    row["due_at"] = (datetime.now(UTC) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    agent._append_register(row)

    first = agent.escalate_overdue()
    assert fid in first
    assert agent._latest_state()[fid]["escalated_at"] is not None

    second = agent.escalate_overdue()  # idempotent — tekrar yükseltme
    assert fid not in second


# ---------------------------------------------------------------------------
# 7. Independence invariant — denetçi READ-ONLY
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cls_name",
    [
        "AuditChiefAgent",
        "AuditExecutionAgent",
        "AuditRiskAgent",
        "AuditDataAgent",
        "AuditResearchAgent",
        "AuditOpsAgent",
    ],
)
def test_auditor_is_readonly(cls_name):
    import price_action.agents as A

    cls = getattr(A, cls_name)
    tools = " ".join(cls.allowed_tools).lower()
    assert "write" not in tools, f"{cls_name} write tool taşımamalı (independence)"
    assert "edit" not in tools, f"{cls_name} edit tool taşımamalı (independence)"
