"""AuditOpsAgent — Ops & Control-Environment denetçisi (3. hat).

"Auditor of the 2nd line": gözetim katmanının KENDİSİNİ denetler — scheduler cron
sağlığı, notifications/mute durumu, token_budget, freshness/promise/stuck guard'ları,
ve 2. hat ajanlarının (risk_officer/adversary/bot_monitor) gerçekten koşup koşmadığı.

Archetype: SRE error-budget / alert-fatigue (SNR + mute drift) + James Reason
"Swiss-cheese" (hizalanan delikler) + IIA control self-assessment (kontrolün varlığı
≠ çalışması).

Kontrol-testleri:
  CT-OPS-01  alarm mute drift / kör-nokta (bu seansın mute bug'ı): paper için
             susturulan alarmlar canlıya geçişte / kök-neden çözüldükten sonra
             hâlâ mute mu?
  CT-OPS-02  silent cron — beklenen pencerede koşmamış job (öngörü).
"""

from __future__ import annotations

from typing import Any, ClassVar

from price_action.logging_config import logger

from .audit_base import SKIP, AuditAgentBase, Finding

_OWNER = "ops_engineer"


def ct_ops_01_mute_drift(
    muted_alert_prefixes: list[str],
    muted_crit_sources: list[str],
    *,
    run_mode: str = "paper",
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — aktif mute kuralları kör-nokta yaratıyor mu?

    Herhangi bir alarm mute'luysa bu bir kör-noktadır; canlı (live) modda KRİTİK,
    paper modda dahi kök-neden çözüldüyse kaldırılmalı. Boş mute listeleri = temiz
    (bu seansta unmute edildi).
    """
    muted = [m for m in (muted_alert_prefixes or []) if m] + [
        m for m in (muted_crit_sources or []) if m
    ]
    if not muted:
        return None
    sev = "critical" if str(run_mode).lower() == "live" else "med"
    return Finding(
        control_id="CT-OPS-01",
        severity=sev,
        owner=_OWNER,
        title="alarm mute kör-noktası",
        condition=f"Aktif mute kuralları ({run_mode} mod): {', '.join(muted)}. "
        "Bu alarmlar bastırılmış → gerçek olay sessiz kalabilir.",
        criteria="Mute geçici bir yara bandıdır; kök-neden çözülünce kaldırılmalı. "
        "Canlı modda alarm bastırma yasak.",
        cause="Paper/araştırma modu false-positive'leri için konulan mute kalıcı "
        "drift'e döndü; kaldırma unutuldu.",
        effect="Gerçek bir daemon çöküşü / DD breach / stuck doc sessizce yutulur "
        "(Swiss-cheese: izleme deliği hizalanır).",
        recommendation="Kök-neden çözüldüyse mute listelerini boşalt; canlı geçişte "
        "tüm mute'ları kaldır; mute'a TTL/expiry ekle.",
        evidence={"muted": ", ".join(muted), "run_mode": run_mode},
        due_days=5,
    )


def ct_ops_02_silent_cron(
    job_ages_hours: dict[str, float],
    expected_max_age_hours: dict[str, float],
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK (öngörü) — bir cron job beklenen penceresinde koşmuş mu?

    job_ages_hours: {job_name: son_koşmadan_bu_yana_saat}.
    expected_max_age_hours: {job_name: izin_verilen_max_saat}.
    """
    stale = []
    for job, max_age in expected_max_age_hours.items():
        age = job_ages_hours.get(job)
        if age is None:
            stale.append(f"{job}: hiç koşmamış")
        elif age > max_age:
            stale.append(f"{job}: {age:.1f}h (eşik {max_age:.0f}h)")
    if not stale:
        return None
    return Finding(
        control_id="CT-OPS-02",
        severity="high",
        owner=_OWNER,
        title="sessiz cron — beklenen pencerede koşmamış job",
        condition="Şu job'lar beklenen aralıkta çalışmamış: " + "; ".join(stale),
        criteria="Her cron job beklenen cadence'inde başarılı koşu izi bırakmalı.",
        cause="launchd/scheduler job düşmüş, exception ile sessiz fail, veya göç "
        "kalıntısı (Windows→Mac taşınmamış cron).",
        effect="İzleme/ingest/denetim sessizce durur — kör nokta büyür.",
        recommendation="job'u yeniden etkinleştir; fail-loud + heartbeat ekle.",
        evidence={"stale_jobs": "; ".join(stale)},
        due_days=3,
    )


# ----------------------------------------------------------------------
# CT-OPS-03..07 — tekrar eden daemon hata-log paterni (Principal şartı
# 2026-06-18): denetim her sabah daemon loglarını tarayıp tekrar eden
# hataları İLGİLİ owner'a bulgu olarak açar (1-gün SLA). Bilinen paternler
# owner'a route edilir; bilinmeyen ERROR yığılması CT-OPS-07 (generic) ile
# ops_engineer'a triaj için düşer. Auto-verify: düzeltilince patern logdan
# kaybolur → run_controls otomatik CLOSED yapar.
# ----------------------------------------------------------------------
# FIX 2026-07-10 (T5, izleme kör-noktası): eski liste v14.log + 5m.log +
# v14.stderr tarıyordu — v14 (2 Tem emekli) ve 5m (30 Haz emekli) ÖLÜ loglar;
# canlı bot v15p2. Günlük CT-OPS-03..07 error-pattern audit'i canlı botun
# loglarını HİÇ görmüyordu → yeni kod/emir hataları sessizce kaçıyordu.
_LOG_SCAN_FILES: tuple[str, ...] = (
    "logs/futures_daemon_v15p2.log",
    "logs/launchd/futures_v15p2.stderr.log",
    "logs/launchd/ceo.stdout.log",
)

# Her spec = bir kontrol. (control_id, owner, severity, threshold, title, regex, hint)
_LOG_PATTERN_SPECS: tuple[dict[str, Any], ...] = (
    {
        "control_id": "CT-OPS-03",
        "owner": "execution_chief",
        "severity": "med",
        "threshold": 3,
        "title": "journal DuckDB ro+rw çakışması (tekrar eden)",
        "regex": r"different configuration|TRADE_CLOSED_LOOKUP_FAIL|JOURNAL_HEAL_PNL_ERR",
        "hint": "Aynı process'te journal DuckDB'ye farklı config'le (read_only vs "
        "read_write) 2. connection açılıyor → 'different configuration'.",
    },
    {
        "control_id": "CT-OPS-04",
        "owner": "data_engineer",
        "severity": "high",
        "threshold": 5,
        "title": "DuckDB ingest invalidation / ART-index bozulması",
        "regex": r"has been invalidated|ARTOperator|ingest\.symbol_fail",
        "hint": "market_ingest.duckdb ART-index bozulması; sembol ingest fail → o "
        "sembolün barı stale kalıyor (sessiz veri-bütünlüğü kaybı).",
    },
    {
        "control_id": "CT-OPS-05",
        "owner": "execution_chief",
        "severity": "high",
        "threshold": 2,
        "title": "pozisyon-koruma döngüsü unhandled exception",
        "regex": r"POS_CHECK ERROR|float\(\) argument must be",
        "hint": "position_check() içinde None-safe olmayan float() → o tick'te tüm "
        "pozisyon koruması (SL ratchet/orphan reconcile) atlanıyor.",
    },
    {
        "control_id": "CT-OPS-06",
        "owner": "execution_chief",
        "severity": "low",
        "threshold": 5,
        "title": "pyramid leg insufficient-margin tekrar denemesi",
        "regex": r"PyramidRouter.*FAILED|PYRAMID_CHECK_ERR|InsufficientFunds|-2019",
        "hint": "Pyramid leg margin yetersizken her tick yeniden deneniyor; -2019 "
        "asla retry'la çözülmez → kalıcı disable gerekir.",
    },
)

# CT-OPS-07 generic: yukarıdakilerce KAPSANMAYAN tekrar eden ERROR/CRITICAL.
_GENERIC_ERR_RX = r"\bERROR\b|\bCRITICAL\b|Traceback|Unhandled|FATAL Error"
# Normal akış gürültüsü (hata değil) — generic taramadan dışla.
_GENERIC_BENIGN_RX = r"REJECT|_REJECT_|_skip|_done|throttle|ORPHAN_(SKIP|PENDING)|WAIT|TICK_DONE"
_GENERIC_THRESHOLD = 30


def ct_ops_log_error_pattern(
    *,
    control_id: str,
    owner: str,
    severity: str,
    title: str,
    count: int,
    threshold: int,
    window_desc: str,
    samples: list[str],
    hint: str,
) -> Finding | None:
    """DETERMİNİSTİK ÇEKİRDEK — bir hata-paterni eşik üstü tekrar ediyor mu?

    count < threshold → None (TEMİZ; auto-verify açık bulguyu kapatır).
    """
    if count < threshold:
        return None
    return Finding(
        control_id=control_id,
        severity=severity,
        owner=owner,
        title=title,
        condition=f"Son {window_desc} içinde bu hata-paterni daemon logunda "
        f"{count} kez görüldü (eşik {threshold}).",
        criteria="Tekrar eden daemon hatası bir açık kontrol-açığıdır; üretim "
        "loglarında ERROR/FAIL paterni birikmemeli.",
        cause=hint,
        effect="Hata sessizce birikiyor; journal/veri/pozisyon-koruma bütünlüğü "
        "aşınabilir ve kimse fark etmeden büyür (Swiss-cheese).",
        recommendation=f"Owner ({owner}) kök-nedeni gidersin. Düzeltme sonrası bu "
        "patern logdan kaybolacağı için denetçi kontrolü auto-verify ile CLOSED yapar.",
        evidence={
            "count": count,
            "threshold": threshold,
            "window": window_desc,
            "sample": " || ".join(s[:160] for s in samples[:3]) or "(yok)",
        },
        due_days=1,
    )


class AuditOpsAgent(AuditAgentBase):
    name: ClassVar[str] = "audit_ops"
    domain: ClassVar[str] = "ops"

    _LOG_WINDOW_DESC: ClassVar[str] = "~son 24-48s (log tail)"

    # -- log tail okuma (büyük dosyalar için seek-from-end) --
    def _tail_text(self, rel_path: str, max_bytes: int = 1_500_000, max_lines: int = 4000) -> str:
        p = self._repo_root() / rel_path
        if not p.exists():
            return ""
        try:
            size = p.stat().st_size
            with p.open("rb") as fh:
                if size > max_bytes:
                    fh.seek(-max_bytes, 2)
                    fh.readline()  # kısmi ilk satırı at
                data = fh.read()
            lines = data.decode("utf-8", "replace").splitlines()
            return "\n".join(lines[-max_lines:])
        except Exception as exc:
            logger.warning("audit_ops.tail_fail", extra={"path": rel_path, "err": str(exc)[:120]})
            return ""

    def _recent_log_lines(self) -> list[str]:
        cached = getattr(self, "_log_lines_cache", None)
        if cached is None:
            lines: list[str] = []
            for f in _LOG_SCAN_FILES:
                lines.extend(self._tail_text(f).splitlines())
            self._log_lines_cache = lines
            cached = lines
        return cached

    def _scan_log_pattern(self, spec: dict[str, Any]) -> Finding | None:
        import re

        try:
            rx = re.compile(spec["regex"])
        except re.error:
            return SKIP
        hits = [ln for ln in self._recent_log_lines() if rx.search(ln)]
        return ct_ops_log_error_pattern(
            control_id=spec["control_id"],
            owner=spec["owner"],
            severity=spec["severity"],
            title=spec["title"],
            count=len(hits),
            threshold=int(spec["threshold"]),
            window_desc=self._LOG_WINDOW_DESC,
            samples=hits[-3:],
            hint=spec["hint"],
        )

    def _scan_generic_errors(self) -> Finding | None:
        """CT-OPS-07 — bilinen paternlerce kapsanmayan tekrar eden ERROR yığılması."""
        import re

        specific = re.compile("|".join(s["regex"] for s in _LOG_PATTERN_SPECS))
        err = re.compile(_GENERIC_ERR_RX)
        benign = re.compile(_GENERIC_BENIGN_RX)
        hits = [
            ln
            for ln in self._recent_log_lines()
            if err.search(ln) and not specific.search(ln) and not benign.search(ln)
        ]
        # En sık normalize-imza (rakam/hex maskelenmiş) — yeni/bilinmeyen hatayı yüzeye çıkar.
        sig: dict[str, int] = {}
        norm = re.compile(r"[0-9a-fx]{4,}|\d+")
        for ln in hits:
            key = norm.sub("·", ln)[-120:]
            sig[key] = sig.get(key, 0) + 1
        top = sorted(sig.items(), key=lambda kv: -kv[1])[:3]
        return ct_ops_log_error_pattern(
            control_id="CT-OPS-07",
            owner="ops_engineer",
            severity="med",
            title="bilinmeyen tekrar eden ERROR yığılması (triaj)",
            count=len(hits),
            threshold=_GENERIC_THRESHOLD,
            window_desc=self._LOG_WINDOW_DESC,
            samples=[f"{c}× {k}" for k, c in top],
            hint="Bilinen patern kataloğunda (CT-OPS-03..06) olmayan yeni bir hata "
            "sınıfı tekrar ediyor. ops_engineer triaj edip ya düzeltmeli ya katalога "
            "yeni spec eklemeli.",
        )

    def run_ct_ops_01(self) -> Finding | None:
        """Canlı mute durumunu kod'dan oku (telegram_throttle + notifications)."""
        try:
            from price_action.ops.telegram_throttle import TelegramThrottle
            from price_action.orchestrator.notifications import _MUTED_CRIT_SOURCES
            from price_action.settings import get_settings

            run_mode = str(getattr(get_settings(), "pa_run_mode", "paper"))
            return ct_ops_01_mute_drift(
                list(TelegramThrottle._MUTED_ALERT_PREFIXES),
                list(_MUTED_CRIT_SOURCES),
                run_mode=run_mode,
            )
        except Exception as exc:
            logger.warning("audit_ops.ct_ops_01_fail", extra={"err": str(exc)[:160]})
            return SKIP

    # ------------------------------------------------------------------
    # CT-OPS-08 — canlı PnL-pace vs beklenti bandı (2026-07-02, sistem RW).
    # Kapsam boşluğu bulgusu: "botun varlık sebebi ölçülmüyordu" — hiçbir
    # kontrol canlı aylık pace'i resmi banda kıyaslamıyordu. Band, 2026-07-02
    # gap-waterfall denetiminin DÜRÜST bandı: +%5..%9/ay (pyramid %42 fill
    # gerçeğiyle); %12 üstü mevcut yapıyla istatistiksel olarak desteklenmiyor.
    # ------------------------------------------------------------------
    def run_ct_ops_08_pnl_pace(self) -> Finding | None:
        """Borsa-truth income → aylık pace; band dışıysa finding (owner=ceo)."""
        try:
            import sys
            from datetime import UTC, datetime

            repo = self._repo_root()
            if str(repo / "scripts") not in sys.path:
                sys.path.insert(0, str(repo / "scripts"))
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            from scripts.futures_trade_daily import get_futures_exchange  # type: ignore

            ex = get_futures_exchange()
            clean_ms = int(datetime(2026, 6, 14, 21, 53, tzinfo=UTC).timestamp() * 1000)
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            rows: list[dict[str, Any]] = []
            cur = clean_ms
            while cur < now_ms:
                batch = ex.fapiPrivateGetIncome(
                    {"startTime": cur, "endTime": now_ms, "limit": 1000}
                )
                if not batch:
                    break
                rows.extend(batch)
                if len(batch) < 1000:
                    break
                cur = int(batch[-1]["time"]) + 1
            seen: set[tuple] = set()
            net = 0.0
            n_closes = 0
            for r in rows:
                k = (r.get("tranId"), r.get("time"), r.get("incomeType"), r.get("income"))
                if k in seen:
                    continue
                seen.add(k)
                t = r.get("incomeType")
                if t in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
                    net += float(r.get("income") or 0.0)
                    if t == "REALIZED_PNL" and float(r.get("income") or 0.0) != 0.0:
                        n_closes += 1
            days = max(1e-9, (now_ms - clean_ms) / 86_400_000)
            if days < 7 or n_closes < 20:
                return SKIP  # örneklem çok kısa — pace hükmü verilmez
            pace_pct = net / 5000.0 / days * 30.0 * 100.0
            band_lo, band_hi = 5.0, 9.0
            if pace_pct >= band_lo:
                return None  # band içi/üstü — kontrol temiz
            sev = "high" if pace_pct < 0 else "med"
            return Finding(
                control_id="CT-OPS-08",
                severity=sev,
                owner="ceo",
                title="canlı PnL pace resmi bandın altında",
                condition=(
                    f"Temiz-dönem aylık pace {pace_pct:+.1f}%/ay — resmi dürüst band "
                    f"[{band_lo:.0f}, {band_hi:.0f}]%/ay altında. NET ${net:+.2f} / "
                    f"{days:.1f} gün / {n_closes} kapanış."
                ),
                criteria="2026-07-02 gap-waterfall mutabakatı: dürüst band +5..9%/ay "
                "(pyramid %42 leg-fill gerçeğiyle); negatif pace derhal eskalasyon.",
                cause="Rejim/DD-yarası/kol-atrofisi olabilir — Analyst atribüsyon "
                "raporu gerekir (kol bazında).",
                effect="Sermaye hedefin altında çalışıyor; band dışı sapma erken "
                "yakalanmazsa ay sonu sürprizi.",
                recommendation="Analyst'ten kol-bazlı atribüsyon iste; 2 hafta üst "
                "üste band-altıysa CEO kapital/kol kararı gündeme.",
                evidence={
                    "pace_pct_monthly": f"{pace_pct:+.2f}",
                    "net_usd": f"{net:+.2f}",
                    "days": f"{days:.1f}",
                    "n_closes": str(n_closes),
                },
                due_days=3,
            )
        except Exception as exc:
            logger.warning("audit_ops.ct_ops_08_fail", extra={"err": str(exc)[:160]})
            return SKIP

    # ------------------------------------------------------------------
    # CT-OPS-09 — araştırma fabrikası çıktı-watchdog'u (2026-07-02, sistem RW).
    # Kapsam boşluğu: "cron KOŞUYOR ama 32 gündür 0 terfi" hâlini hiçbir kontrol
    # görmüyordu (CT-OPS-02 silent-cron bunu yakalayamaz — job'lar canlıydı).
    # ------------------------------------------------------------------
    def run_ct_ops_09_promotion_throughput(self) -> Finding | None:
        """Autopilot AÇIK + son 14 günde ≥10 tournament raporu var + 0
        promote_candidate → fabrika boşta dönüyor (owner=lab_scientist)."""
        try:
            import os
            import time

            if os.getenv("PA_RESEARCH_AUTOPILOT", "0") != "1":
                return None  # fabrika bilinçli kapalıyken watchdog susar
            lab_dir = self._repo_root() / "reports" / "lab"
            if not lab_dir.exists():
                return SKIP
            cutoff = time.time() - 14 * 86400
            recent = [p for p in lab_dir.glob("*tournament*.md") if p.stat().st_mtime >= cutoff]
            if len(recent) < 10:
                return None  # yeterli pencere yok (yeniden-açılış grace'i)
            n_promote = 0
            for p in recent:
                try:
                    if "promote_candidate" in p.read_text(encoding="utf-8"):
                        n_promote += 1
                except OSError:
                    continue
            if n_promote > 0:
                return None
            return Finding(
                control_id="CT-OPS-09",
                severity="med",
                owner="lab_scientist",
                title="araştırma fabrikası çıktısı 0 — promotion throughput",
                condition=(
                    f"Autopilot AÇIK, son 14 günde {len(recent)} tournament raporu "
                    "koştu, promote_candidate=0. Cron'lar canlı ama ürün yok."
                ),
                criteria="Fabrika açıkken 14 günlük pencerede en az 1 promote_candidate "
                "(veya gate'lerin NEDEN geçilemediğine dair yapısal analiz) beklenir.",
                cause="Gate kalibrasyonu (DSR/effect), aday havuzu kalitesi veya "
                "challenger toplama kopukluğu.",
                effect="Token/CPU yakılıyor, canlı bot rakipsiz yaşlanıyor — 30 Haz "
                "öncesi 195-abort churn'ünün geri dönüşü riski.",
                recommendation="Gate red-sebep dağılımını çıkar (effect mi DSR mi "
                "maxdd mi); aday kaynaklarını (sweep/hypothesis) genişletmeden önce "
                "kaliteyi doğrula.",
                evidence={
                    "n_tournaments_14d": str(len(recent)),
                    "n_promote": "0",
                },
                due_days=5,
            )
        except Exception as exc:
            logger.warning("audit_ops.ct_ops_09_fail", extra={"err": str(exc)[:160]})
            return SKIP

    def controls(self) -> dict[str, Any]:
        ctrls: dict[str, Any] = {"CT-OPS-01": self.run_ct_ops_01}
        # CT-OPS-03..06 — bilinen hata-paternleri (owner'a route, 1-gün SLA).
        for spec in _LOG_PATTERN_SPECS:
            ctrls[spec["control_id"]] = lambda s=spec: self._scan_log_pattern(s)
        # CT-OPS-07 — bilinmeyen ERROR yığılması (generic catch-all → ops_engineer).
        ctrls["CT-OPS-07"] = self._scan_generic_errors
        # CT-OPS-08/09 — 2026-07-02 sistem RW kapsam-boşluğu kapatmaları:
        # canlı PnL-pace bandı (owner=ceo) + fabrika promotion-throughput
        # watchdog'u (owner=lab_scientist).
        ctrls["CT-OPS-08"] = self.run_ct_ops_08_pnl_pace
        ctrls["CT-OPS-09"] = self.run_ct_ops_09_promotion_throughput
        return ctrls
