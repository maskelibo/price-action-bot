#!/usr/bin/env python3
"""verify_scheduler — 9 cron job'un canlı doğrulaması (DRY-RUN).

Scheduler'ı **start ETMEZ**; sadece her JOB_TABLE entry'sini tek sefer
asyncio ile çağırır, sonucu ölçer, markdown rapor üretir.

Çıktı: `reports/ops/scheduler-verification-YYYY-MM-DD.md`

Usage
-----
    cd ~/price-action-bot
    PYTHONPATH=src .venv/bin/python scripts/verify_scheduler.py

    # DRY-RUN ZORUNLU değil — script kendi env'ini set eder
    # Ama gerçek LLM çağrısı yapmak istemezseniz:
    PYTHONPATH=src PA_LLM_DRY_RUN=true .venv/bin/python scripts/verify_scheduler.py

Faz 1.3 — `cosmic-cuddling-cocke.md` planının verify gate'i.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

# PYTHONPATH öner — interactive çalıştırmada
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


async def _run_one_job(job_id: str, func: Any) -> dict[str, Any]:
    """Tek bir job func'u çalıştır, exception'ı yakala, sonuç döndür."""
    start = time.perf_counter()
    error: str | None = None
    try:
        await asyncio.wait_for(func(), timeout=120)
    except asyncio.TimeoutError:
        error = "TIMEOUT (>120s)"
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "job_id": job_id,
        "elapsed_ms": elapsed_ms,
        "status": "OK" if error is None else "FAIL",
        "error": error,
    }


async def _main(dry_run: bool, output_dir: Path) -> int:
    if dry_run:
        os.environ["PA_LLM_DRY_RUN"] = "true"

    # Import schedule jobs (lazy — env hazırlandıktan sonra)
    from price_action.orchestrator.scheduler import JOB_TABLE

    print(f"=== verify_scheduler — {date.today().isoformat()} ===")
    print(f"PA_LLM_DRY_RUN={os.environ.get('PA_LLM_DRY_RUN', 'false')}")
    print(f"PA_CEO_PUSH_TELEGRAM={os.environ.get('PA_CEO_PUSH_TELEGRAM', 'false')}")
    print(f"PA_RUN_MODE={os.environ.get('PA_RUN_MODE', 'unset')}")
    print(f"Toplam {len(JOB_TABLE)} job test edilecek\n")

    results: list[dict[str, Any]] = []
    for job_id, kind, expr, func in JOB_TABLE:
        if kind != "cron":
            continue
        print(f"  [{job_id:30s}] cron='{expr}' çalıştırılıyor...", end=" ", flush=True)
        r = await _run_one_job(job_id, func)
        r["cron"] = expr
        results.append(r)
        status_icon = "✓" if r["status"] == "OK" else "✗"
        print(f"{status_icon} {r['status']} ({r['elapsed_ms']}ms)" + (f" — {r['error']}" if r["error"] else ""))

    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    print()
    print(f"=== ÖZET: {n_ok}/{len(results)} OK, {n_fail} FAIL ===")

    # Markdown rapor
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"scheduler-verification-{date.today().isoformat()}.md"
    _write_report(report_path, results, dry_run=dry_run)
    print(f"\nRapor: {report_path}")

    # Exit code: bir tane bile fail varsa non-zero (CI için)
    return 0 if n_fail == 0 else 1


def _write_report(path: Path, results: list[dict[str, Any]], *, dry_run: bool) -> None:
    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")

    lines = [
        "---",
        f"doc_id: ops-{date.today().strftime('%Y%m%dT000000')}-scheduler-verify",
        "doc_type: incident" if n_fail > 0 else "doc_type: postmortem",
        "agent_id: ops_engineer",
        f"created_at: {date.today().isoformat()}T00:00:00Z",
        "status: ACTIVE",
        f"confidence: high",
        "depends_on: []",
        "blocks: []",
        "requested_review_from: []",
        "tags: [verify, scheduler, faz1]",
        "---",
        "",
        f"# Scheduler Verification — {date.today().isoformat()}",
        "",
        f"**Mode:** {'DRY-RUN' if dry_run else 'LIVE'}",
        f"**Sonuç:** {n_ok}/{len(results)} OK, {n_fail} FAIL",
        "",
        "## Job Tablo",
        "",
        "| Job ID | Cron | Status | Duration | Error |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        err = r["error"][:80] + "…" if r["error"] and len(r["error"]) > 80 else (r["error"] or "—")
        lines.append(
            f"| `{r['job_id']}` | `{r['cron']}` | {r['status']} | {r['elapsed_ms']}ms | {err} |"
        )
    lines.extend([
        "",
        "## Yorumlama",
        "",
        "- **OK + DRY-RUN:** Job func import edildi ve dry-run yanıt verdi (LLM çağrı yapılmadı).",
        "- **FAIL + ImportError:** Modül eksik veya yol problemi.",
        "- **FAIL + TimeoutError:** Job 120sn'de bitmedi — büyük olasılıkla LLM çağrısı askıda.",
        "- **OK + LIVE:** Gerçek LLM çağrısı yapıldı, başarılı.",
        "",
        "## Sonraki Adım",
        "",
        "FAIL varsa: log dosyalarına bak (`logs/launchd/ceo.stderr.log`)" if n_fail > 0
        else "Tümü OK — `launchctl load ~/Library/LaunchAgents/com.priceaction.ceo.plist` ile autostart kur.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="verify scheduler jobs (dry-run)")
    p.add_argument(
        "--live",
        action="store_true",
        help="Gerçek LLM çağrısı yap (default: dry-run)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/ops"),
        help="Rapor çıkış dizini",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rc = asyncio.run(_main(dry_run=not args.live, output_dir=args.output_dir))
    sys.exit(rc)


if __name__ == "__main__":
    main()
