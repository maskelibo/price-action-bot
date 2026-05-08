"""CLI Smoke — `claude` CLI üzerinden gerçek bir LLM çağrısı yapar.

Çalıştırma (proje kökünden):
    PYTHONPATH=src PA_LLM_USE_CLI=true python scripts/cli_smoke.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


async def main() -> int:
    os.environ.setdefault("PA_LLM_USE_CLI", "true")
    os.environ.pop("PA_LLM_DRY_RUN", None)

    from price_action.agents.ceo import CEOAgent  # noqa: E402

    agent = CEOAgent()
    agent.model = os.getenv("PA_SMOKE_MODEL", "claude-haiku-4-5")

    prompt = (
        "TEK CUMLE: Trading sisteminin sabah brief'inin en kritik 1 metrigi nedir? "
        "Sadece cevap; baska aciklama yok."
    )
    print(f"[smoke] agent={agent.name} model={agent.model}")
    print(f"[smoke] kind=...", flush=True)
    agent._ensure_client()
    print(f"[smoke] client_kind={agent._client_kind}", flush=True)
    if agent._client_kind != "cli":
        print(f"[smoke] HATA: client_kind cli olmali, '{agent._client_kind}' bulundu.", file=sys.stderr)
        return 2

    resp = await agent.run_full(prompt, max_tokens=256, temperature=0.2)
    print("---")
    print(f"text          : {resp.text!r}")
    print(f"input_tokens  : {resp.input_tokens}")
    print(f"output_tokens : {resp.output_tokens}")
    print(f"stop_reason   : {resp.stop_reason}")
    print(f"raw           : {resp.raw}")
    print("---")
    if not resp.text.strip():
        print("[smoke] HATA: bos cevap.", file=sys.stderr)
        return 3
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
