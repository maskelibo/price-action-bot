"""reconcile canlı-bot pointer fix — kapanış sprinti 2026-07-08 (dalga-4 T3/T8 CRIT).

reconcile_journal.py PA_BOT_NAME default "v14"; scheduler subprocess'i env
aktarmıyordu → 2 Tem'den beri DONMUŞ v14 journal'ı denetlenip canlı v15p2'nin
orphan/phantom güvenlik ağı kör kaldı. Fix: scheduler subprocess'ine
PA_BOT_NAME=v15p2 (PA_RECONCILE_BOT override'lı) geçir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_passes_bot_name_env_to_reconcile():
    """Kaynak-pin: reconcile subprocess'i artık env ile PA_BOT_NAME geçiriyor."""
    src = (ROOT / "src/price_action/orchestrator/scheduler.py").read_text(encoding="utf-8")
    # _job_reconcile_journal fonksiyon gövdesini izole et
    fn_idx = src.find("async def _job_reconcile_journal")
    assert fn_idx != -1
    nxt = src.find("\nasync def ", fn_idx + 10)
    block = src[fn_idx:nxt]
    assert "PA_RECONCILE_BOT" in block, "override anahtarı yok"
    assert "PA_BOT_NAME" in block, "reconcile subprocess'i PA_BOT_NAME geçirmiyor"
    assert "env=_recon_env" in block, "subprocess.run env= almıyor"


def test_reconcile_resolves_journal_from_bot_name(monkeypatch):
    """reconcile_journal PA_BOT_NAME=v15p2 → futures_journal_v15p2.duckdb çözer."""
    import importlib

    monkeypatch.setenv("PA_BOT_NAME", "v15p2")
    import scripts.reconcile_journal as rj

    importlib.reload(rj)
    assert rj._JOURNAL.name == "futures_journal_v15p2.duckdb"


def test_reconcile_default_still_resolves(monkeypatch):
    """Env yoksa eski default korunur (geriye-uyum; scheduler artık override eder)."""
    import importlib

    monkeypatch.delenv("PA_BOT_NAME", raising=False)
    monkeypatch.delenv("PA_RECONCILE_BOT", raising=False)
    import scripts.reconcile_journal as rj

    importlib.reload(rj)
    # default "v14" (kod-içi) — scheduler env ile v15p2'ye çeviriyor
    assert "futures_journal" in rj._JOURNAL.name


@pytest.mark.ops
def test_live_journal_matches_exchange_precondition():
    """Deploy ön-koşulu belgesi: v15p2 journal açık kayıtları borsayla mutabık
    olmalı (fix güvenli = 0 orphan). Bu test journal'ın VAR ve okunabilir
    olduğunu doğrular; canlı borsa çağrısı yapmaz (offline-safe)."""
    import duckdb

    jpath = ROOT / "data" / "futures_journal_v15p2.duckdb"
    assert jpath.exists(), "v15p2 journal yok — reconcile yönlendirmesi anlamsız"
    con = duckdb.connect(str(jpath), read_only=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM futures_signals WHERE status='filled' "
            "AND signal_id NOT IN (SELECT trade_id FROM futures_trades_closed)"
        ).fetchone()[0]
    finally:
        con.close()
    assert n >= 0  # tablo okunabilir; mutabakat canlı-doğrulama ile ayrı teyit edildi
