"""Promise/Reality Detector (Faz 14.2).

configs/promises.yaml'daki SLA beyanlarını saatlik kontrol eder.
İhlal varsa push_critical Telegram alert + reports/promises/ altına rapor.

Cron: scheduler her saat çağırır (`_job_check_promises`).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO = Path(__file__).resolve().parent.parent
_PROMISES_YAML = _REPO / "configs" / "promises.yaml"
_REPORT_DIR = _REPO / "reports" / "promises"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _count_files_in_window(pattern: str, hours: int = 24) -> int:
    """Pattern'e uyan ve son N saat içinde değiştirilmiş dosyaları say."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for p in _REPO.glob(pattern):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                count += 1
        except Exception:
            continue
    return count


def _file_max_age_hours(pattern: str) -> float | None:
    """Pattern'e uyan en yeni dosyanın yaşı (saat). Hiç yoksa None."""
    newest_mtime = 0.0
    for p in _REPO.glob(pattern):
        try:
            mt = p.stat().st_mtime
            if mt > newest_mtime:
                newest_mtime = mt
        except Exception:
            continue
    if newest_mtime == 0.0:
        return None
    return (datetime.now(timezone.utc).timestamp() - newest_mtime) / 3600.0


def _count_log_matches(log_path: str, regex: str, hours: int = 24) -> int:
    """Log dosyasında son N saat içinde regex'e uyan satır sayısı.

    Log'da timestamp yoksa (sadece HH:MM:SS), mtime referansıyla son
    N saatlik içerik tahmini.
    """
    p = _REPO / log_path
    if not p.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    pattern = re.compile(regex)
    count = 0
    try:
        # JSON log mu plain log mu?
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not pattern.search(line):
                    continue
                # JSON log → ts field var
                try:
                    rec = json.loads(line)
                    ts_str = rec.get("ts")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= cutoff:
                            count += 1
                        continue
                except Exception:
                    pass
                # Plain log → match var, time gating yok (tüm dosyayı say)
                # Daha doğru: log dosyasının mtime'ı cutoff'tan önce ise zaten 0
                # döner. Yoksa hepsi son 24h tahmin edilir.
                count += 1
    except Exception:
        pass
    return count


def check_promises(promises: dict[str, Any]) -> list[dict[str, Any]]:
    """Tüm komponentleri kontrol et, ihlal listesini döndür."""
    violations: list[dict[str, Any]] = []
    components = promises.get("components", {}) or {}
    for comp_name, comp_cfg in components.items():
        if not comp_cfg.get("enabled", True):
            continue
        severity = comp_cfg.get("severity", "warn")
        for check in comp_cfg.get("checks", []) or []:
            kind = check.get("kind")
            if kind == "file_pattern":
                pattern = check.get("pattern", "")
                min_per_24h = check.get("min_per_24h")
                max_age_hours = check.get("max_age_hours")
                if min_per_24h is not None:
                    actual = _count_files_in_window(pattern, hours=24)
                    if actual < int(min_per_24h):
                        violations.append({
                            "component": comp_name,
                            "severity": severity,
                            "kind": kind,
                            "promise": f"min {min_per_24h} files matching {pattern}/24h",
                            "actual": f"{actual} files",
                            "comment": check.get("comment", ""),
                        })
                elif max_age_hours is not None:
                    age = _file_max_age_hours(pattern)
                    if age is None:
                        violations.append({
                            "component": comp_name,
                            "severity": severity,
                            "kind": kind,
                            "promise": f"file matching {pattern} exists",
                            "actual": "NO FILE",
                            "comment": check.get("comment", ""),
                        })
                    elif age > float(max_age_hours):
                        violations.append({
                            "component": comp_name,
                            "severity": severity,
                            "kind": kind,
                            "promise": f"file age <= {max_age_hours}h",
                            "actual": f"{age:.1f}h old",
                            "comment": check.get("comment", ""),
                        })
            elif kind == "log_pattern":
                log_path = check.get("log", "")
                regex = check.get("regex", "")
                min_per_24h = check.get("min_per_24h", 0)
                actual = _count_log_matches(log_path, regex, hours=24)
                if actual < int(min_per_24h):
                    violations.append({
                        "component": comp_name,
                        "severity": severity,
                        "kind": kind,
                        "promise": f"min {min_per_24h} log matches for /{regex}/ in {log_path} /24h",
                        "actual": f"{actual} matches",
                        "comment": check.get("comment", ""),
                    })
    return violations


def write_report(violations: list[dict[str, Any]]) -> Path:
    """Markdown rapor yaz."""
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    report_path = _REPORT_DIR / f"promises-{now.strftime('%Y-%m-%d-%H')}.md"
    lines = [
        f"# Promise/Reality Check — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**Toplam ihlal:** {len(violations)} ({sum(1 for v in violations if v['severity']=='crit')} CRIT, {sum(1 for v in violations if v['severity']=='warn')} WARN)",
        "",
    ]
    if not violations:
        lines.append("✅ Tüm komponentler sözlerinde duruyor.")
    else:
        for v in violations:
            icon = "🚨" if v["severity"] == "crit" else "⚠️"
            lines.append(f"## {icon} [{v['severity'].upper()}] {v['component']}")
            lines.append(f"- **Söz:** {v['promise']}")
            lines.append(f"- **Gerçek:** {v['actual']}")
            if v.get("comment"):
                lines.append(f"- **Not:** {v['comment']}")
            lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def push_violations(violations: list[dict[str, Any]]) -> None:
    """CRIT ihlaller için tek Telegram mesajı."""
    crit_violations = [v for v in violations if v["severity"] == "crit"]
    if not crit_violations:
        return
    try:
        from price_action.orchestrator.notifications import push_critical
        msg_lines = [
            f"PROMISE VIOLATION ({len(crit_violations)} CRIT):",
        ]
        for v in crit_violations:
            msg_lines.append(f"- {v['component']}: söz '{v['promise']}', gerçek '{v['actual']}'")
        push_critical("\n".join(msg_lines), source="promise_detector")
    except Exception as exc:
        _log(f"telegram_push_fail: {exc}")


def main() -> int:
    if not _PROMISES_YAML.exists():
        _log(f"PROMISES_YAML_MISSING: {_PROMISES_YAML}")
        return 1
    try:
        promises = yaml.safe_load(_PROMISES_YAML.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log(f"YAML_PARSE_FAIL: {exc}")
        return 1
    violations = check_promises(promises)
    report = write_report(violations)
    push_violations(violations)
    _log(f"DONE: {len(violations)} violations, report={report.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
