"""Daily Truth Report (Faz 14.4).

Her sabah 03:00 UTC çalışır. Sistemin gerçek durumunu aggregate eder:
- Her bot hangi config'i yüklü? (provenance)
- Config drift var mı? (git HEAD vs disk)
- Promise/Reality ihlal sayısı (son 24h)
- Cron job execution rates
- Açık pozisyonlar + 24h PnL
- Son 24h Telegram alert sayısı
- Son commit'ler (24h)

Çıktı: reports/truth/truth-YYYY-MM-DD.md + Telegram (kısa özet).

Bu rapor varsa hatalar gizlenemez — sen sabah 1 mesaj okur ve sistem
gerçek aynaya kavuşur.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO = Path(__file__).resolve().parent.parent
_REPORT_DIR = _REPO / "reports" / "truth"


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _git_run(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# scripts/futures_daemon_v14.py:_PHASE_CONFIGS ile senkron tutulmalı.
# Yeni faz deploy edilirse buraya da eklenmeli — yoksa rapor FAIL LOUD eder
# (sessizce eski/yanlış config göstermez).
_PHASE_TO_CONFIG = {
    "v15p2": "configs/risk_phoenix_scalp_15m_v15p2.yaml",
}


def gather_bot_configs() -> list[dict[str, Any]]:
    """Aktif bot (v15p2 daemon) için provenance bilgisi.

    FIX 2026-07-06: eski hali emekli botları (futures15m 15 Haz, futures5m
    30 Haz) sorguluyordu ve retired default config gösteriyordu — truth report
    "ayna" olduğu halde yanlış config/risk raporluyordu. Aktif faz, launchd
    wrapper'daki PA_V14_PHASE'ten okunur (deploy'un kaynağı orası).
    """
    from price_action.ops.provenance import config_provenance

    bots: list[dict[str, Any]] = []
    wrapper = _REPO / "ops" / "launchd" / "run_futures_v15p2.sh"
    try:
        phase = None
        for line in wrapper.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export PA_V14_PHASE="):
                phase = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        if phase is None:
            raise ValueError(f"PA_V14_PHASE bulunamadı: {wrapper}")
        cfg_rel = _PHASE_TO_CONFIG.get(phase)
        if cfg_rel is None:
            raise ValueError(f"faz {phase!r} _PHASE_TO_CONFIG'de yok — truth_report.py güncelle")
        prov = config_provenance(_REPO / cfg_rel)
        prov["bot"] = f"futures15m ({phase})"
        bots.append(prov)
    except Exception as exc:
        bots.append({"bot": "futures15m (v15p2)", "error": str(exc)[:200]})
    return bots


def gather_config_drift() -> list[str]:
    """git diff configs/ — değişen ama commit edilmemiş dosyalar."""
    out = _git_run(["diff", "--name-only", "HEAD", "--", "configs/"])
    return out.splitlines() if out else []


def gather_recent_commits(hours: int = 24) -> list[str]:
    """Son N saatte yapılan commit özetleri."""
    since = f"{hours}.hours.ago"
    out = _git_run(["log", f"--since={since}", "--oneline", "-20"])
    return out.splitlines() if out else []


def gather_promise_violations() -> dict[str, Any]:
    """En son promise check raporunu oku."""
    report_dir = _REPO / "reports" / "promises"
    if not report_dir.exists():
        return {"latest": None, "summary": "promise check henüz çalışmamış"}
    files = sorted(report_dir.glob("promises-*.md"), reverse=True)
    if not files:
        return {"latest": None, "summary": "rapor yok"}
    latest = files[0]
    try:
        body = latest.read_text(encoding="utf-8")
        # "Toplam ihlal: N" satırını parse et
        for line in body.splitlines():
            if "Toplam ihlal" in line:
                return {"latest": latest.name, "summary": line.strip("* ").strip()}
        return {"latest": latest.name, "summary": "ihlal sayısı parse edilemedi"}
    except Exception as exc:
        return {"latest": latest.name, "summary": f"read fail: {exc}"}


def gather_position_status() -> dict[str, Any]:
    """Journal'dan açık pozisyon + 24h PnL."""
    out: dict[str, Any] = {"open_positions": [], "pnl_24h": 0.0, "trades_24h": 0}
    # FIX 2026-07-06: eski futures_journal.duckdb v14-öncesi dönemin journal'ı —
    # içindeki stale 'filled' kayıtlar (örn NEAR short) açık pozisyon gibi
    # görünüyordu. Aktif bot v15p2'nin journal'ı ayrı dosya.
    journal = _REPO / "data" / "futures_journal_v15p2.duckdb"
    if not journal.exists():
        return out
    try:
        import duckdb

        con = duckdb.connect(str(journal), read_only=True)
        try:
            # Açık pozisyonlar (signals.status=filled & trade_id trades_closed'te yok)
            df_open = con.execute("""
                SELECT s.symbol, s.side, s.strategy, s.fill_price, s.fill_qty,
                       s.notional_usdt, s.leverage
                  FROM futures_signals s
                 WHERE s.status = 'filled'
                   AND s.signal_id NOT IN (SELECT trade_id FROM futures_trades_closed)
                 ORDER BY s.ts DESC
            """).fetchdf()
            for _, r in df_open.iterrows():
                out["open_positions"].append(
                    {
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "strategy": r["strategy"],
                        "entry": float(r["fill_price"]),
                        "qty": float(r["fill_qty"]),
                        "notional": float(r["notional_usdt"]),
                        "lev": int(r["leverage"]),
                    }
                )
            # 24h closed PnL
            df_closed = con.execute("""
                SELECT SUM(realized_pnl_usdt) AS pnl, COUNT(*) AS n
                  FROM futures_trades_closed
                 WHERE ts_close >= now() - INTERVAL '24 hours'
            """).fetchone()
            if df_closed:
                out["pnl_24h"] = float(df_closed[0] or 0.0)
                out["trades_24h"] = int(df_closed[1] or 0)
        finally:
            con.close()
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


def gather_recent_critical_alerts(hours: int = 24) -> list[str]:
    """app.log'dan son N saatlik push_critical mesajlarını çek."""
    log = _REPO / "logs" / "app.log"
    if not log.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    alerts: list[str] = []
    try:
        with log.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "telegram.sent" not in line and "push_critical" not in line:
                    continue
                if '"level": "CRIT"' not in line and "CRIT" not in line:
                    continue
                # Basit timestamp parse (loguru format)
                try:
                    rec = json.loads(line)
                    ts_str = rec.get("ts")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)
                        if ts >= cutoff:
                            preview = (
                                rec.get("extra", {})
                                .get("extra", {})
                                .get("message_preview", "")[:100]
                            )
                            alerts.append(f"{ts.strftime('%H:%M')} {preview}")
                except Exception:
                    continue
    except Exception:
        pass
    return alerts[:20]


def build_report() -> str:
    """Markdown rapor üret."""
    now = datetime.now(UTC)
    lines = [
        f"# 🪞 Truth Report — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "**Sistem aynası**: her komponentin gerçekte ne yaptığını gösterir.",
        "",
    ]

    # ── 1. Bot Configs (Provenance) ──────────────────────────────
    lines.append("## 1️⃣ Bot Configs (Aktif)")
    lines.append("")
    bots = gather_bot_configs()
    for b in bots:
        if "error" in b:
            lines.append(f"- ❌ **{b['bot']}**: {b['error']}")
            continue
        wide_ok = float(b.get("sl_pct_min") or 0) >= 0.025
        wide_str = "✅ WIDESTOP" if wide_ok else "❌ no widestop"
        lines.append(
            f"- **{b['bot']}**: `{b.get('name','?')}` "
            f"(sha={b.get('sha256_short','?')}) — {wide_str}"
        )
        lines.append(
            f"  - risk={b.get('risk_per_trade','?')}, "
            f"sl_pct_min={b.get('sl_pct_min','?')}, "
            f"lev={b.get('leverage_max','?')}x, "
            f"pyramid={'AÇIK' if b.get('pyramid_enabled') else 'KAPALI'}"
        )
        if b.get("backtest_summary"):
            lines.append(
                f"  - backtest_header: {b['backtest_summary'][0][:100] if b['backtest_summary'] else 'n/a'}"
            )
    lines.append("")

    # ── 2. Config Drift (git) ────────────────────────────────────
    lines.append("## 2️⃣ Config Drift (git HEAD vs disk)")
    drift = gather_config_drift()
    if drift:
        lines.append(f"⚠️ {len(drift)} dosya değişmiş ama commit edilmemiş:")
        for f in drift[:10]:
            lines.append(f"- `{f}`")
    else:
        lines.append("✅ Tüm config'ler git ile senkron.")
    lines.append("")

    # ── 3. Promise Violations ────────────────────────────────────
    lines.append("## 3️⃣ Promise/Reality Check (son saat)")
    pv = gather_promise_violations()
    lines.append(f"- Son rapor: `{pv.get('latest', '—')}`")
    lines.append(f"- {pv.get('summary', '—')}")
    lines.append("")

    # ── 4. Pozisyonlar ───────────────────────────────────────────
    lines.append("## 4️⃣ Pozisyon Durumu (24h)")
    pos = gather_position_status()
    lines.append(f"- Açık pozisyon: **{len(pos['open_positions'])}**")
    for p in pos["open_positions"][:8]:
        lines.append(
            f"  - {p['symbol']} {p['side']} ({p['strategy']}) "
            f"@${p['entry']:.4f} qty={p['qty']:.4f} notional=${p['notional']:.0f}"
        )
    lines.append(
        f"- 24h realized PnL: **${pos.get('pnl_24h', 0):.2f}** ({pos.get('trades_24h', 0)} trade)"
    )
    lines.append("")

    # ── 5. Recent Critical Alerts ────────────────────────────────
    lines.append("## 5️⃣ Son 24h CRIT Alert'ler")
    alerts = gather_recent_critical_alerts(hours=24)
    if alerts:
        for a in alerts:
            lines.append(f"- {a}")
    else:
        lines.append("✅ Hiç CRIT alert yok.")
    lines.append("")

    # ── 6. Recent Commits ────────────────────────────────────────
    lines.append("## 6️⃣ Son 24h Commit'ler")
    commits = gather_recent_commits(hours=24)
    if commits:
        for c in commits[:15]:
            lines.append(f"- `{c}`")
    else:
        lines.append("(commit yok)")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    body = build_report()
    path = _REPORT_DIR / f"truth-{now.strftime('%Y-%m-%d')}.md"
    path.write_text(body, encoding="utf-8")
    _log(f"Truth report written: {path.name}")

    # Telegram push (kısa özet — full body Telegram'a sığmaz, sadece headlines)
    try:
        from price_action.orchestrator.notifications import push_report

        push_report(
            path, level="INFO", caption="Daily Truth Report", alert_type="truth_report_daily"
        )
    except Exception as exc:
        _log(f"telegram_push_fail: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
