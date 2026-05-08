"""Live Agents Test — 5 LLM agent'i `claude` CLI uzerinden gercek model ile cagir.

Her agent icin:
- LLMResponse alinir (text + token usage)
- episodic.jsonl'e satir yazildigi dogrulanir
- learning.md / know_how.md icin de bir append testi yapilir (Lab Scientist)

Cikti tablosunu stdout'a basar; herhangi bir agent fail olursa rc=1 doner.

Calistirma:
    PYTHONPATH=src PA_LLM_USE_CLI=true python scripts/live_agents_test.py
    # Hizli/ucuz model: PA_SMOKE_MODEL=claude-haiku-4-5 (default)
    # Tam: PA_SMOKE_MODEL=claude-sonnet-4-6
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _hr(label: str, char: str = "=") -> None:
    print(f"\n{char * 8} {label} {char * (60 - len(label))}")


async def _call_one(agent_cls: type, name: str, prompt: str) -> dict[str, Any]:
    from price_action.agents.base import LLMAgentBase  # noqa: F401  (sanity)

    agent = agent_cls()
    agent.model = os.getenv("PA_SMOKE_MODEL", "claude-haiku-4-5")

    # Episodic baseline
    log_path = agent.episodic.path
    before_lines = (
        log_path.read_text(encoding="utf-8").count("\n") if log_path.exists() else 0
    )

    agent._ensure_client()
    if agent._client_kind != "cli":
        return {
            "agent": name,
            "ok": False,
            "err": f"client_kind={agent._client_kind}, beklenen 'cli'",
        }

    t0 = time.time()
    try:
        resp = await agent.run_full(prompt, max_tokens=400, temperature=0.2)
    except Exception as exc:
        return {"agent": name, "ok": False, "err": f"{type(exc).__name__}: {exc}"}
    dt = time.time() - t0

    after_lines = (
        log_path.read_text(encoding="utf-8").count("\n") if log_path.exists() else 0
    )
    episodic_appended = after_lines > before_lines

    return {
        "agent": name,
        "ok": bool(resp.text.strip()) and episodic_appended,
        "model": resp.model,
        "in_tok": resp.input_tokens,
        "out_tok": resp.output_tokens,
        "stop": resp.stop_reason,
        "dur_s": round(dt, 1),
        "episodic": episodic_appended,
        "preview": resp.text.strip().replace("\n", " ")[:140],
    }


async def main() -> int:
    os.environ.setdefault("PA_LLM_USE_CLI", "true")
    os.environ.pop("PA_LLM_DRY_RUN", None)

    # Agent imports
    from price_action.agents.ceo import CEOAgent
    from price_action.agents.researcher import ResearcherAgent
    from price_action.agents.analyst import AnalystAgent
    from price_action.agents.lab_scientist import LabScientistAgent
    from price_action.agents.ops_engineer import OpsAgent

    # Her agent icin kucuk, deterministik prompt:
    plan: list[tuple[type, str, str]] = [
        (
            CEOAgent,
            "ceo",
            "Tek cumle: Bir trading desk CEO'sunun sabah brief'inde olmamasi gereken 1 sey nedir? Aciklama yapma, sadece cumleyi yaz.",
        ),
        (
            ResearcherAgent,
            "researcher",
            "Tek cumle: Pre-registered hipotezde 'curve-fit suphesi' nasil onlenir? Sadece tek cumle.",
        ),
        (
            AnalystAgent,
            "analyst",
            "Tek cumle: Gunluk KPI brief'inde 'profit factor' rakamini tek basina raporlamanin riski nedir? Sadece tek cumle.",
        ),
        (
            LabScientistAgent,
            "lab_scientist",
            "Tek cumle: Walk-forward dilim oraninin %66'nin altinda kalmasi neyi gosterir? Sadece tek cumle.",
        ),
        (
            OpsAgent,
            "ops_engineer",
            "Tek cumle: Kill-switch tetiklendikten sonra ilk 3 dakika icinde kontrol edilmesi gereken metrik nedir? Sadece tek cumle.",
        ),
    ]

    print(f"[live] model={os.getenv('PA_SMOKE_MODEL', 'claude-haiku-4-5')}")
    print(f"[live] CLI={os.getenv('PA_LLM_USE_CLI')}")

    results: list[dict[str, Any]] = []
    for cls, name, prompt in plan:
        _hr(name)
        print(f"prompt: {prompt}")
        r = await _call_one(cls, name, prompt)
        results.append(r)
        if r.get("ok"):
            print(
                f"  OK  in={r['in_tok']:>6}  out={r['out_tok']:>4}  "
                f"stop={r['stop']:<10}  dur={r['dur_s']:>4}s  "
                f"episodic={'+' if r['episodic'] else 'X'}"
            )
            print(f"  cevap: {r['preview']}")
        else:
            print(f"  FAIL  err={r.get('err')}")

    # Ozet tablo
    _hr("OZET")
    ok = sum(1 for r in results if r.get("ok"))
    total = len(results)
    print(f"\n{'agent':<14} {'ok':<4} {'in':>6} {'out':>5} {'dur':>5}  preview")
    print("-" * 100)
    for r in results:
        flag = "Y" if r.get("ok") else "N"
        print(
            f"{r['agent']:<14} {flag:<4} "
            f"{r.get('in_tok', 0):>6} {r.get('out_tok', 0):>5} "
            f"{r.get('dur_s', 0):>4}s  "
            f"{r.get('preview', r.get('err', ''))[:60]}"
        )

    # Memory append testi (Lab Scientist'a learning yaz)
    _hr("memory append (Lab Scientist learning)")
    try:
        from price_action.agents.lab_scientist import LabScientistAgent

        lab = LabScientistAgent()
        path = lab.append_learning(
            "Live test: CLI yolu uzerinden ilk e2e cagri basarili.",
            slug=f"live-test-{int(time.time())}",
            confidence="high",
            tags=["live_test", "cli"],
        )
        print(f"  learning.md path: {path}")
        print(f"  exists: {path.exists()}, size: {path.stat().st_size}")
    except Exception as exc:
        print(f"  FAIL learning append: {exc}")
        ok -= 1

    print(f"\n[live] {ok}/{total} agent OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
