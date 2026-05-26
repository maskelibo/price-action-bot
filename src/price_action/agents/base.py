"""LLMAgentBase — tüm LLM agent'larının ortak temeli.

Bu sınıf:
- ``agents/<name>.md`` rule dosyasını + memory boot context'ini birleştirip
  system prompt üretir.
- Anthropic SDK üzerinden retry'lı LLM çağrısı yapar (claude_agent_sdk
  varsa onu, yoksa ``anthropic.Anthropic`` client'ını kullanır).
- ``PA_LLM_DRY_RUN=true`` ise gerçek çağrı yapmaz; deterministic mock
  cevap üretir (CI ve testler için).
- Token telemetrisini Prometheus counter'ına yazar
  (``pa_llm_tokens_total{agent, model, type}``).
- Her agent için **izinli tool listesi** tutar — gerçek tool çağrılarını
  dış orchestrator (Claude Agent SDK MCP) yapar; biz sadece deklare eder
  ve loglarız.
"""
from __future__ import annotations

import abc
import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from price_action.contracts import MemoryEntry
from price_action.logging_config import logger
from price_action.memory import EpisodicLog, MemoryStore
from price_action.memory.store import make_entry
from price_action.settings import get_settings


# FIX 2026-05-26 (H5): Global semaphore for CLI subprocess calls.
# Önceden 11 agent paralel claude CLI çağırabiliyordu — Max Pro 5-saatlik
# rate window'unu birden tüketebilirdi (asyncio.gather içinden 5-batch
# researcher veya weekend Pazar burst). Bu semaphore concurrent CLI
# çağrılarını N ile sınırlar (default 3, env PA_CLI_MAX_CONCURRENT ile
# override edilebilir).
_CLI_MAX_CONCURRENT = int(os.environ.get("PA_CLI_MAX_CONCURRENT", "3"))
_CLI_SEMAPHORE: asyncio.Semaphore | None = None  # lazy init (event loop bound)


def _get_cli_semaphore() -> asyncio.Semaphore:
    """Module-level singleton — first call current event loop'a bağlanır."""
    global _CLI_SEMAPHORE
    if _CLI_SEMAPHORE is None:
        _CLI_SEMAPHORE = asyncio.Semaphore(_CLI_MAX_CONCURRENT)
    return _CLI_SEMAPHORE


# FIX 2026-05-26 (H3): Circuit breaker for LLM calls.
# Önceden tenacity 3x × CCXT 5x × scheduler retry cascade riski vardı.
# Çözüm: per-agent failure counter; N consecutive fail in M minutes
# → circuit OPEN T seconds (retry'lar skip, push_critical alert).
# Half-open: T sonra 1 trial; başarılı ise CLOSE, fail ise yine OPEN.
_CIRCUIT_FAIL_THRESHOLD = int(os.environ.get("PA_CIRCUIT_FAIL_THRESHOLD", "5"))
_CIRCUIT_WINDOW_SECONDS = int(os.environ.get("PA_CIRCUIT_WINDOW_S", "300"))  # 5 dk
_CIRCUIT_OPEN_SECONDS = int(os.environ.get("PA_CIRCUIT_OPEN_S", "600"))     # 10 dk
_circuit_state: dict[str, dict[str, Any]] = {}  # agent_name → state


def _circuit_check(agent_name: str) -> tuple[bool, str]:
    """Returns (allow_call, reason).

    State per agent:
        failures: [timestamps of recent failures]
        open_until: datetime when circuit re-closes (None if closed)
    """
    state = _circuit_state.setdefault(agent_name, {"failures": [], "open_until": None})
    now = datetime.now(timezone.utc)

    # Eğer açık ise: timer geçti mi?
    if state["open_until"] is not None:
        if now < state["open_until"]:
            remaining = (state["open_until"] - now).total_seconds()
            return False, f"circuit_open ({remaining:.0f}s kaldı)"
        # Timer geçti — half-open (1 trial'a izin)
        state["open_until"] = None
        state["failures"] = []  # reset
        return True, "circuit_half_open_trial"

    return True, "circuit_closed"


def _circuit_record_failure(agent_name: str) -> None:
    """Failure kaydet — eşik aşılırsa circuit OPEN."""
    state = _circuit_state.setdefault(agent_name, {"failures": [], "open_until": None})
    now = datetime.now(timezone.utc)
    state["failures"].append(now)
    # Window dışındakileri at
    cutoff = now - timedelta(seconds=_CIRCUIT_WINDOW_SECONDS)
    state["failures"] = [t for t in state["failures"] if t >= cutoff]
    if len(state["failures"]) >= _CIRCUIT_FAIL_THRESHOLD:
        state["open_until"] = now + timedelta(seconds=_CIRCUIT_OPEN_SECONDS)
        logger.error(
            "agent.circuit_open",
            extra={
                "agent": agent_name,
                "failures": len(state["failures"]),
                "open_until": state["open_until"].isoformat(),
            },
        )
        # Telegram CRIT alert
        try:
            from price_action.orchestrator.notifications import push_critical
            push_critical(
                f"LLM circuit OPEN: {agent_name} — "
                f"{len(state['failures'])} fail in {_CIRCUIT_WINDOW_SECONDS}s, "
                f"retry'lar {_CIRCUIT_OPEN_SECONDS}s skip edilecek",
                source="circuit_breaker",
            )
        except Exception:
            pass


def _circuit_record_success(agent_name: str) -> None:
    """Başarılı çağrı — failure listesini temizle (recovery)."""
    state = _circuit_state.setdefault(agent_name, {"failures": [], "open_until": None})
    if state["failures"] or state["open_until"] is not None:
        logger.info("agent.circuit_recovered", extra={"agent": agent_name})
    state["failures"] = []
    state["open_until"] = None

# ----------------------------------------------------------------------
# Prometheus metrics — best-effort
# ----------------------------------------------------------------------

def _find_claude_cli() -> str | None:
    """Claude CLI'ı bul; Windows'ta .cmd wrapper yerine .exe'yi tercih et.

    .cmd wrapper çağrıldığında subprocess CMD.EXE'yi başlatır ve argv 8191
    char ile sınırlanır; .exe doğrudan CreateProcess ile çalışır (~32K limit),
    büyük sistem promptlarını taşımak için gereklidir.
    """
    # 1) Doğrudan exe (Windows npm global install)
    if os.name == "nt":
        candidate = (
            Path(os.environ.get("APPDATA", ""))
            / "npm"
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
        if candidate.is_file():
            return str(candidate)
    # 2) PATH'te claude.exe (Windows) veya claude (Unix)
    exe = shutil.which("claude.exe") if os.name == "nt" else None
    if exe:
        return exe
    return shutil.which("claude")


try:  # pragma: no cover - prometheus opsiyonel
    from price_action.api.prometheus_metrics import (
        llm_calls_total as PA_LLM_CALLS,
        llm_tokens_total as PA_LLM_TOKENS,
    )
except Exception:  # pragma: no cover

    class _Noop:
        def labels(self, **_kw: Any) -> "_Noop":
            return self

        def inc(self, *_a: Any, **_kw: Any) -> None:
            return None

    PA_LLM_TOKENS = _Noop()  # type: ignore[assignment]
    PA_LLM_CALLS = _Noop()  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Veri sınıfları
# ----------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Tek LLM çağrısı sonucu — agent'lardan dönen cevap."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    """LLM çağrı hatası (retry edilebilir)."""


# ----------------------------------------------------------------------
# Base
# ----------------------------------------------------------------------

class LLMAgentBase(abc.ABC):
    """Tüm LLM agent'larının ortak temeli.

    Subclass'lar ``allowed_tools`` ve ``default_model`` sınıf değişkenlerini
    set ederler.
    """

    name: ClassVar[str] = "agent"
    default_model: ClassVar[str] = ""  # boşsa settings.claude_model_default
    allowed_tools: ClassVar[tuple[str, ...]] = ()  # SDK'ya bildirilebilir

    def __init__(
        self,
        *,
        name: str | None = None,
        model: str | None = None,
        memory_store: MemoryStore | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> None:
        self.settings = get_settings()
        self.name = name or self.name
        self.model = model or self.default_model or self.settings.claude_model_default
        self.memory = memory_store or MemoryStore()
        # EpisodicLog memory store ile aynı base_dir'ı kullansın (test izolasyonu).
        self.episodic = EpisodicLog(agent=self.name, base_dir=self.memory.base_dir)
        self.mcp_servers = list(mcp_servers or [])
        self._client: Any = None  # lazy
        self._client_kind: str = ""  # "agent_sdk" | "anthropic" | "dry"

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _rules_path(self) -> Path:
        return self.settings.agents_rules_dir / f"{self.name}.md"

    def _load_rules(self) -> str:
        p = self._rules_path()
        if not p.exists():
            logger.warning("agent.rules_missing", extra={"agent": self.name, "path": str(p)})
            return ""
        return p.read_text(encoding="utf-8")

    def _load_protocol(self) -> str:
        """Faz 1.5: inter-agent protocol metnini oku (her oturumda system prompt'a girer)."""
        p = self.settings.memory_dir / "shared" / "protocol.md"
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:  # pragma: no cover
            return ""

    def _load_system_prompt(self) -> str:
        rules = self._load_rules().strip()
        boot = self.memory.boot_context(self.name).strip()
        protocol = self._load_protocol().strip()
        tools_line = (
            f"## ALLOWED TOOLS\n{', '.join(self.allowed_tools) or '(none)'}\n"
        )
        parts = [
            f"# AGENT: {self.name}",
            "## RULES (canonical)",
            rules or "(no rules file)",
            "## INTER-AGENT PROTOCOL",
            protocol or "(no protocol — protokol.md eksik)",
            "## BOOT CONTEXT (memory)",
            boot or "(no memory)",
            tools_line,
            "## OPERATING NOTES",
            (
                "- LLM rolün rapor/araştırma. Trading kararı veya canlı emir "
                "vermezsin.\n"
                "- API anahtarları, kişisel veri loglara/raporlara yazılmaz.\n"
                "- Memory dosyaları append-only — silme/üzerine yazma yok.\n"
                "- Tüm doc çıktıları INTER-AGENT PROTOCOL §1 frontmatter spec'ine uymalı.\n"
                "- Critique için PROTOCOL §3 5-zorunlu-alan formatını kullan."
            ),
        ]
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Client (lazy)
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        if os.getenv("PA_LLM_DRY_RUN", "").lower() in ("1", "true", "yes"):
            self._client_kind = "dry"
            self._client = object()
            return
        # 1) Claude Code CLI — `PA_LLM_USE_CLI=true` veya API key yokken
        #    `claude` binary varsa CLI'a düş. CLI subscription/OAuth ile
        #    auth olduğu için ANTHROPIC_API_KEY gerektirmez.
        prefer_cli = os.getenv("PA_LLM_USE_CLI", "").lower() in ("1", "true", "yes")
        api_key_present = bool(
            self.settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        )
        if prefer_cli or not api_key_present:
            cli = os.getenv("PA_CLAUDE_CLI") or _find_claude_cli()
            if cli:
                self._client_kind = "cli"
                self._client = cli
                return
        # 2) claude_agent_sdk
        try:  # pragma: no cover - opsiyonel paket
            import claude_agent_sdk  # type: ignore[import-not-found]  # noqa: F401

            self._client_kind = "agent_sdk"
            self._client = claude_agent_sdk
            return
        except Exception:
            pass
        # 3) anthropic SDK fallback
        try:
            import anthropic  # type: ignore[import-not-found]

            api_key = self.settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
            self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
            self._client_kind = "anthropic"
        except Exception as exc:  # pragma: no cover
            logger.error("agent.client_init_failed", extra={"agent": self.name, "err": str(exc)})
            self._client_kind = "dry"
            self._client = object()

    # ------------------------------------------------------------------
    # Çağrı
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        *,
        context_files: list[Path] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Asenkron LLM çağrısı — string cevap döndürür."""
        resp = await self.run_full(
            prompt,
            context_files=context_files,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.text

    async def run_full(
        self,
        prompt: str,
        *,
        context_files: list[Path] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Asenkron LLM çağrısı — tam cevap nesnesi."""
        self._ensure_client()
        system_prompt = self._load_system_prompt()
        user_text = self._build_user_message(prompt, context_files)

        if self._client_kind == "dry":
            resp = self._dry_run_response(prompt)
        else:
            # FIX 2026-05-26 (H5): CLI çağrılarını semaphore ile sınırla.
            # Sadece CLI subprocess path için (Anthropic SDK direct çağrıları
            # SDK'nin kendi rate limit'i var). dry-run + sdk path için
            # semaphore by-pass.
            if self._client_kind == "cli":
                sem = _get_cli_semaphore()
                async with sem:
                    resp = await asyncio.to_thread(
                        self._sync_call_with_retry,
                        system_prompt,
                        user_text,
                        max_tokens,
                        temperature,
                    )
            else:
                resp = await asyncio.to_thread(
                    self._sync_call_with_retry,
                    system_prompt,
                    user_text,
                    max_tokens,
                    temperature,
                )

        # Telemetri
        try:
            PA_LLM_TOKENS.labels(agent=self.name, model=self.model, type="input").inc(
                resp.input_tokens
            )
            PA_LLM_TOKENS.labels(agent=self.name, model=self.model, type="output").inc(
                resp.output_tokens
            )
            PA_LLM_CALLS.labels(agent=self.name, model=self.model, status="ok").inc()
        except Exception:  # pragma: no cover
            pass

        # FIX 2026-05-26 (C3): Persistent audit log — Prometheus counter
        # restart'ta sıfırlanıyor, gerçek günlük kullanım kaybediliyordu.
        # JSONL append-only source of truth; token_budget.get_token_stats
        # bunu okuyup tüm-zaman cumulative sum verebiliyor.
        try:
            import json as _json
            from datetime import datetime as _dt, timezone as _tz
            from pathlib import Path as _Path
            _audit_path = _Path("data/llm_calls.jsonl")
            _audit_path.parent.mkdir(parents=True, exist_ok=True)
            _audit_record = {
                "ts": _dt.now(_tz.utc).isoformat(),
                "agent": self.name,
                "model": self.model,
                "input_tokens": int(resp.input_tokens or 0),
                "output_tokens": int(resp.output_tokens or 0),
                "stop_reason": resp.stop_reason,
            }
            with open(_audit_path, "a", encoding="utf-8") as _af:
                _af.write(_json.dumps(_audit_record) + "\n")
                _af.flush()
        except Exception:  # pragma: no cover — audit fail trade'i durdurmamalı
            pass

        # Episodic kayıt (özet)
        self.record_episodic(
            f"[{self.model}] prompt={prompt[:120]} -> resp={resp.text[:120]}",
            tags=["llm_call"],
        )
        logger.info(
            "agent.llm_call",
            extra={
                "agent": self.name,
                "model": self.model,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "stop_reason": resp.stop_reason,
            },
        )
        return resp

    def _build_user_message(
        self, prompt: str, context_files: list[Path] | None
    ) -> str:
        parts = [prompt.strip()]
        for cf in context_files or []:
            try:
                content = Path(cf).read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(
                    "agent.context_file_missing",
                    extra={"agent": self.name, "file": str(cf), "err": str(exc)},
                )
                continue
            parts.append(f"\n\n--- CONTEXT FILE: {Path(cf).name} ---\n{content}")
        return "\n".join(parts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(LLMError),
        reraise=True,
    )
    def _sync_call_with_retry(
        self,
        system_prompt: str,
        user_text: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        # FIX 2026-05-26 (H3): Circuit breaker check
        allow, reason = _circuit_check(self.name)
        if not allow:
            raise LLMError(f"circuit_breaker_open: {reason}")
        try:
            if self._client_kind == "cli":
                resp = self._call_cli(system_prompt, user_text, max_tokens, temperature)
            elif self._client_kind == "agent_sdk":
                resp = self._call_agent_sdk(system_prompt, user_text, max_tokens, temperature)
            else:
                resp = self._call_anthropic(system_prompt, user_text, max_tokens, temperature)
            _circuit_record_success(self.name)
            return resp
        except LLMError:
            _circuit_record_failure(self.name)
            raise
        except Exception as exc:
            _circuit_record_failure(self.name)
            try:
                PA_LLM_CALLS.labels(agent=self.name, model=self.model, status="error").inc()
            except Exception:  # pragma: no cover
                pass
            logger.warning(
                "agent.llm_retry",
                extra={"agent": self.name, "err": str(exc)[:200]},
            )
            raise LLMError(str(exc)) from exc

    def _call_anthropic(  # pragma: no cover - dış servis
        self, system_prompt: str, user_text: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        client = self._client
        msg = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_text}],
            timeout=60.0,
        )
        # Anthropic SDK >=0.39 message yapısı
        text_parts: list[str] = []
        for block in getattr(msg, "content", []) or []:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        usage = getattr(msg, "usage", None)
        in_t = int(getattr(usage, "input_tokens", 0)) if usage else 0
        out_t = int(getattr(usage, "output_tokens", 0)) if usage else 0
        return LLMResponse(
            text="".join(text_parts),
            model=self.model,
            input_tokens=in_t,
            output_tokens=out_t,
            stop_reason=getattr(msg, "stop_reason", None),
            raw={},
        )

    def _call_agent_sdk(  # pragma: no cover - dış servis
        self, system_prompt: str, user_text: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        sdk = self._client
        # SDK API'si versiyonlar arası değişebilir; defansif çağrı:
        if hasattr(sdk, "Client"):
            client = sdk.Client(api_key=self.settings.anthropic_api_key or None)
            result = client.run(
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}],
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                allowed_tools=list(self.allowed_tools),
                mcp_servers=self.mcp_servers,
                timeout=60.0,
            )
            text = getattr(result, "text", str(result))
            usage = getattr(result, "usage", {}) or {}
            return LLMResponse(
                text=text,
                model=self.model,
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                stop_reason=getattr(result, "stop_reason", None),
            )
        # Bilinmeyen şema → anthropic SDK'ya düş
        import anthropic  # type: ignore[import-not-found]

        self._client = anthropic.Anthropic(
            api_key=self.settings.anthropic_api_key or None
        )
        self._client_kind = "anthropic"
        return self._call_anthropic(system_prompt, user_text, max_tokens, temperature)

    def _call_cli(  # pragma: no cover - dış servis
        self, system_prompt: str, user_text: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        """Claude Code CLI'ı subprocess olarak çağır.

        ANTHROPIC_API_KEY gerektirmez — CLI subscription/OAuth ile auth olur.
        ``--bare`` KULLANILMAZ (bare API key zorunlu kılar). Sistem promptu
        ``--append-system-prompt`` ile, user mesajı stdin üzerinden geçirilir.
        ``--output-format=json`` cevabı ve token usage'ı yapılandırılmış döner.
        """
        cli_path = self._client if isinstance(self._client, str) else "claude"
        # FIX 2026-05-26 (M4): timeout bounds check — geçersiz değer instant
        # fail loop'a sebep olurdu (PA_CLI_TIMEOUT_S=0 → instant timeout → retry).
        try:
            timeout_s = float(os.getenv("PA_CLI_TIMEOUT_S", "180"))
        except (ValueError, TypeError):
            timeout_s = 180.0
        # Bounds: minimum 30s (subprocess overhead), maximum 1800s (30dk)
        if timeout_s < 30:
            logger.warning(
                "agent.cli_timeout_below_min",
                extra={"requested": timeout_s, "clamped_to": 30},
            )
            timeout_s = 30.0
        elif timeout_s > 1800:
            logger.warning(
                "agent.cli_timeout_above_max",
                extra={"requested": timeout_s, "clamped_to": 1800},
            )
            timeout_s = 1800.0
        cmd = [
            cli_path,
            "-p",
            "--output-format=json",
            "--model",
            self.model,
            "--append-system-prompt",
            system_prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=user_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"claude CLI bulunamadi: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude CLI timeout ({timeout_s}s)") from exc

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:500]
            raise LLMError(f"claude CLI rc={proc.returncode}: {err}")

        out = (proc.stdout or "").strip()
        if not out:
            raise LLMError("claude CLI bos cevap dondurdu")
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude CLI JSON parse hatasi: {exc}; head={out[:200]}") from exc

        if data.get("is_error"):
            raise LLMError(f"claude CLI is_error=true: {data.get('result', '')[:200]}")

        text = data.get("result", "") or ""
        usage = data.get("usage") or {}
        in_t = int(usage.get("input_tokens", 0)) + int(
            usage.get("cache_read_input_tokens", 0)
        ) + int(usage.get("cache_creation_input_tokens", 0))
        out_t = int(usage.get("output_tokens", 0))
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=in_t,
            output_tokens=out_t,
            stop_reason=data.get("stop_reason"),
            raw={"session_id": data.get("session_id"), "duration_ms": data.get("duration_ms")},
        )

    def _dry_run_response(self, prompt: str) -> LLMResponse:
        text = (
            f"[DRY RUN — {self.name}/{self.model}] "
            f"prompt='{prompt[:160]}' — gerçek LLM çağrısı yapılmadı."
        )
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
            stop_reason="dry_run",
        )

    # ------------------------------------------------------------------
    # Memory yardımcıları
    # ------------------------------------------------------------------

    def record_episodic(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        kind: str = "episodic",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Episodic JSONL'e satır ekle."""
        self.episodic.append(content, tags=tags, kind=kind, extra=extra)

    def append_learning(
        self,
        body: str,
        *,
        slug: str | None = None,
        confidence: str = "med",
        tags: list[str] | None = None,
    ) -> Path:
        entry = make_entry(
            self.name,
            body,
            entry_type="learning",
            slug=slug,
            confidence=confidence,
            tags=tags,
        )
        return self.memory.append_learning(self.name, entry)

    def append_know_how(
        self,
        body: str,
        *,
        slug: str | None = None,
        tags: list[str] | None = None,
    ) -> Path:
        entry = make_entry(self.name, body, entry_type="know_how", slug=slug, tags=tags)
        return self.memory.append_know_how(self.name, entry)

    def write_decision(self, adr: dict[str, Any], slug: str | None = None) -> Path:
        return self.memory.write_decision(self.name, adr, slug=slug)

    # ------------------------------------------------------------------
    # Faz 1.5 — INTER-AGENT PROTOCOL helper
    # ------------------------------------------------------------------

    def write_protocol_doc(
        self,
        doc_type: str,
        body: str,
        *,
        slug: str | None = None,
        target_dir: Path | None = None,
        status: str = "DRAFT",
        confidence: str = "med",
        depends_on: list[str] | None = None,
        blocks: list[str] | None = None,
        requested_review_from: list[str] | None = None,
        tags: list[str] | None = None,
        supersedes: str | None = None,
    ) -> Path:
        """Protokol-uyumlu doc yaz (`memory/shared/protocol.md` §1 spec).

        Frontmatter otomatik üretilir; doc_id globally unique; inbox.jsonl'e
        broadcast satır eklenir (`requested_review_from`'daki her agent için).

        Parameters
        ----------
        doc_type:
            ``brief|hypothesis|tournament|drift_alert|whatif|adr|postmortem|incident|directive|critique|endorse|learning|decision``
        body:
            Markdown body — frontmatter SONRASI içerik.
        slug:
            Kısa kebab-case identifier. Yoksa doc_type + ts'ten üretilir.
        target_dir:
            Çıkış dizini. Yoksa `reports/<agent>/` (örn. `reports/researcher/`).
        status / confidence / depends_on / blocks / requested_review_from / tags / supersedes:
            Frontmatter alanları — `memory/shared/protocol.md` §1.

        Returns
        -------
        Path
            Oluşturulan doc'un yolu.
        """
        ts = datetime.now(timezone.utc)
        ts_compact = ts.strftime("%Y%m%dT%H%M%S")
        ts_iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        if slug is None:
            slug = doc_type
        # Sanitize slug: slash, space, special chars → tire (filesystem safe)
        import re as _re
        slug = _re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-").lower()
        if not slug:
            slug = doc_type
        doc_id = f"{self.name}-{ts_compact}-{slug}"

        # Frontmatter
        fm_lines = [
            "---",
            f"doc_id: {doc_id}",
            f"doc_type: {doc_type}",
            f"agent_id: {self.name}",
            f"created_at: {ts_iso}",
            f"status: {status}",
            f"confidence: {confidence}",
            f"depends_on: {json.dumps(depends_on or [])}",
            f"blocks: {json.dumps(blocks or [])}",
            f"requested_review_from: {json.dumps(requested_review_from or [])}",
            f"tags: {json.dumps(tags or [])}",
        ]
        if supersedes:
            fm_lines.append(f"supersedes: {supersedes}")
        fm_lines.append("---")
        content = "\n".join(fm_lines) + "\n\n" + body.strip() + "\n"

        # Çıkış dizini
        if target_dir is None:
            # Varsayılan: reports/<agent>/<doc_type>/<doc_id>.md
            target_dir = self.settings.reports_dir / self.name
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(
            "agent.protocol_doc_written",
            extra={
                "agent": self.name,
                "doc_id": doc_id,
                "doc_type": doc_type,
                "path": str(path),
                "requested_review_from": requested_review_from or [],
            },
        )

        # Inbox broadcast (requested_review_from'daki her agent için satır)
        try:
            self._inbox_publish(
                doc_id=doc_id,
                ref_path=str(path.relative_to(self.settings.reports_dir.parent)),
                recipients=requested_review_from or [],
                topic=doc_type,
                ts_iso=ts_iso,
            )
        except Exception as exc:
            logger.warning(
                "agent.inbox_publish_fail",
                extra={"doc_id": doc_id, "err": str(exc)[:200]},
            )

        return path

    def _inbox_publish(
        self,
        *,
        doc_id: str,
        ref_path: str,
        recipients: list[str],
        topic: str,
        ts_iso: str,
    ) -> None:
        """Inbox.jsonl'e mesaj satırları ekle (append-only).

        `recipients` boşsa `all` broadcast — herkes okur, ack beklenmiyor.
        """
        inbox = self.settings.memory_dir / "protocol" / "inbox.jsonl"
        inbox.parent.mkdir(parents=True, exist_ok=True)

        targets = recipients if recipients else ["all"]
        with inbox.open("a", encoding="utf-8") as f:
            for recipient in targets:
                msg = {
                    "doc_id": doc_id,
                    "sender": self.name,
                    "recipient": recipient,
                    "topic": topic,
                    "ref_path": ref_path,
                    "created_at": ts_iso,
                    "ack_at": None,
                }
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Konsolidasyon (Lab tarafından çağrılır)
    # ------------------------------------------------------------------

    def consolidate_weekly(self, last_n_days: int = 7) -> dict[str, Any]:
        """Episodic logu özetler ve learning/know_how'a transfer eder.

        Çıktı: konsolidasyon raporu dict.
        """
        report = self.episodic.consolidate(last_n_days=last_n_days)
        # Tekrar eden body prefix'leri learning olarak kaydet
        for body_prefix, count in report.get("frequent_bodies", []) or []:
            entry = make_entry(
                self.name,
                f"Tekrar eden episode (x{count}): {body_prefix}",
                entry_type="learning",
                slug=f"recurring-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                confidence="med",
                tags=["consolidation", "recurring"],
            )
            self.memory.append_learning(self.name, entry)
        # Top tags know_how'a not olarak
        if report.get("top_tags"):
            tags_str = ", ".join(f"{t}:{c}" for t, c in report["top_tags"])
            note = MemoryEntry(
                agent=self.name,
                type="know_how",
                slug=f"weekly-tag-snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                body=f"Haftalık episodic tag dağılımı: {tags_str}",
                tags=["consolidation"],
            )
            self.memory.append_know_how(self.name, note)
        logger.info(
            "agent.consolidation_done",
            extra={"agent": self.name, "total": report.get("total", 0)},
        )
        return report
