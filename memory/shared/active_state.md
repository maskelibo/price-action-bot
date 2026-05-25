---
doc_id: active-state-current
doc_type: protocol
agent_id: ceo
created_at: 2026-05-25T00:00:00Z
status: ACTIVE
confidence: high
last_updated: 2026-05-25T00:56:26Z
updated_by: ceo
depends_on: []
tags: [active_state, ledger, single_source_of_truth]
---

# Active State Ledger — Şirketin Anlık Durumu

> **Tek doğruluk noktası.** Tüm agent'lar bu dosyayı okur. Sadece `ceo` yazar (`update_active_state()` metodu `daily_brief()` başında ve sonunda çağırır). Manuel edit yalnızca `human_principal` yapar.

## 1. Live Bots — şu anda çalışan

| Bot | Mode | PID | Strategy | Uptime | Capital | Risk/Trade | Notlar |
|---|---|---|---|---|---|---|---|
| futures_daemon_15m | paper (testnet) | 17267 | wide-stop (sl_pct ≥ 2.5%) | 2g+ | $5000 | $25 (0.5%) | Bekleyen — son 2 günde 0 entry |

## 2. Active Strategies (deployed)

| Strategy | Manifest | Config | Status | Live since | Last review |
|---|---|---|---|---|---|
| 15m wide-stop v2 | configs/risk_phoenix_scalp_15m_widestop.yaml | sl≥2.5%, risk 0.5% | ACTIVE | 2026-05-22 | 2026-05-22 |

## 3. Open Hypotheses (Researcher pre-registered, sonuç bekleniyor)

| HYP ID | Title | Status | Pre-reg date | Owner | Notes |
|---|---|---|---|---|---|
| HYP-2026-05-22-15m-widestop-dd | 15m wide-stop grid optimization for DD ≤ -25% | OPEN | 2026-05-22 | researcher | Grid run sonucu bekleniyor |
| (proposed) D2-vsa-only-sl30 | Sadece vsa_climax_test stratejisi sl_pct≥3.0% | DRAFT | 2026-05-25 | researcher (henüz pre-reg edilmemiş) | Bu seansta keşfedildi |

## 4. Open Critiques (review bekleyenler)

| Doc ID | Original doc | Reviewer | Days waiting | Notes |
|---|---|---|---|---|
| (none) | | | | İlk inbox boş |

## 5. Active Drift Alerts (son 7 gün)

| Alert ID | Symbol/Strategy | KS p-value | Detected | Status | Response |
|---|---|---|---|---|---|
| (none) | | | | | Lab henüz drift detect çalıştırmadı |

## 6. Pending Principal Decisions (insan onayı bekleyen)

| Decision | Description | Originator | Days waiting | Urgency |
|---|---|---|---|---|
| D2 paper-deploy | "Sadece vsa_climax + sl≥3.0" config'i 2. paralel paper bot olarak çalıştır | ad-hoc (bu seans bulgusu) | 0 | MEDIUM — backtest pozitif ama WF-OOS testleri eksik |
| Wide-stop deploy onayı | RESUME_2026-05-22'de açık: principal kararı bekliyor | researcher | 3 | HIGH |
| 5m P1c paper-deploy | reports/research/5m_p1c_candidate_2026-05-24.md WIRE adımları | researcher | 1 | MEDIUM |

## 7. Last Weekly Consolidation

- **Date:** (henüz hiç çalışmadı — Faz 4 sonrası başlayacak)
- **Next scheduled:** Faz 4 implementation sonrası Pazar 05:30 UTC

## 8. System Health

| Component | Status | Last check | Notes |
|---|---|---|---|
| futures_daemon_15m | 🟢 Healthy | (saatlik ops job) | uptime 2g+, son log <15dk |
| ceo_loop (autonomous) | 🔴 Not deployed | - | Faz 1.1 ile launchd entegrasyonu beklenir |
| Inbox processing | 🔴 Not active | - | Faz 1.5 sonrası |
| Telegram push | 🟡 Manual only | - | llm_orchestrator.py'den manual; pa-ceo unify Faz 1.2 |

## 9. Known Risks & Open Threads

- 2026 YTD wide-stop edge zayıf (+%4.6/ay vs hedef ≥%10) — rejim değişikliği uyarısı (henüz teyit yok)
- Execution Chief live mode PLACEHOLDER — gerçek borsa emri yok, sadece paper
- Inbox.jsonl rotation yok (Faz 4'te eklenecek)
- launchd autostart kurulmamış — Mac mini reboot olursa ceo_loop düşer

---

**Format kuralı:** Tablolar mümkün olduğunca sabit kolonla. Yeni section eklemek için Principal onayı. Bu dosya update_active_state() ile her CEO çalışmasında refreshlenir (sadece veri kısımları; yapı sabit).
