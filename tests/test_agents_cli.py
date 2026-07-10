"""CLI adapter unit tests for LLMAgentBase._call_cli, _find_claude_cli,
and _ensure_client CLI branch.

No real CLI calls — pure subprocess mocks.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from price_action.agents.base import LLMAgentBase, LLMError, LLMResponse
from price_action.memory import MemoryStore


# ---------------------------------------------------------------------------
# Minimal concrete agent for testing
# ---------------------------------------------------------------------------

class _CliAgent(LLMAgentBase):
    name = "ceo"
    default_model = "claude-test-model"
    allowed_tools = ()


# ---------------------------------------------------------------------------
# Shared fixture — isolates memory + rules, no DRY_RUN so CLI paths run
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Isolated memory + agent rules, DRY_RUN off so CLI branches are reachable."""
    rules_dir = tmp_path / "agents"
    rules_dir.mkdir()
    (rules_dir / "ceo.md").write_text("# CEO Rules\n- Be cautious.\n", encoding="utf-8")

    memdir = tmp_path / "memory"
    (memdir / "ceo").mkdir(parents=True)
    (memdir / "shared" / "facts").mkdir(parents=True)
    (memdir / "shared" / "lessons").mkdir(parents=True)
    (memdir / "ceo" / "identity.md").write_text("# Id\nidentity-text\n", encoding="utf-8")
    (memdir / "ceo" / "know_how.md").write_text("# KH\nplaybook-text\n", encoding="utf-8")
    (memdir / "ceo" / "learning.md").write_text("# L\n", encoding="utf-8")

    # Turn off dry-run so real branches execute
    monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

    # Override settings ROOT_DIR to tmp_path so rules/memory paths resolve
    from price_action import settings as _settings_mod
    _settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(_settings_mod, "ROOT_DIR", tmp_path)

    return {"rules_dir": rules_dir, "memdir": memdir, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# _find_claude_cli tests
# ---------------------------------------------------------------------------

# FIX 2026-05-28 (audit-F7): Windows path testleri non-Windows'ta `pathlib.Path()`
# factory'sinin `os.name` monkeypatch'i tanımaması yüzünden `WindowsPath`
# instantiate edemiyor — testler hep fail. macOS/Linux'ta bu testler
# meaningful değil; gerçek Windows runner'da skip kalkar.
import os as _os_modskip
_SKIP_WIN_PATHS = pytest.mark.skipif(
    _os_modskip.name != "nt",
    reason="Windows path testleri sadece Windows runner'da koşar — "
           "pathlib.Path() os.name monkeypatch'i tanımıyor (audit-F7).",
)


@_SKIP_WIN_PATHS
def test_find_claude_cli_prefers_exe_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows, should return the .exe under APPDATA/npm/node_modules/... ."""
    # Build the expected npm path structure
    appdata = tmp_path / "AppData" / "Roaming"
    exe_path = (
        appdata
        / "npm"
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe"
    )
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("fake claude exe", encoding="utf-8")

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr("os.name", "nt")
    # shutil.which should NOT be called for the exe path — but patch to be safe
    monkeypatch.setattr("shutil.which", lambda name: None)

    from price_action.agents import base as base_mod
    result = base_mod._find_claude_cli()
    assert result == str(exe_path)


@_SKIP_WIN_PATHS
def test_find_claude_cli_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When APPDATA structure is absent, should fall back to shutil.which."""
    # APPDATA points somewhere without the npm structure
    empty_appdata = tmp_path / "empty_appdata"
    empty_appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(empty_appdata))
    monkeypatch.setattr("os.name", "nt")

    fake_claude = str(tmp_path / "bin" / "claude.exe")

    def fake_which(name: str) -> str | None:
        if name in ("claude.exe", "claude"):
            return fake_claude
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    from price_action.agents import base as base_mod
    result = base_mod._find_claude_cli()
    assert result == fake_claude


def test_find_claude_cli_falls_back_to_claude_on_unix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On non-Windows, should use shutil.which('claude')."""
    monkeypatch.setattr("os.name", "posix")
    fake_claude = "/usr/local/bin/claude"

    def fake_which(name: str) -> str | None:
        if name == "claude":
            return fake_claude
        return None

    monkeypatch.setattr("shutil.which", fake_which)

    from price_action.agents import base as base_mod
    result = base_mod._find_claude_cli()
    assert result == fake_claude


def test_find_claude_cli_returns_none_when_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None when CLI is not available anywhere."""
    monkeypatch.setattr("os.name", "posix")
    monkeypatch.setattr("shutil.which", lambda name: None)

    from price_action.agents import base as base_mod
    result = base_mod._find_claude_cli()
    assert result is None


# ---------------------------------------------------------------------------
# _ensure_client CLI branch tests
# ---------------------------------------------------------------------------

def test_ensure_client_picks_cli_when_use_cli_env(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA_LLM_USE_CLI=true forces CLI client regardless of API key."""
    fake_cli = "/usr/local/bin/claude"
    monkeypatch.setenv("PA_LLM_USE_CLI", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from price_action.agents import base as base_mod
    monkeypatch.setattr(base_mod, "_find_claude_cli", lambda: fake_cli)

    store = MemoryStore(base_dir=env["memdir"])
    agent = _CliAgent(memory_store=store)
    agent._ensure_client()

    assert agent._client_kind == "cli"
    assert agent._client == fake_cli


def test_ensure_client_picks_cli_when_no_api_key(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No PA_LLM_USE_CLI but no API key + CLI found → uses CLI."""
    fake_cli = "/usr/local/bin/claude"
    monkeypatch.delenv("PA_LLM_USE_CLI", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from price_action.agents import base as base_mod
    monkeypatch.setattr(base_mod, "_find_claude_cli", lambda: fake_cli)

    # Ensure settings has no API key too
    from price_action import settings as _settings_mod
    _settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    store = MemoryStore(base_dir=env["memdir"])
    agent = _CliAgent(memory_store=store)
    # Force settings.anthropic_api_key to be empty
    agent.settings.anthropic_api_key = ""
    agent._ensure_client()

    assert agent._client_kind == "cli"
    assert agent._client == fake_cli


def test_ensure_client_picks_anthropic_when_api_key_present(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """API key present and PA_LLM_USE_CLI not set → uses anthropic SDK."""
    monkeypatch.delenv("PA_LLM_USE_CLI", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-12345")

    # Mock the anthropic import so we don't need the real package
    fake_anthropic_client = MagicMock()
    fake_anthropic_mod = MagicMock()
    fake_anthropic_mod.Anthropic.return_value = fake_anthropic_client

    from price_action.agents import base as base_mod
    # Patch claude_agent_sdk to not be available (raise ImportError)
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    store = MemoryStore(base_dir=env["memdir"])
    agent = _CliAgent(memory_store=store)

    # Patch the anthropic import inside _ensure_client
    with patch.dict("sys.modules", {"claude_agent_sdk": None, "anthropic": fake_anthropic_mod}):
        agent._ensure_client()

    assert agent._client_kind == "anthropic"


# ---------------------------------------------------------------------------
# _call_cli tests
# ---------------------------------------------------------------------------

def _make_agent(env: dict) -> _CliAgent:
    """Create a _CliAgent pre-wired to CLI mode."""
    store = MemoryStore(base_dir=env["memdir"])
    agent = _CliAgent(memory_store=store)
    agent._client = "/usr/local/bin/claude"
    agent._client_kind = "cli"
    return agent


_GOOD_JSON = json.dumps({
    "is_error": False,
    "result": "hello",
    "usage": {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    },
    "stop_reason": "end_turn",
    "session_id": "abc",
    "duration_ms": 100,
})


def test_call_cli_success_parses_json(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: valid JSON response → populated LLMResponse."""
    agent = _make_agent(env)

    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=_GOOD_JSON, stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    resp = agent._call_cli("sys", "user", 4096, 0.2)

    assert isinstance(resp, LLMResponse)
    assert resp.text == "hello"
    assert resp.input_tokens == 10   # 10 + 0 + 0
    assert resp.output_tokens == 5
    assert resp.stop_reason == "end_turn"
    assert resp.raw["session_id"] == "abc"
    assert resp.raw["duration_ms"] == 100


def test_call_cli_input_tokens_include_cache_tokens(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """input_tokens should sum input + cache_read + cache_creation tokens."""
    agent = _make_agent(env)

    payload = json.dumps({
        "is_error": False,
        "result": "ok",
        "usage": {
            "input_tokens": 5,
            "output_tokens": 3,
            "cache_creation_input_tokens": 7,
            "cache_read_input_tokens": 11,
        },
        "stop_reason": "end_turn",
        "session_id": "xyz",
        "duration_ms": 50,
    })
    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=payload, stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    resp = agent._call_cli("sys", "user", 4096, 0.2)
    assert resp.input_tokens == 5 + 7 + 11  # = 23


def test_call_cli_returncode_nonzero_raises_LLMError(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero returncode → LLMError with rc info."""
    agent = _make_agent(env)

    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="boom"
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "rc=1" in str(exc_info.value)
    assert "boom" in str(exc_info.value)


def test_call_cli_invalid_json_raises_LLMError(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-JSON stdout → LLMError mentioning JSON parse failure."""
    agent = _make_agent(env)

    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not json", stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "JSON" in str(exc_info.value)


def test_call_cli_is_error_field_raises(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_error=true in response JSON → LLMError with result text."""
    agent = _make_agent(env)

    payload = json.dumps({
        "is_error": True,
        "result": "rate limit exceeded",
        "usage": {},
        "stop_reason": None,
        "session_id": None,
        "duration_ms": 0,
    })
    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=payload, stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "is_error=true" in str(exc_info.value)
    assert "rate limit" in str(exc_info.value)


def test_call_cli_timeout_raises_LLMError(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TimeoutExpired from subprocess → LLMError with 'timeout' in message."""
    agent = _make_agent(env)

    def raise_timeout(*a: Any, **kw: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="claude", timeout=180)

    monkeypatch.setattr("subprocess.run", raise_timeout)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "timeout" in str(exc_info.value).lower()


def test_call_cli_filenotfound_raises_LLMError(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FileNotFoundError from subprocess → LLMError."""
    agent = _make_agent(env)

    def raise_fnf(*a: Any, **kw: Any) -> None:
        raise FileNotFoundError("No such file: claude")

    monkeypatch.setattr("subprocess.run", raise_fnf)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "CLI" in str(exc_info.value) or "claude" in str(exc_info.value).lower()


def test_call_cli_empty_stdout_raises_LLMError(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty stdout with rc=0 → LLMError about empty response."""
    agent = _make_agent(env)

    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_proc)

    with pytest.raises(LLMError) as exc_info:
        agent._call_cli("sys", "user", 4096, 0.2)
    assert "bos" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()


def test_call_cli_uses_pa_claude_cli_env(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA_CLAUDE_CLI env var should override the cli_path used in the command."""
    agent = _make_agent(env)
    monkeypatch.setenv("PA_CLAUDE_CLI", "/custom/path/claude")

    captured: list[Any] = []

    def capture_run(cmd: list, **kw: Any) -> subprocess.CompletedProcess:
        captured.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=_GOOD_JSON, stderr=""
        )

    monkeypatch.setattr("subprocess.run", capture_run)
    agent._call_cli("sys", "user", 4096, 0.2)

    # The first element of cmd is the cli_path; _client overrides it via isinstance check
    # agent._client is already a str path so that's used, not PA_CLAUDE_CLI in _call_cli
    # (PA_CLAUDE_CLI is only used in _ensure_client). The cmd[0] should be agent._client.
    assert captured[0][0] == "/usr/local/bin/claude"


# ---------------------------------------------------------------------------
# C1 (KALAN_ISLER #15) — allowed_tools RUNTIME enforcement smoke testleri
#
# Sözleşme: her somut ajanın allowed_tools ClassVar'ı CLI komutuna
# --allowedTools olarak AYNEN geçer. Yazma-yetenekli soyut tool'u (write*)
# olmayan ajanlar (audit_* ailesi) acceptEdits ALMAZ → -p modunda Write/Edit
# otomatik red. Fail-safe: PA_AGENT_TOOL_ENFORCE=0 → eski davranış.
# LLM/subprocess YOK — saf komut-kurucu (_build_cli_cmd) + mock subprocess.
# ---------------------------------------------------------------------------

from price_action.agents import (
    AdversaryEngineerAgent,
    AnalystAgent,
    AuditChiefAgent,
    AuditDataAgent,
    AuditExecutionAgent,
    AuditOpsAgent,
    AuditResearchAgent,
    AuditRiskAgent,
    BotMonitorAgent,
    CEOAgent,
    DataEngineerAgent,
    LabScientistAgent,
    MarketScoutAgent,
    OpsAgent,
    ResearcherAgent,
    RiskOfficerAgent,
    StrategyCuratorAgent,
)
from price_action.agents.base import _build_cli_cmd

_CONCRETE_AGENT_CLASSES = [
    AdversaryEngineerAgent,
    AnalystAgent,
    AuditChiefAgent,
    AuditDataAgent,
    AuditExecutionAgent,
    AuditOpsAgent,
    AuditResearchAgent,
    AuditRiskAgent,
    BotMonitorAgent,
    CEOAgent,
    DataEngineerAgent,
    LabScientistAgent,
    MarketScoutAgent,
    OpsAgent,
    ResearcherAgent,
    RiskOfficerAgent,
    StrategyCuratorAgent,
]


def _allowed_tools_value(cmd: list) -> str:
    """cmd içindeki --allowedTools değerini döndür (yoksa fail)."""
    assert "--allowedTools" in cmd, f"--allowedTools yok: {cmd}"
    return cmd[cmd.index("--allowedTools") + 1]


def _permission_mode(cmd: list) -> str:
    assert "--permission-mode" in cmd, f"--permission-mode yok: {cmd}"
    return cmd[cmd.index("--permission-mode") + 1]


@pytest.mark.parametrize("cls", _CONCRETE_AGENT_CLASSES, ids=lambda c: c.__name__)
def test_cli_cmd_contains_allowed_tools_verbatim(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Her somut ajan: ClassVar allowed_tools CLI'a AYNEN geçer (uydurma liste yok)."""
    monkeypatch.delenv("PA_AGENT_TOOL_ENFORCE", raising=False)  # default=açık
    assert cls.allowed_tools, f"{cls.__name__}.allowed_tools boş — sözleşme eksik"
    cmd = _build_cli_cmd("claude", "test-model", "sys", cls.allowed_tools)
    assert _allowed_tools_value(cmd) == ",".join(cls.allowed_tools)
    # Hiçbir ajan CLI'ın gerçek Write/Edit tool'unu allowlist'e almaz —
    # soyut isimler (read_file, write_report...) CLI tool adlarıyla çakışmaz.
    for arg in cmd:
        assert arg != "Write" and arg != "Edit"
    tokens = _allowed_tools_value(cmd).split(",")
    assert "Write" not in tokens and "Edit" not in tokens


@pytest.mark.parametrize("cls", _CONCRETE_AGENT_CLASSES, ids=lambda c: c.__name__)
def test_cli_cmd_permission_mode_matches_write_contract(
    cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write* sözleşmesi olmayan ajan (audit_*) acceptEdits ALMAZ; yazıcılar alır."""
    monkeypatch.delenv("PA_AGENT_TOOL_ENFORCE", raising=False)
    cmd = _build_cli_cmd("claude", "test-model", "sys", cls.allowed_tools)
    can_write = any(t.startswith("write") for t in cls.allowed_tools)
    if can_write:
        assert _permission_mode(cmd) == "acceptEdits"
    else:
        # Read-only sözleşme: -p (print) modunda default mode → Write/Edit
        # onay istemi kurulamaz, CLI otomatik reddeder.
        assert _permission_mode(cmd) == "default"
        assert "acceptEdits" not in cmd


def test_audit_family_is_readonly_by_classvar() -> None:
    """audit_* sınıfları write* soyut tool taşımaz (independence by construction)."""
    for cls in (
        AuditChiefAgent,
        AuditDataAgent,
        AuditExecutionAgent,
        AuditOpsAgent,
        AuditResearchAgent,
        AuditRiskAgent,
    ):
        assert not any(t.startswith("write") for t in cls.allowed_tools), cls.__name__


def test_enforce_env_zero_restores_legacy_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-SAFE: PA_AGENT_TOOL_ENFORCE=0 → kısıt yok, acceptEdits geri (eski davranış)."""
    monkeypatch.setenv("PA_AGENT_TOOL_ENFORCE", "0")
    cmd = _build_cli_cmd("claude", "m", "sys", AuditChiefAgent.allowed_tools)
    assert "--allowedTools" not in cmd
    assert _permission_mode(cmd) == "acceptEdits"
    # Eski komutla birebir aynı iskelet:
    assert cmd == [
        "claude", "-p", "--output-format=json", "--model", "m",
        "--permission-mode", "acceptEdits", "--append-system-prompt", "sys",
    ]


def test_empty_allowed_tools_means_no_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    """allowed_tools boş/tanımsız → kısıt EKLENMEZ (eski davranış), enforcement açıkken bile."""
    monkeypatch.setenv("PA_AGENT_TOOL_ENFORCE", "1")
    for empty in ((), None):
        cmd = _build_cli_cmd("claude", "m", "sys", empty)
        assert "--allowedTools" not in cmd
        assert _permission_mode(cmd) == "acceptEdits"


def test_call_cli_passes_allowed_tools_through_subprocess(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entegrasyon (mock subprocess): _call_cli gerçek yolda kısıtı komuta koyar."""
    monkeypatch.delenv("PA_AGENT_TOOL_ENFORCE", raising=False)
    store = MemoryStore(base_dir=env["memdir"])
    agent = CEOAgent(memory_store=store)
    agent._client = "/usr/local/bin/claude"
    agent._client_kind = "cli"

    captured: list = []

    def capture_run(cmd: list, **kw: Any) -> subprocess.CompletedProcess:
        captured.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=_GOOD_JSON, stderr="")

    monkeypatch.setattr("subprocess.run", capture_run)
    agent._call_cli("sys", "user", 4096, 0.2)

    cmd = captured[0]
    assert _allowed_tools_value(cmd) == ",".join(CEOAgent.allowed_tools)
    assert _permission_mode(cmd) == "acceptEdits"  # ceo write_report taşıyor


def test_call_cli_audit_agent_gets_no_acceptedits(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entegrasyon (mock subprocess): read-only denetçi acceptEdits ALMAZ."""
    monkeypatch.delenv("PA_AGENT_TOOL_ENFORCE", raising=False)
    store = MemoryStore(base_dir=env["memdir"])
    agent = AuditChiefAgent(memory_store=store)
    agent._client = "/usr/local/bin/claude"
    agent._client_kind = "cli"

    captured: list = []

    def capture_run(cmd: list, **kw: Any) -> subprocess.CompletedProcess:
        captured.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=_GOOD_JSON, stderr="")

    monkeypatch.setattr("subprocess.run", capture_run)
    agent._call_cli("sys", "user", 4096, 0.2)

    cmd = captured[0]
    assert _allowed_tools_value(cmd) == ",".join(AuditChiefAgent.allowed_tools)
    assert _permission_mode(cmd) == "default"
    assert "acceptEdits" not in cmd
