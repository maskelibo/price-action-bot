"""LLM agent base testleri — system prompt, dry-run, telemetry, retry.

Gerçek LLM çağrısı YOK — `PA_LLM_DRY_RUN=true` veya client mock.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from price_action.agents.base import LLMAgentBase, LLMError, LLMResponse
from price_action.memory import MemoryStore


class _DummyAgent(LLMAgentBase):
    name = "ceo"
    default_model = "claude-test-model"
    allowed_tools = ("read_file", "write_report")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """İzole memory + agent rules dosyası kur."""
    rules_dir = tmp_path / "agents"
    rules_dir.mkdir()
    rules_file = rules_dir / "ceo.md"
    rules_file.write_text("# CEO Rules\n- Be cautious.\n", encoding="utf-8")

    memdir = tmp_path / "memory"
    (memdir / "ceo").mkdir(parents=True)
    (memdir / "shared" / "facts").mkdir(parents=True)
    (memdir / "shared" / "lessons").mkdir(parents=True)
    (memdir / "ceo" / "identity.md").write_text("# Id\nidentity-text\n", encoding="utf-8")
    (memdir / "ceo" / "know_how.md").write_text("# KH\nplaybook-text\n", encoding="utf-8")
    (memdir / "ceo" / "learning.md").write_text("# L\n", encoding="utf-8")

    monkeypatch.setenv("PA_LLM_DRY_RUN", "true")
    # settings.agents_rules_dir & memory_dir override
    from price_action import settings as _settings_mod

    _settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(_settings_mod, "ROOT_DIR", tmp_path)
    # memory_dir/agents_rules_dir property'leri ROOT_DIR temelli olduğundan
    # tmp_path'a tekabül eder.
    return {"rules_dir": rules_dir, "memdir": memdir}


def test_system_prompt_combines_rules_and_memory(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    sp = agent._load_system_prompt()
    assert "CEO Rules" in sp
    assert "Be cautious" in sp
    assert "identity-text" in sp
    assert "playbook-text" in sp
    assert "ALLOWED TOOLS" in sp
    assert "read_file" in sp


def test_dry_run_returns_mock_response(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    text = asyncio.run(agent.run("Bugünkü brief lütfen."))
    assert "[DRY RUN" in text
    assert "ceo/claude-test-model" in text


def test_dry_run_records_episodic(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    asyncio.run(agent.run("merhaba"))
    # episodic.jsonl dolmuş olmalı
    log_file = env["memdir"] / "ceo" / "runtime" / "episodic.jsonl"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "llm_call" in content


def test_run_full_returns_response(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    resp = asyncio.run(agent.run_full("test"))
    assert isinstance(resp, LLMResponse)
    assert resp.model == "claude-test-model"
    assert resp.stop_reason == "dry_run"
    assert resp.input_tokens > 0
    assert resp.output_tokens > 0


def test_context_files_appended_to_user_message(env: dict, tmp_path: Path) -> None:
    extra = tmp_path / "ctx.md"
    extra.write_text("--SPECIFIC-CONTEXT--", encoding="utf-8")
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    msg = agent._build_user_message("user prompt", [extra])
    assert "user prompt" in msg
    assert "--SPECIFIC-CONTEXT--" in msg
    assert "ctx.md" in msg


def test_consolidate_weekly_writes_back_to_memory(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    # Episodic'e tekrar eden body ekle
    for _ in range(3):
        agent.record_episodic("recurring identical body event", tags=["t"])
    agent.record_episodic("singleton", tags=["s"])
    report = agent.consolidate_weekly(last_n_days=7)
    assert report["total"] == 4
    # Learning'e tekrar dersinin yansıdığını gör
    learning = store.read_learning("ceo")
    assert "Tekrar eden episode" in learning
    # Know-how'a haftalık tag özet notu yazılmış olmalı
    kh = store.read_know_how("ceo")
    assert "Haftalık episodic tag" in kh


def test_retry_on_llm_error(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM hatası: 3 deneme, sonra exception fırlar."""
    monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)

    call_counts = {"n": 0}

    def fake_call(*_a, **_kw):
        call_counts["n"] += 1
        raise LLMError("simulated failure")

    # Client'ı hazırla — anthropic kind seçilsin diye kobay
    agent._client = MagicMock()
    agent._client_kind = "anthropic"
    monkeypatch.setattr(agent, "_call_anthropic", fake_call)

    with pytest.raises(LLMError):
        asyncio.run(agent.run("test"))
    # tenacity stop_after_attempt(3)
    assert call_counts["n"] == 3


def test_append_learning_via_agent_creates_entry(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    agent.append_learning("Yeni ders satırı", slug="new-lesson", tags=["x"])
    txt = store.read_learning("ceo")
    assert "new-lesson" in txt
    assert "Yeni ders satırı" in txt


def test_write_decision_via_agent(env: dict) -> None:
    store = MemoryStore(base_dir=env["memdir"])
    agent = _DummyAgent(memory_store=store)
    path = agent.write_decision(
        {"title": "Test ADR", "decision": "do it"},
        slug="test-adr",
    )
    assert path.exists()
    assert "Test ADR" in path.read_text(encoding="utf-8")
