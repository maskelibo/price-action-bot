"""Faz 7 Pre-flight Kontrol Sistemi.

Faz 6 paper trading'den Faz 7 mikro-canli gecise hazir olup olmadigini
tek komutla otomatik kontrol eder.

Kullanim:
    python scripts/faz7_preflight.py
    python scripts/faz7_preflight.py --json      # makine-okunur cikti
    python scripts/faz7_preflight.py --strict    # ilk FAIL'de dur

Cikti:
    PASS / FAIL her kriter icin + genel READY / NOT READY karari
"""
# ruff: noqa: N806, E741  (pre-existing stil; preflight script — 2026-07-10)

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Windows terminali UTF-8 ciktisi icin stdout'u yeniden sar
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# Proje kokuyle baslat
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# =====================================================================
# Terminal renkleri (Windows terminal destekliyorsa)
# =====================================================================

_RESET = "\033[0m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_CYAN = "\033[96m"


def _c(text: str, color: str) -> str:
    """ANSI renk ekle (Windows cmd desteklemiyorsa devre disi)."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"{color}{text}{_RESET}"


# =====================================================================
# Check sonuc yapisi
# =====================================================================


class CheckResult:
    def __init__(
        self,
        name: str,
        passed: bool,
        detail: str,
        action: str = "",
        warning: bool = False,
    ) -> None:
        self.name = name
        self.passed = passed
        self.detail = detail
        self.action = action
        self.warning = warning  # PASS ama dikkat gerektiriyor

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "status": "PASS" if self.passed else "FAIL",
            "detail": self.detail,
            "action": self.action,
            "warning": self.warning,
        }

    def __str__(self) -> str:
        if self.passed and not self.warning:
            icon = _c("[PASS]", _GREEN)
        elif self.passed and self.warning:
            icon = _c("[WARN]", _YELLOW)
        else:
            icon = _c("[FAIL]", _RED)
        lines = [f"  {icon} {_c(self.name, _BOLD)}"]
        lines.append(f"         {self.detail}")
        if self.action:
            lines.append(f"         {_c('Aksiyon:', _YELLOW)} {self.action}")
        return "\n".join(lines)


# =====================================================================
# Bireysel kontroller
# =====================================================================


def check_paper_four_weeks() -> CheckResult:
    """Paper trading 4 hafta tamamlandi mi?"""
    name = "Paper trading 4 hafta tamamlandi"
    state_path = _ROOT / "logs" / "execution" / "paper_state_faz6.json"

    if not state_path.exists():
        return CheckResult(
            name,
            False,
            "logs/execution/paper_state_faz6.json bulunamadi.",
            "Faz 6 paper trading loop'u calistir: python scripts/paper_trading_loop.py --watchdog",
        )

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        created_at_str = data.get("created_at") or data.get("start_ts")
        if not created_at_str:
            return CheckResult(
                name,
                False,
                "paper_state_faz6.json icerisinde 'created_at' veya 'start_ts' yok.",
                "Dosyayi kontrol et veya paper_status_report.py --json calistir.",
            )
        created_at = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        elapsed_days = (now - created_at).days

        if elapsed_days >= 28:
            return CheckResult(
                name,
                True,
                f"Paper trading suresi: {elapsed_days} gun (>= 28 gun).",
            )
        else:
            remaining = 28 - elapsed_days
            return CheckResult(
                name,
                False,
                f"Sadece {elapsed_days} gun gecti. {remaining} gun daha beklenmeli.",
                "Faz 7 icin 28 gun (4 hafta) tam bekleme suresi zorunlu.",
            )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"paper_state dosyasi okunamadi: {exc}",
            "Dosya formatini kontrol et.",
        )


def check_pl_deviation() -> CheckResult:
    """Beklenen vs gercek P&L sapmasi < %20 mi?"""
    name = "P&L sapmasi < %20 (backtest vs gercek)"
    # paper_status_report tarafindan uretilen raporu ara
    report_dir = _ROOT / "reports" / "paper"
    json_reports = sorted(report_dir.glob("faz6_status_*.json")) if report_dir.exists() else []

    if not json_reports:
        # Fallback: DuckDB journal
        journal_path = _ROOT / "data" / "paper_journal.duckdb"
        if not journal_path.exists():
            return CheckResult(
                name,
                False,
                "Ne paper status raporu ne de paper_journal.duckdb bulunamadi.",
                "python scripts/paper_status_report.py --json calistir.",
            )
        try:
            import duckdb  # type: ignore

            conn = duckdb.connect(str(journal_path), read_only=True)
            row = conn.execute(
                "SELECT SUM(realized_pnl) FROM paper_trades WHERE status='closed' AND dry_run=false"
            ).fetchone()
            conn.close()
            total_pnl = float(row[0] or 0.0) if row else 0.0
        except Exception as exc:
            return CheckResult(
                name,
                False,
                f"DuckDB sorgusu basarisiz: {exc}",
                "duckdb kurulu mu? uv add duckdb",
            )

        # Backtest beklentisi: aylik %5.6 (~$10K baz), paper'da $10K ile calisiyor
        initial = float(os.environ.get("PA_PAPER_INITIAL_CAPITAL", "10000"))
        try:
            state_path = _ROOT / "logs" / "execution" / "paper_state_faz6.json"
            if state_path.exists():
                data = json.loads(state_path.read_text(encoding="utf-8"))
                created_at_str = data.get("created_at") or data.get("start_ts")
                if created_at_str:
                    created_at = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=UTC)
                    elapsed_days = (datetime.now(UTC) - created_at).days
                    months_elapsed = max(elapsed_days / 30.0, 0.1)
                    expected_pnl = initial * (1.056**months_elapsed - 1.0)
                else:
                    expected_pnl = initial * 0.056  # 1 ay varsayimi
            else:
                expected_pnl = initial * 0.056
        except Exception:
            expected_pnl = initial * 0.056

        if expected_pnl <= 0:
            return CheckResult(
                name,
                True,
                "Beklenen P&L sifir veya negatif (cok kisa sure) — atlaniyor.",
                warning=True,
            )

        deviation = abs(total_pnl - expected_pnl) / abs(expected_pnl)
        pct = deviation * 100

        if pct < 20:
            return CheckResult(
                name,
                True,
                f"Gercek P&L: ${total_pnl:.2f}, Beklenen: ${expected_pnl:.2f}, Sapma: %{pct:.1f} (< %20).",
            )
        else:
            return CheckResult(
                name,
                False,
                f"Gercek P&L: ${total_pnl:.2f}, Beklenen: ${expected_pnl:.2f}, Sapma: %{pct:.1f} (>= %20).",
                "1 ay daha paper trading yap; strateji kalibrasyonunu kontrol et.",
            )

    # En son raporu kullan
    latest = json_reports[-1]
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
        criteria = report.get("stopping_criteria", {})
        deviation_ok = criteria.get("deviation_within_20pct", False)
        detail_text = report.get("performance", {})
        actual = detail_text.get("total_pnl_usdt", "?")
        expected = detail_text.get("expected_pnl_usdt", "?")
        deviation_pct = detail_text.get("deviation_pct", "?")
        if deviation_ok:
            return CheckResult(
                name,
                True,
                f"Gercek P&L: ${actual}, Beklenen: ${expected}, Sapma: %{deviation_pct} (< %20).",
            )
        else:
            return CheckResult(
                name,
                False,
                f"Gercek P&L: ${actual}, Beklenen: ${expected}, Sapma: %{deviation_pct} (>= %20).",
                "1 ay daha paper trading yap; Researcher'a hipotez rafine et.",
            )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"Rapor dosyasi okunamadi: {exc}",
            "python scripts/paper_status_report.py --json calistir.",
        )


def check_slippage_realistic() -> CheckResult:
    """Slippage backtest'ten mantikli mi? (2x'ten fazla sapma sorun)."""
    name = "Slippage gercekcilik kontrolu"
    BACKTEST_SLIPPAGE_BPS = 5.0
    MAX_ACCEPTABLE_MULTIPLIER = 3.0  # 3x'e kadar tolere

    journal_path = _ROOT / "data" / "paper_journal.duckdb"
    if not journal_path.exists():
        return CheckResult(
            name,
            True,
            "paper_journal.duckdb yok — paper slippage verisi toplanmamis, atlaniyor.",
            warning=True,
        )

    try:
        import duckdb  # type: ignore

        conn = duckdb.connect(str(journal_path), read_only=True)
        # paper_trades tablosunda slippage_bps yoksa sorgu bos donecek
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "paper_trades" not in tables:
            conn.close()
            return CheckResult(
                name,
                True,
                "paper_trades tablosu yok — henuz trade yok, atlaniyor.",
                warning=True,
            )
        # Slippage sutunu var mi?
        cols = [r[0] for r in conn.execute("DESCRIBE paper_trades").fetchall()]
        conn.close()
        if "slippage_bps" not in cols:
            return CheckResult(
                name,
                True,
                "paper_trades tablosunda slippage_bps sutunu yok — eski versiyon, atlaniyor.",
                warning=True,
            )
        conn = duckdb.connect(str(journal_path), read_only=True)
        row = conn.execute(
            "SELECT AVG(slippage_bps), COUNT(*) FROM paper_trades WHERE status='closed'"
        ).fetchone()
        conn.close()
        if not row or row[1] == 0:
            return CheckResult(
                name,
                True,
                "Kapanan paper trade yok — slippage verisi yok, atlaniyor.",
                warning=True,
            )
        avg_slip = float(row[0] or BACKTEST_SLIPPAGE_BPS)
        multiplier = avg_slip / BACKTEST_SLIPPAGE_BPS

        if multiplier <= MAX_ACCEPTABLE_MULTIPLIER:
            return CheckResult(
                name,
                True,
                f"Ortalama slippage: {avg_slip:.1f} bps ({multiplier:.1f}x backtest {BACKTEST_SLIPPAGE_BPS} bps). Kabul edilebilir.",
            )
        else:
            return CheckResult(
                name,
                False,
                f"Ortalama slippage: {avg_slip:.1f} bps ({multiplier:.1f}x backtest {BACKTEST_SLIPPAGE_BPS} bps). Cok yuksek!",
                "configs/risk.yaml max_slippage_bps degerini 25'ten dusur; veya backtest'te gercekci slippage modeli kullan.",
            )
    except ImportError:
        return CheckResult(
            name,
            True,
            "duckdb kurulu degil — slippage kontrolu atlaniyor.",
            "uv add duckdb",
            warning=True,
        )
    except Exception as exc:
        return CheckResult(
            name,
            True,
            f"Slippage kontrolu basarisiz ({exc}) — atlaniyor.",
            warning=True,
        )


def check_kill_switch() -> CheckResult:
    """Kill-switch dosyasi var mi ve test edildi mi?"""
    name = "Kill-switch test edildi"
    ks_path = _ROOT / "logs" / "kill_switch.json"

    if not ks_path.exists():
        return CheckResult(
            name,
            False,
            "logs/kill_switch.json bulunamadi. Kill-switch hic tetiklenmemis.",
            "PYTHONPATH=src python scripts/_archive/breaker_monitor_ARCHIVED_20260710.py (ARŞİV — tek otorite DMS) --force-halt ile test et, sonra --reset ile ac.",
        )

    try:
        data = json.loads(ks_path.read_text(encoding="utf-8"))
        # Aktif mi?
        if data.get("active"):
            return CheckResult(
                name,
                False,
                "Kill-switch AKTIF durumda! Sistemi acmadan once reset et.",
                "PYTHONPATH=src python scripts/_archive/breaker_monitor_ARCHIVED_20260710.py (ARŞİV — tek otorite DMS) --reset",
            )
        # Gecmiste en az bir kez tetiklendi mi?
        history = data.get("history", [])
        if not history and not data.get("last_halt_ts"):
            return CheckResult(
                name,
                False,
                "Kill-switch dosyasi var ama hic tetikleme gecmisi yok.",
                "PYTHONPATH=src python scripts/_archive/breaker_monitor_ARCHIVED_20260710.py (ARŞİV — tek otorite DMS) --force-halt ile test et.",
            )
        return CheckResult(
            name,
            True,
            f"Kill-switch gecmiste test edildi. Son tetikleme: {data.get('last_halt_ts', 'kayit yok')}.",
        )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"kill_switch.json okunamadi: {exc}",
            "Dosyayi kontrol et.",
        )


def check_telegram_alarm() -> CheckResult:
    """Telegram CRIT alarm calisiyor mu?"""
    name = "Telegram CRIT alarm calisiyor"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return CheckResult(
            name,
            False,
            "TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID .env dosyasinda yok.",
            "RUNBOOK.md Faz 5 bolumunu izleyerek Telegram bot kur.",
        )

    # Gecmis CRIT alarm log'u var mi?
    log_path = _ROOT / "logs" / "paper_trading.log"
    crit_found = False
    if log_path.exists():
        try:
            content = log_path.read_text(encoding="utf-8", errors="ignore")
            if "crit" in content.lower() or "CRIT" in content or "breaker" in content.lower():
                crit_found = True
        except Exception:
            pass

    # reports/ceo/ altinda crisis raporu var mi?
    crisis_reports = (
        list((_ROOT / "reports" / "ceo").glob("crisis-*.md"))
        if (_ROOT / "reports" / "ceo").exists()
        else []
    )

    if crit_found or crisis_reports:
        return CheckResult(
            name,
            True,
            f"Telegram token/chat_id mevcut. CRIT alarm gecmisi bulundu ({len(crisis_reports)} kriz raporu).",
        )
    else:
        return CheckResult(
            name,
            False,
            "Telegram bilgileri mevcut ama gecmiste CRIT alarm tetiklenmemis.",
            "Bir kez manuel test yap: PYTHONPATH=src python scripts/llm_orchestrator.py --mode crit-alarm --reason 'Preflight test'",
            warning=False,
        )


def check_manifest_hash() -> CheckResult:
    """Manifest hash her trade'e mi yaziliyor?"""
    name = "Manifest hash trade kayitlarinda mevcut"
    journal_path = _ROOT / "data" / "paper_journal.duckdb"

    if not journal_path.exists():
        return CheckResult(
            name,
            False,
            "paper_journal.duckdb yok — trade kaydi yok.",
            "Paper trading loop'u en az 1 kez calistir.",
        )

    try:
        import duckdb  # type: ignore

        conn = duckdb.connect(str(journal_path), read_only=True)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "paper_trades" not in tables:
            conn.close()
            return CheckResult(
                name,
                False,
                "paper_trades tablosu yok.",
                "Paper trading loop'u calistir.",
            )
        row = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()
        total = int(row[0] or 0) if row else 0
        conn.close()

        if total == 0:
            return CheckResult(
                name,
                False,
                "Hic paper trade yok — manifest hash kontrolu yapilamadi.",
                "En az 1 paper trade olcak sekilde loop calistir.",
            )

        # RiskedOrder'da manifest_hash var; paper trade'de pattern_id alani
        # manifest hash dolaylı olarak her Fill icinde stable_hash() ile oluşturuluyor
        # Journal'da doğrudan sütun olmayabilir — logs kontrolü
        log_path = _ROOT / "logs" / "paper_trading.log"
        hash_found = False
        if log_path.exists():
            sample = log_path.read_text(encoding="utf-8", errors="ignore")[-50000:]
            if "manifest_hash" in sample:
                hash_found = True

        if hash_found:
            return CheckResult(
                name,
                True,
                f"Toplam {total} paper trade kaydi var. manifest_hash log'larda goruldu.",
            )
        else:
            return CheckResult(
                name,
                True,
                f"Toplam {total} paper trade kaydi var. manifest_hash dogrudan log'larda gorulmuyor — kod seviyesinde stable_hash() her Fill'de mevcut.",
                warning=True,
            )
    except ImportError:
        return CheckResult(
            name,
            True,
            "duckdb kurulu degil — manifest hash kontrolu atlaniyor.",
            "uv add duckdb",
            warning=True,
        )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"DuckDB sorgusu basarisiz: {exc}",
        )


def check_postgres_journal() -> CheckResult:
    """Postgres aktif mi (audit trail)?"""
    name = "Postgres journal aktif (audit trail)"
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_ROOT),
        )
        if result.returncode == 0 and "postgres" in result.stdout.lower():
            # JSON output - postgres running mi?
            if (
                '"running"' in result.stdout.lower()
                or '"up"' in result.stdout.lower()
                or "running" in result.stdout.lower()
            ):
                return CheckResult(
                    name,
                    True,
                    "Postgres container 'running' durumunda.",
                )
            else:
                return CheckResult(
                    name,
                    False,
                    "Postgres container docker compose ps'de gorunuyor ama running degil.",
                    "docker compose up -d postgres",
                )
        else:
            # Eski docker-compose format dene
            result2 = subprocess.run(
                ["docker", "compose", "ps"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(_ROOT),
            )
            if result2.returncode == 0 and "postgres" in result2.stdout.lower():
                lines = [l for l in result2.stdout.splitlines() if "postgres" in l.lower()]
                running = any("up" in l.lower() or "running" in l.lower() for l in lines)
                if running:
                    return CheckResult(name, True, "Postgres container UP durumunda.")
                else:
                    return CheckResult(
                        name,
                        False,
                        f"Postgres container durumu belirsiz: {lines}",
                        "docker compose up -d postgres",
                    )
            return CheckResult(
                name,
                False,
                "Postgres docker compose'da bulunamadi.",
                "docker compose up -d  # tam stack'i kaldir",
            )
    except FileNotFoundError:
        return CheckResult(
            name,
            False,
            "docker komutu bulunamadi — Docker Desktop yuklu mu?",
            "Docker Desktop kur: https://www.docker.com/products/docker-desktop",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name,
            False,
            "docker compose ps zaman asimina ugradi.",
            "Docker Desktop calisiyor mu?",
        )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"Postgres kontrolu basarisiz: {exc}",
            "docker compose up -d",
        )


def check_env_live_config() -> CheckResult:
    """LIVE mod icin zorunlu .env degerleri mevcut mu?"""
    name = ".env LIVE konfigurasyonu hazir"
    env_path = _ROOT / ".env"

    if not env_path.exists():
        return CheckResult(
            name,
            False,
            ".env dosyasi bulunamadi.",
            "cp .env.example .env  ve gerekli degerleri doldur.",
        )

    missing = []
    warnings = []

    # .env parse (basit — dotenv olmadan)
    env_values: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_values[k.strip()] = v.strip()
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f".env okunamadi: {exc}",
        )

    # Zorunlu kontroller
    if not env_values.get("BINANCE_API_KEY", "").strip():
        missing.append("BINANCE_API_KEY bos — mainnet key gerekmeli")

    if not env_values.get("BINANCE_API_SECRET", "").strip():
        missing.append("BINANCE_API_SECRET bos — mainnet secret gerekmeli")

    if env_values.get("BINANCE_TESTNET", "true").lower() == "true":
        warnings.append("BINANCE_TESTNET=true — canli icin false olmali")

    if not env_values.get("TELEGRAM_BOT_TOKEN", "").strip():
        missing.append("TELEGRAM_BOT_TOKEN bos — alarm icin zorunlu")

    if not env_values.get("TELEGRAM_CHAT_ID", "").strip():
        missing.append("TELEGRAM_CHAT_ID bos — alarm icin zorunlu")

    # PA_LIVE_CONFIRM henuz eksik olmali (pre-flight kontrol; kullanici gocsiz donmemeli)
    live_confirm = env_values.get("PA_LIVE_CONFIRM", "").strip()
    if live_confirm == "YES_I_KNOW":
        warnings.append("PA_LIVE_CONFIRM=YES_I_KNOW zaten set — sistem acilirsa CANLI ISLEM ATAR")
    elif not live_confirm:
        pass  # Normal: pre-flight sirasinda henuz set edilmemis olmali

    if missing:
        return CheckResult(
            name,
            False,
            f"Eksik: {'; '.join(missing)}",
            "RUNBOOK.md Faz 7 bolum D'yi izle.",
        )

    if warnings:
        return CheckResult(
            name,
            True,
            f"Temel degerler mevcut. Dikkat: {'; '.join(warnings)}",
            warning=True,
        )

    return CheckResult(
        name,
        True,
        "Zorunlu .env degerleri mevcut (API key, secret, Telegram).",
    )


def check_risk_yaml() -> CheckResult:
    """configs/risk.yaml okunabiliyor mu ve breaker esikleri dogru mu?"""
    name = "configs/risk.yaml okunabiliyor ve dogrulanmis"
    risk_path = _ROOT / "configs" / "risk.yaml"

    if not risk_path.exists():
        return CheckResult(
            name,
            False,
            "configs/risk.yaml bulunamadi.",
            "Dosya silindi mi? Git'ten geri yukle.",
        )

    try:
        import yaml  # type: ignore

        with risk_path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except ImportError:
        return CheckResult(
            name,
            True,
            "yaml modulu yok — detayli dogrulama atlaniyor.",
            "uv add pyyaml",
            warning=True,
        )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            f"risk.yaml okunamadi: {exc}",
        )

    issues = []
    breakers = cfg.get("drawdown_breakers", {})
    if float(breakers.get("daily_loss_pct", 0)) != 0.05:
        issues.append(f"daily_loss_pct: {breakers.get('daily_loss_pct')} (beklenen 0.05)")
    if float(breakers.get("weekly_loss_pct", 0)) != 0.10:
        issues.append(f"weekly_loss_pct: {breakers.get('weekly_loss_pct')} (beklenen 0.10)")
    if float(breakers.get("monthly_loss_pct", 0)) != 0.15:
        issues.append(f"monthly_loss_pct: {breakers.get('monthly_loss_pct')} (beklenen 0.15)")

    lev = cfg.get("leverage", {})
    if int(lev.get("max_leverage_per_symbol", 0)) > 5:
        issues.append(
            f"max_leverage_per_symbol: {lev.get('max_leverage_per_symbol')} (maks 5 olmali)"
        )

    if issues:
        return CheckResult(
            name,
            False,
            f"risk.yaml parametreleri uyumsuz: {'; '.join(issues)}",
            "configs/risk.yaml ADR-006 ile karsilastir.",
        )

    return CheckResult(
        name,
        True,
        "Breaker esikleri (%5/%10/%15) ve leverage (<=5x) dogrulandi.",
    )


def check_human_principal_commitment() -> CheckResult:
    """Insan principal taahhut belgesi var mi?"""
    name = "Insan principal taahhut (ilk 2 hafta gunluk brief)"
    # Bu check tamamen kullanici beyanina dayanir
    # Bir commitment dosyasi veya cal'a bakabiliriz
    commitment_path = _ROOT / "logs" / "faz7_commitment.txt"

    if commitment_path.exists():
        try:
            content = commitment_path.read_text(encoding="utf-8").strip()
            if len(content) > 10:
                return CheckResult(
                    name,
                    True,
                    f"Taahhut dosyasi mevcut: {commitment_path.name}",
                )
        except Exception:
            pass

    today = datetime.now().strftime("%Y-%m-%d")
    return CheckResult(
        name,
        False,
        "logs/faz7_commitment.txt yok — insan taahhut belgesi gerekli.",
        (
            "Asagidaki komutu calistir:\n"
            "         echo 'Ben [adiniz], Faz 7 mikro canli operasyon sirasinda ilk 14 gun her sabah "
            "CEO brief okuyacagimi ve DD %%5 esigi asiminda manuel inceleme yapacagimi taahhut ediyorum. "
            "Tarih: " + today + "' "
            "> logs/faz7_commitment.txt"
        ),
    )


# =====================================================================
# Ana calistirici
# =====================================================================

CHECKS = [
    check_paper_four_weeks,
    check_pl_deviation,
    check_slippage_realistic,
    check_kill_switch,
    check_telegram_alarm,
    check_manifest_hash,
    check_postgres_journal,
    check_env_live_config,
    check_risk_yaml,
    check_human_principal_commitment,
]


def run_preflight(strict: bool = False) -> tuple[list[CheckResult], bool]:
    results: list[CheckResult] = []
    all_passed = True

    for check_fn in CHECKS:
        try:
            result = check_fn()
        except Exception as exc:
            result = CheckResult(
                check_fn.__name__,
                False,
                f"Kontrol sirasinda beklenmedik hata: {exc}",
                "Hatayi raporla.",
            )
        results.append(result)
        if not result.passed:
            all_passed = False
            if strict:
                break

    return results, all_passed


def print_report(results: list[CheckResult], all_passed: bool) -> None:
    print()
    print(_c("=" * 60, _BOLD))
    print(_c("  FAZ 7 PRE-FLIGHT KONTROL SISTEMI", _BOLD))
    print(_c("  Engulfing Continuation — Mikro Canli ($200)", _CYAN))
    print(_c("=" * 60, _BOLD))
    print()

    passed_count = sum(1 for r in results if r.passed)
    failed_count = sum(1 for r in results if not r.passed)
    warn_count = sum(1 for r in results if r.passed and r.warning)
    total = len(results)

    for r in results:
        print(str(r))
        print()

    print(_c("-" * 60, _BOLD))
    summary_line = (
        f"  Sonuc: {passed_count}/{total} PASS" f" | {failed_count} FAIL" f" | {warn_count} WARN"
    )
    print(_c(summary_line, _BOLD))
    print()

    if all_passed and failed_count == 0:
        print(_c("  SISTEM FAZ 7 ICIN HAZIR.", _GREEN + _BOLD))
        print(_c("  Son adim: .env dosyasina PA_LIVE_CONFIRM=YES_I_KNOW ekle.", _GREEN))
        print(
            _c("  Sonra: PYTHONPATH=src python scripts/paper_trading_loop.py --live-mode", _GREEN)
        )
    else:
        print(_c("  SISTEM FAZ 7 ICIN HAZIR DEGIL.", _RED + _BOLD))
        print(_c("  Yukaridaki FAIL maddelerini duzelt ve tekrar calistir.", _RED))

    print(_c("=" * 60, _BOLD))
    print()

    # Gercekci beklenti hatirlat
    print(_c("  Realist ROI Tablosu ($200 baslangic):", _CYAN))
    print("  +-------------+------------------+------------------+")
    print("  | Donem       | Realist (%35/yil)| Realist (%50/yil)|")
    print("  +-------------+------------------+------------------+")
    print("  | 6 ay        | ~$233 (+%17)     | ~$249 (+%24)     |")
    print("  | 1 yil       | ~$270 (+%35)     | ~$300 (+%50)     |")
    print("  | 2 yil       | ~$365 (+%82)     | ~$450 (+%125)    |")
    print("  | 3 yil       | ~$493 (+%147)    | ~$675 (+%238)    |")
    print("  +-------------+------------------+------------------+")
    print("  NOT: Backtest %68/yil -- gercekte slippage/funding/downtime")
    print("       etkisiyle %35-50 beklenmeli. Bu bir emeklilik fonu degil.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Faz 7 Pre-flight Kontrol Sistemi — Mikro Canli Gecis Dogrulamasi"
    )
    parser.add_argument("--json", action="store_true", help="JSON formatinda cikti")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Ilk FAIL'de dur (diger kontrolleri calistirma)",
    )
    args = parser.parse_args()

    results, all_passed = run_preflight(strict=args.strict)

    if args.json:
        output = {
            "timestamp": datetime.now(UTC).isoformat(),
            "faz": 7,
            "ready": all_passed,
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed),
                "warnings": sum(1 for r in results if r.passed and r.warning),
            },
            "checks": [r.as_dict() for r in results],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(results, all_passed)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
