"""CEO Agent — Trading Desk Head.

CEO'nun mandate'i:
- Günlük morning brief
- Haftalık executive summary
- Kriz protokolü tetikleme önerisi
- Departmanlar arası çatışma çözme

CEO emir VEREMEZ — sadece **öneri** üretir. Çıktı `reports/ceo/` altında
markdown olarak diskte kalır.

Faz 1.4: `_collect_daily_context` artık `memory/shared/active_state.md` ve
`memory/protocol/inbox.jsonl`'i her zaman dahil eder; yeni `update_active_state()`
metodu Researcher hipotezleri + Lab drift alarmları + open critique'leri tarayarak
ledger'ı (sadece CEO'nun yazma yetkisi) günceller.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger
from price_action.settings import get_settings

from .base import LLMAgentBase


class CEOAgent(LLMAgentBase):
    name: ClassVar[str] = "ceo"
    default_model: ClassVar[str] = ""  # settings.claude_model_default
    # CEO sadece okuma + dosya yazma yapabilir (rapor)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",
        "list_dir",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        p = self.settings.reports_dir / "ceo"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _write_report(self, filename: str, content: str) -> Path:
        path = self._reports_dir() / filename
        path.write_text(content, encoding="utf-8")
        logger.info("ceo.report_written", extra={"path": str(path)})
        return path

    # ------------------------------------------------------------------
    # SOP
    # ------------------------------------------------------------------

    async def daily_brief(self, when: date | None = None) -> Path:
        """Sabah brief'ini üretir. Çıktı: `reports/ceo/YYYY-MM-DD-brief.md`.

        Faz 1.4: brief üretmeden ÖNCE `update_active_state()` çağrılır ki
        ledger taze olsun (inbox doc'lar, open hypotheses, drift alerts
        güncel). Brief prompt'una protokol farkındalığı eklenir.

        Faz 3.4: brief'ten ÖNCE `_check_conflicts()` çağrılır; aynı doc_id'ye
        yönelik zıt critique'ler varsa otomatik `arbitrate()` tetiklenir.
        Çıktı brief'in "Decisions Made" section'ına dahil edilir.
        """
        when = when or date.today()
        # Faz 1.4: ledger refresh
        try:
            self.update_active_state()
        except Exception as exc:
            logger.warning("ceo.update_active_state_fail", extra={"err": str(exc)[:200]})

        # Faz 3.4: conflict scan + arbitrate
        arbitrate_outputs: list[str] = []
        try:
            conflicts = self._check_conflicts()
            for conflict in conflicts[:3]:  # max 3 arbitrate per brief
                out = await self.arbitrate(conflict)
                arbitrate_outputs.append(f"- {conflict.get('topic', '?')}: {out[:200]}")
        except Exception as exc:
            logger.warning("ceo.conflict_scan_fail", extra={"err": str(exc)[:200]})

        # Faz 3.4 BUG FIX: arbitrate_outputs prompt'a dahil edilir
        # (eskiden dead code — list dolduruluyordu ama prompt'a girmiyor)
        arbitrate_section = ""
        if arbitrate_outputs:
            arbitrate_section = (
                "\n\n## CONFLICTS RESOLVED (auto-arbitrate sonuçları)\n"
                + "\n".join(arbitrate_outputs)
                + "\n\n^ Bu çatışma çözümlerini brief'in 'Decisions Made' "
                "veya 'Blocked on Principal' bölümlerine yansıt."
            )

        prompt = (
            "SOP-1 Günlük Morning Brief üret. Önce dünkü Analytics raporlarını, "
            "açık pozisyon snapshot'ını ve `memory/shared/active_state.md` "
            "ledger'ını oku. 'CEO Morning Brief' başlık formatında çıktı ver.\n\n"
            "ZORUNLU section'lar:\n"
            "- ## TL;DR (Telegram-friendly, <280 char)\n"
            "- ## Dünkü Performans\n"
            "- ## Bugünün Risk Tablosu\n"
            "- ## Alternative Scenarios (en az 2 counterfactual)\n"
            "- ## Open Questions (en az 3, her biri specific agent'a)\n"
            "- ## Blocked on Principal (insan onayı bekleyenler)\n\n"
            "Sayısal gerekçe olmayan satır yazma. Inbox'taki critique'leri "
            "değerlendir; conflict varsa arbitrate önerisi ekle."
            + arbitrate_section
        )
        ctx = self._collect_daily_context(when)
        text = await self.run(prompt, context_files=ctx)
        path = self._write_report(f"{when.isoformat()}-brief.md", text)
        self.record_episodic(
            f"daily_brief produced for {when.isoformat()}", tags=["brief", "daily"]
        )
        return path

    async def weekly_summary(self, week_label: str | None = None) -> Path:
        """Haftalık executive summary."""
        if week_label is None:
            iso = datetime.now(timezone.utc).isocalendar()
            week_label = f"{iso.year}-W{iso.week:02d}"
        prompt = (
            "SOP-2 Haftalık Executive Summary üret. Net P&L, Sharpe, MaxDD, "
            "profit factor; Researcher hipotez özeti; Lab tournament sonucu; "
            "drift uyarısı; aday parametre değişiklikleri (insan onayına); "
            "önümüzdeki haftaya 3 watch-item."
        )
        ctx = self._collect_weekly_context()
        text = await self.run(prompt, context_files=ctx)
        return self._write_report(f"{week_label}-weekly.md", text)

    async def crisis_protocol(self, reason: str) -> Path:
        """Kriz protokolü — önerileri üretir; aksiyon almaz."""
        prompt = (
            f"SOP-3 Kriz Protokolü tetiklendi. Tetikleyici: {reason}. "
            "Sadece **öneri** üret: Telegram CRIT alert metni, açık pozisyon "
            "için partial-close veya SL sıkıştırma önerisi, sebep analizi. "
            "Hiçbir komut çağrısı yapma; insan onayı zorunlu olduğunu yinele."
        )
        text = await self.run(prompt)
        slug = "crisis-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = self._write_report(f"{slug}.md", text)
        self.record_episodic(
            f"crisis_protocol triggered: {reason}", tags=["crisis"], kind="learning"
        )
        return path

    async def arbitrate(self, conflict: dict[str, Any]) -> str:
        """SOP-4: Departmanlar arası çatışma çözümü. ADR yazar + cevap döner.

        ``conflict`` örneği::
            {
              "topic": "promotion_vs_drift",
              "researcher_view": "...",
              "lab_view": "...",
              "metrics": {...}
            }
        """
        prompt = (
            "SOP-4 Departmanlar Arası Çatışma. Aşağıdaki çatışmayı sayısal "
            "gerekçelerle değerlendirip karar öner. Conservative bias: "
            "şüphedeyken Risk/Lab tarafına yaslan.\n\n"
            f"CONFLICT: {conflict}"
        )
        text = await self.run(prompt)
        adr = {
            "title": f"Arbitration: {conflict.get('topic', 'untitled')}",
            "context": str(conflict),
            "options": "Promote / Reject / Wait",
            "decision": text,
            "consequences": "Re-evaluate in 4 weeks.",
            "status": "proposed",
        }
        self.write_decision(adr, slug=f"arbitration-{conflict.get('topic', 'untitled')}")
        return text

    # ------------------------------------------------------------------
    # Context toplama
    # ------------------------------------------------------------------

    def _collect_daily_context(self, when: date) -> list[Path]:
        """Brief context dosyaları.

        Faz 1.4: protokol farkındalığı —
        - `memory/shared/active_state.md` HER ZAMAN dahil (single source of truth)
        - `memory/shared/protocol.md` HER ZAMAN dahil (kurallara dair farkındalık)
        - Son inbox doc'larından recipient=ceo olanlar (ref_path'leri) eklenir
        - Mevcut analytics + lab raporları
        """
        s = get_settings()
        candidates: list[Path] = []

        # 1) Active state ledger (zorunlu)
        active_state = self.settings.memory_dir / "shared" / "active_state.md"
        if active_state.exists():
            candidates.append(active_state)

        # 2) Protocol (zorunlu — agent her oturumda kurallarını okur)
        protocol = self.settings.memory_dir / "shared" / "protocol.md"
        if protocol.exists():
            candidates.append(protocol)

        # 3) Mevcut analytics + lab
        candidates.extend([
            s.reports_dir / "analytics" / f"{when.isoformat()}.md",
            s.reports_dir / "analytics" / "yesterday.md",
            s.reports_dir / "lab" / "latest.md",
        ])

        # 4) Inbox: kendisine yönelik son 50 doc'tan ref_path'leri ekle (max 5)
        try:
            inbox_refs = self._collect_inbox_refs(limit=5)
            candidates.extend(inbox_refs)
        except Exception as exc:
            logger.warning("ceo.inbox_collect_fail", extra={"err": str(exc)[:200]})

        # 5) Son tournament + drift (varsa)
        lab_dir = s.reports_dir / "lab"
        if lab_dir.exists():
            for pattern in ("tournament-*.md", "drift-*.md", "whatif-*.md"):
                matches = sorted(lab_dir.glob(pattern), reverse=True)[:1]
                candidates.extend(matches)

        # 6) Son 7g analytics whatif raporu (Faz 2'de aktif olacak)
        analytics_dir = s.reports_dir / "analytics"
        if analytics_dir.exists():
            recent_whatif = sorted(analytics_dir.glob("whatif-*.md"), reverse=True)[:1]
            candidates.extend(recent_whatif)

        # De-dup + existence filter
        seen: set[str] = set()
        result: list[Path] = []
        for p in candidates:
            if p and p.exists():
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    result.append(p)
        return result

    def _collect_weekly_context(self) -> list[Path]:
        s = get_settings()
        candidates: list[Path] = []
        # Active state + protocol HER ZAMAN
        for shared in ("active_state.md", "protocol.md"):
            p = self.settings.memory_dir / "shared" / shared
            if p.exists():
                candidates.append(p)
        for sub in ("analytics", "research", "lab"):
            d = s.reports_dir / sub
            if d.exists():
                latest = sorted(d.glob("*.md"), reverse=True)[:3]
                candidates.extend(latest)
        return candidates

    def _collect_inbox_refs(self, *, limit: int = 5) -> list[Path]:
        """Inbox'tan recipient=ceo olan son N doc'un ref_path'lerini topla.

        M1 FIX: ref_path validation — Path.resolve() ile traversal saldırılarına
        karşı koruma. `../../../etc/passwd` gibi yolları reddet.

        Atomik değil — concurrent yazma sırasında bazı satırlar kaybolabilir,
        ama append-only formatta okuma genelde tutarlı.
        """
        inbox = self.settings.memory_dir / "protocol" / "inbox.jsonl"
        if not inbox.exists():
            return []
        # M1: izin verilen kök dizin (repo root) — tüm ref_path'ler bunun altında olmalı
        allowed_root = self.settings.reports_dir.parent.resolve()
        refs: list[Path] = []
        try:
            lines = inbox.read_text(encoding="utf-8").strip().split("\n")
            # Son 50 satıra bak, sondan başa doğru filtrele
            for line in reversed(lines[-50:]):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                recipient = msg.get("recipient", "")
                ack_at = msg.get("ack_at")
                # Bana yönelik veya broadcast (all) ve henüz ack'lenmemiş
                if recipient in (self.name, "all") and not ack_at:
                    ref = msg.get("ref_path", "")
                    if not ref:
                        continue
                    # M1 FIX: Path traversal validation
                    try:
                        candidate = (allowed_root / ref).resolve()
                        # candidate allowed_root altında mı?
                        candidate.relative_to(allowed_root)
                    except (ValueError, OSError):
                        logger.warning(
                            "ceo.inbox_ref_path_traversal",
                            extra={"ref_path": ref[:200], "sender": msg.get("sender", "?")},
                        )
                        continue
                    if candidate.exists():
                        refs.append(candidate)
                if len(refs) >= limit:
                    break
        except Exception as exc:
            logger.warning("ceo.inbox_parse_fail", extra={"err": str(exc)[:200]})
        return refs

    # ------------------------------------------------------------------
    # Faz 3.4 — Conflict detection (aynı doc'a zıt critique'ler)
    # ------------------------------------------------------------------

    def _check_conflicts(self, *, since_days: int = 7) -> list[dict[str, Any]]:
        """Aynı `depends_on`'a yönelik zıt critique + endorse var mı tara.

        H2 FIX: `since_days` cutoff (mtime bazlı) eklendi. Eskiden tüm
        `reports/risk/` dizinini parse ediyordu — 6 ay sonra 200+ doc her
        brief'te yaml parse + IO. Şimdi son 7 günle sınırlı.

        Returns
        -------
        list[dict]
            Her conflict için ``{topic, original_doc_id, critique_path, endorse_path}``.
        """
        risk_dir = self.settings.reports_dir / "risk"
        if not risk_dir.exists():
            return []

        critiques: dict[str, list[Path]] = {}
        endorses: dict[str, list[Path]] = {}

        import yaml
        from datetime import datetime as _dt, timezone as _tz
        FRONTMATTER_RE = __import__("re").compile(r"^---\n(.*?)\n---\n", __import__("re").DOTALL)
        cutoff_ts = _dt.now(_tz.utc).timestamp() - since_days * 86400

        for p in risk_dir.glob("*.md"):
            try:
                # H2: mtime cutoff — eski dosyaları atla
                if p.stat().st_mtime < cutoff_ts:
                    continue
                content = p.read_text(encoding="utf-8")
                m = FRONTMATTER_RE.match(content)
                if not m:
                    continue
                fm = yaml.safe_load(m.group(1)) or {}
                doc_type = fm.get("doc_type")
                depends_on = fm.get("depends_on", []) or []
                if doc_type == "critique":
                    for dep in depends_on:
                        critiques.setdefault(dep, []).append(p)
                elif doc_type == "endorse":
                    for dep in depends_on:
                        endorses.setdefault(dep, []).append(p)
            except Exception:
                continue

        # Conflict: same doc_id has both critique and endorse
        conflicts: list[dict[str, Any]] = []
        for orig_id in critiques:
            if orig_id in endorses:
                conflicts.append({
                    "topic": f"critique_vs_endorse_{orig_id}",
                    "original_doc_id": orig_id,
                    "critique_paths": [str(p) for p in critiques[orig_id]],
                    "endorse_paths": [str(p) for p in endorses[orig_id]],
                })
        if conflicts:
            logger.info(
                "ceo.conflicts_detected",
                extra={"n": len(conflicts), "topics": [c["topic"] for c in conflicts]},
            )
        return conflicts

    # ------------------------------------------------------------------
    # Faz 1.4 — Active State Ledger update (sadece CEO yazar)
    # ------------------------------------------------------------------

    def update_active_state(self) -> Path | None:
        """`memory/shared/active_state.md` ledger'ını yenile.

        M3 FIX: regex replacement → proper YAML parse + serialize.
        Eskiden `re.sub` ile `^last_updated:` arıyordu; YAML structure değişirse
        kırılırdı. Şimdi yaml.safe_load(frontmatter) → dict update → yaml.dump.

        Returns
        -------
        Path | None
            Güncellenen dosya yolu (yoksa None).
        """
        ledger = self.settings.memory_dir / "shared" / "active_state.md"
        if not ledger.exists():
            logger.warning("ceo.active_state_missing", extra={"path": str(ledger)})
            return None

        try:
            import yaml
            content = ledger.read_text(encoding="utf-8")

            # Frontmatter parse — proper YAML
            fm_re = __import__("re").compile(r"^---\n(.*?)\n---\n", __import__("re").DOTALL)
            m = fm_re.match(content)
            if not m:
                logger.warning("ceo.active_state_no_frontmatter")
                return None

            try:
                fm_dict = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError as exc:
                logger.warning("ceo.active_state_yaml_parse_fail", extra={"err": str(exc)[:200]})
                return None

            # Update fields
            new_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fm_dict["last_updated"] = new_ts
            fm_dict["updated_by"] = "ceo"

            # Serialize back — sort_keys=False yapı sırasını korur
            new_fm = yaml.safe_dump(fm_dict, default_flow_style=False, sort_keys=False)
            new_content = "---\n" + new_fm + "---\n" + content[m.end():]

            ledger.write_text(new_content, encoding="utf-8")
            logger.info("ceo.active_state_updated", extra={"ts": new_ts})
            return ledger
        except Exception as exc:
            logger.warning("ceo.active_state_update_fail", extra={"err": str(exc)[:200]})
            return None
