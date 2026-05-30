"""İç Denetim — on-demand tam denetim turu (Faz 3 CLI).

5 domain denetçisini koşturur, bulguları reports/audit/ + findings_register.jsonl'e
emit eder, kapsama açıklarını tarar ve dashboard'u günceller.

Usage:
    .venv/bin/python scripts/run_audit.py            # tam tur + dashboard
    .venv/bin/python scripts/run_audit.py --dashboard-only   # sadece dashboard

Read-only denetçiler; trading'e dokunmaz. Çıktı: reports/audit/dashboard.md +
yeni audit_finding doc'ları + memory/audit/findings_register.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import os

os.environ.setdefault("PA_LOG_QUIET", "1")
try:
    from dotenv import load_dotenv

    load_dotenv()  # borsa erişimi için API anahtarları (CT-EXE-01 gerçek mutabakat)
except Exception:
    pass

from price_action.agents import AuditChiefAgent


async def _main(dashboard_only: bool) -> None:
    chief = AuditChiefAgent()
    if dashboard_only:
        path = chief.build_dashboard()
        print(f"[AUDIT] dashboard güncellendi: {path}")
        return
    print("[AUDIT] tam denetim turu başlıyor (5 domain + kapsama + dashboard)...")
    results = await chief.run_full_audit()
    for k, v in results.items():
        if k == "dashboard":
            print(f"[AUDIT] dashboard: {v}")
        else:
            print(f"[AUDIT]   {k}: {v} bulgu")
    summ = chief.register_summary()
    print(f"[AUDIT] register: toplam={summ['total']} açık={summ['open']} "
          f"overdue={summ['overdue']} recurrence={summ['recurring']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-only", action="store_true")
    args = ap.parse_args()
    asyncio.run(_main(args.dashboard_only))
