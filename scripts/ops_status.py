#!/usr/bin/env python3
"""ops_status — Operations dashboard CLI (Faz 4.5).

Tek ekranda otonom ofis durumu:
- Çalışan launchd job'ları (com.priceaction.*)
- futures_daemon.py + ceo_loop process'leri
- Son 24h scheduler job tick özetleri
- Bekleyen inbox doc sayısı (per recipient)
- Open principal decisions (active_state.md'den)
- Token kullanımı snapshot (Prometheus varsa)
- logs/ disk usage

Usage
-----
    cd ~/price-action-bot
    PYTHONPATH=src .venv/bin/python scripts/ops_status.py

    # JSON output (cron/monitoring entegrasyonu için)
    PYTHONPATH=src .venv/bin/python scripts/ops_status.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _check_launchd() -> list[dict]:
    """launchctl list | grep priceaction."""
    try:
        out = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return [{"error": out.stderr[:200]}]
        results = []
        for line in out.stdout.split("\n"):
            if "priceaction" in line.lower():
                parts = line.split()
                if len(parts) >= 3:
                    results.append({
                        "pid": parts[0],
                        "status": parts[1],
                        "label": parts[2],
                    })
        return results
    except Exception as e:
        return [{"error": str(e)[:200]}]


def _check_p1c_walker() -> dict:
    """P1c walker state summary (5m bot)."""
    try:
        sys.path.insert(0, str(SRC))
        from price_action.execution.p1c_walker import P1cWalker
        from pathlib import Path as _P

        cfg_path = ROOT / "configs" / "risk_phoenix_scalp_5m_p1c.yaml"
        if not cfg_path.exists():
            return {"status": "config not found"}
        walker = P1cWalker(config_path=cfg_path)
        summary = walker.state_summary()
        halts = walker.check_halts()
        return {
            "equity_usdt": summary["equity"],
            "mtd_pnl_pct": summary["mtd_pnl_pct"],
            "n_trades": summary["n_trades"],
            "n_open": summary["n_open"],
            "halted": halts["halted"],
            "halt_reason": halts.get("reason", "ok"),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_processes() -> list[dict]:
    """ps aux | grep futures_daemon | ceo_loop."""
    try:
        out = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        results = []
        for line in out.stdout.split("\n"):
            ll = line.lower()
            if "futures_daemon" in ll or "ceo_loop" in ll:
                if "grep" in ll:
                    continue
                parts = line.split(maxsplit=10)
                if len(parts) >= 11:
                    results.append({
                        "user": parts[0],
                        "pid": parts[1],
                        "cpu_pct": parts[2],
                        "mem_pct": parts[3],
                        "start": parts[8],
                        "cmd": parts[10][:80],
                    })
        return results
    except Exception as e:
        return [{"error": str(e)[:200]}]


def _check_inbox() -> dict:
    """memory/protocol/inbox.jsonl per-recipient pending count."""
    inbox = ROOT / "memory" / "protocol" / "inbox.jsonl"
    if not inbox.exists():
        return {"status": "inbox not found"}
    try:
        lines = inbox.read_text(encoding="utf-8").strip().split("\n")
        total = 0
        pending_per_recipient: dict[str, int] = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            if not msg.get("ack_at"):
                rec = msg.get("recipient", "?")
                pending_per_recipient[rec] = pending_per_recipient.get(rec, 0) + 1
        return {
            "total_messages": total,
            "pending_per_recipient": pending_per_recipient,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_active_state() -> dict:
    """active_state.md last_updated + Pending Principal Decisions count."""
    p = ROOT / "memory" / "shared" / "active_state.md"
    if not p.exists():
        return {"status": "ledger not found"}
    try:
        content = p.read_text(encoding="utf-8")
        # last_updated parse
        import re
        m = re.search(r"^last_updated:\s*(\S+)", content, re.MULTILINE)
        last_updated = m.group(1) if m else "unknown"

        # Count pending principal decisions (rough — table rows in #6 section)
        # Section başlığı "## 6. Pending Principal Decisions"
        pending_section = content.split("## 6. Pending Principal Decisions")
        n_pending = 0
        if len(pending_section) >= 2:
            # Next ## heading'e kadar table satırlarını say
            section = pending_section[1].split("\n## ")[0]
            # Markdown table rows that have | and aren't header/separator
            for line in section.split("\n"):
                line = line.strip()
                if line.startswith("|") and not line.startswith("|---") and "Description" not in line:
                    if line.count("|") >= 3:
                        n_pending += 1
        return {
            "last_updated": last_updated,
            "pending_principal_decisions": n_pending,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_token_stats() -> dict:
    """Prometheus registry'den token snapshot (varsa)."""
    try:
        from price_action.ops.token_budget import get_token_stats
        stats = get_token_stats(window_hours=168)
        if not stats:
            return {"status": "no token usage (process restart sonrası 0)"}
        total_input = sum(s["input"] for s in stats.values())
        total_output = sum(s["output"] for s in stats.values())
        total_cost = sum(s["cost_usd"] for s in stats.values())
        return {
            "n_agent_model_combos": len(stats),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(total_cost, 4),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_disk() -> dict:
    """logs/ disk usage."""
    logs_dir = ROOT / "logs"
    if not logs_dir.exists():
        return {"status": "logs/ yok"}
    try:
        out = subprocess.run(
            ["du", "-sh", str(logs_dir)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        size = out.stdout.split()[0] if out.stdout else "?"
        return {"logs_size": size, "path": str(logs_dir)}
    except Exception as e:
        return {"error": str(e)[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Otonom ofis durum dashboard")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "launchd": _check_launchd(),
        "processes": _check_processes(),
        "inbox": _check_inbox(),
        "active_state": _check_active_state(),
        "token_stats": _check_token_stats(),
        "p1c_walker": _check_p1c_walker(),
        "disk": _check_disk(),
    }

    if args.json:
        print(json.dumps(snapshot, indent=2, default=str))
        return 0

    # Pretty print
    print(f"=== Otonom Ofis Durum — {snapshot['timestamp']} ===\n")

    print("## launchd")
    if snapshot["launchd"]:
        for j in snapshot["launchd"]:
            if "error" in j:
                print(f"  ERROR: {j['error']}")
            else:
                print(f"  PID={j['pid']:>8s}  status={j['status']:>3s}  {j['label']}")
    else:
        print("  (priceaction launchd job yok — autostart kurulmamış)")

    print("\n## Processes")
    if snapshot["processes"]:
        for p in snapshot["processes"]:
            if "error" in p:
                print(f"  ERROR: {p['error']}")
            else:
                print(f"  PID={p['pid']:>6s}  CPU={p['cpu_pct']:>5s}%  MEM={p['mem_pct']:>5s}%  start={p['start']:>6s}  {p['cmd']}")
    else:
        print("  (futures_daemon / ceo_loop çalışmıyor)")

    print("\n## Inbox (memory/protocol/inbox.jsonl)")
    ib = snapshot["inbox"]
    if "error" in ib:
        print(f"  ERROR: {ib['error']}")
    else:
        print(f"  Total messages: {ib.get('total_messages', 0)}")
        pending = ib.get("pending_per_recipient", {})
        if pending:
            print("  Pending per recipient:")
            for rec, n in sorted(pending.items(), key=lambda x: -x[1]):
                print(f"    {rec:>16s}: {n}")
        else:
            print("  Pending: (none)")

    print("\n## Active State (memory/shared/active_state.md)")
    s = snapshot["active_state"]
    if "error" in s:
        print(f"  ERROR: {s['error']}")
    else:
        print(f"  last_updated: {s.get('last_updated', '?')}")
        print(f"  pending_principal_decisions: {s.get('pending_principal_decisions', 0)}")

    print("\n## Token Stats (Prometheus, son 7g)")
    t = snapshot["token_stats"]
    if "error" in t:
        print(f"  ERROR: {t['error']}")
    elif "status" in t:
        print(f"  {t['status']}")
    else:
        print(f"  Agent-model combos: {t['n_agent_model_combos']}")
        print(f"  Total input tokens: {t['total_input_tokens']:,}")
        print(f"  Total output tokens: {t['total_output_tokens']:,}")
        print(f"  Total cost (kabaca): ${t['total_cost_usd']}")

    print("\n## P1c Walker (5m bot)")
    p = snapshot["p1c_walker"]
    if "error" in p:
        print(f"  ERROR: {p['error']}")
    elif "status" in p:
        print(f"  {p['status']}")
    else:
        print(f"  Equity:       ${p['equity_usdt']:.2f}")
        print(f"  MTD PnL:      {p['mtd_pnl_pct']:+.3f}%")
        print(f"  Trades:       {p['n_trades']} closed, {p['n_open']} open")
        print(f"  Halted:       {p['halted']}" + (f" ({p['halt_reason']})" if p['halted'] else ""))

    print("\n## Disk")
    d = snapshot["disk"]
    if "error" in d:
        print(f"  ERROR: {d['error']}")
    else:
        print(f"  logs/: {d.get('logs_size', '?')}")

    print("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
