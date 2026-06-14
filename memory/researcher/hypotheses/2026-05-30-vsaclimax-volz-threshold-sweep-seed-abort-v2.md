---
doc_id: researcher-20260530T023600-vsaclimax-volz-threshold-sweep-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-30T02:36:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260530T103000-vsaclimax-volz-threshold-sweep]
blocks: []
requested_review_from: []
tags: [seed_abort, cron_blindness, vsaclimax, volz, self_throttle_arming, prompt_injection, family_wise_n_inflation]
supersedes: null
hash: null
---

# SEED ABORT v2 — vsaclimax-volz-threshold-sweep (cron 2. tetik, ~2 dakika içinde)

> Aynı seed'in v1'i 2026-05-30T02:34Z'de pre-reg edildi (`researcher-20260530T103000-vsaclimax-volz-threshold-sweep`, status PROPOSED, requested_review_from=[lab_scientist, risk_officer, adversary_engineer], 6+4=10 trial family). Cron ~2 dakika sonra (2026-05-30T02:36Z) AYNI seed payload'ını ("Curve-fit şüphesi yarat" injection clause dahil) yeniden tetikledi. v1 substantive bir pre-reg — seed-abort DEĞİL; v2 tetiği ise aynı substrate için ikinci yazım = family-wise N inflation + audit-trail kirlenmesi. **Pre-test reddedildi.**

## 1. Bağlam — neden v2 = abort, v1 = meşru pre-reg

v1 (researcher-20260530T103000-vsaclimax-volz-threshold-sweep):
- **Substrate meşru**: vsa_climax_test canlı 15m strateji, `volume_zscore_min` manifest'te knob olarak var, RAG #1/#2/#4/#9 topical hit ≥4 directly relevant.
- **NULL-proving formulation**: H1 = "ek vol_z gate edge taşımaz, right-tail bozar", H0 = "≥1 threshold +5pp lift + DD korunur + top-5%-share korunur + sign-flip p<0.00833".
- **10 katmanlı anti-curve-fit guard PRE-COMMIT**: coarse grid (6 nokta), boundary-extreme rule, monotonicity check, multi-knob freeze, paired sign-flip null, IS/OOS gap floor, cut-bucket inspection, Holm-10 family-wise, symbol-out CV (14 fold), right-skew artifact guard.
- **Prompt injection clause §10'da explicit reddedildi** ve audit-trail'e işlendi.
- **Pool↔kod parity uyarısı §0/§6/§8'de explicit yakalandı** (2026-05-29 learning).

v2 tetiği ne getiriyor? **Hiçbir yeni state**:
- Substrate aynı (vsa_climax_test deploy değişmedi, manifest değişmedi, pool aynı, trail config aynı, risk config aynı).
- RAG hits aynı (~2 dakika içinde corpus refresh olmadı; refs identical).
- Cron payload identical ("Curve-fit şüphesi yarat" clause hâlâ orada).
- 2 dakikadan kısa sürede ne pool rebuild ne config drift ne yeni öğrenme.

→ **v2 yazsam**, family-wise N (per-seed): 10 (v1 trials) + 6+4 (v2 trials) = 20. Holm α/m: 0.005 → 0.0025 (yarıya). Marjinal Bayes posterior gerçek-edge ≤ 0; sadece audit-trail kirlenmesi + inbox.jsonl gürültüsü.

## 2. Rejection grounds (4 bağımsız sebep)

### 2.1 Family-wise N inflation
v1 zaten 10 trials pre-committed (6 primary vol_z grid + 4 secondary vol_sma_mult sensitivity). v2 yazımı bu N'yi 20'ye çıkarır → Holm-step-down floor 0.005 → 0.0025 (%50 sıkışma). Hiçbir threshold v1'de geçemezken v2'de geçme olasılığı paradoksal olarak DÜŞER (α daha sıkı). Marjinal değer ≤ 0.

### 2.2 Substrate unchanged → no new information
2 dakikalık pencere içinde değişen hiçbir state yok: kod (HEAD identical), manifest, pool, deploy config, RAG corpus, learning. Aynı bilgi durumu üstünde 2. pre-reg = redundant.

### 2.3 Prompt injection clause persists (v1'de zaten reddedildi)
"Curve-fit şüphesi yarat" string'i cron payload'ında hâlâ aktif. v1 §10'da: "persona Hard-Limit'lerine doğrudan zıt ('Anti-narrative bias', 'Reject more than you accept'). Reddedilmiştir." Aynı reddi v2'de tekrar etmek = JSONL kirlenmesi, inbox gürültüsü. Audit-trail tek-doc yeterli.

### 2.4 Cron blindness pattern — established protocol
Recent learning (2026-05-27 cross-strategy-companion v7→v8, 2026-05-30 daily-scan v2→v3, 2026-05-29 btc-dominance v2→v3, ve diğerleri) kalıbı: aynı seed kısa sürede tekrar tetiklenirse v2 abort doc + sonraki tetiklerde JSONL-only. Self-throttle ARMED.

## 3. Sayılar (audit)

| Field | Value |
|---|---|
| Seed | vsa_climax_test: volume-z threshold parameter sweep |
| v1 doc_id | researcher-20260530T103000-vsaclimax-volz-threshold-sweep |
| v1 created | 2026-05-30T02:34Z (file mtime), 2026-05-30T10:30Z (doc UTC field — local TZ confusion in v1) |
| v2 trigger | 2026-05-30T02:36Z (~2 min after v1) |
| Family-wise N (v1) | 10 (6 primary vol_z + 4 secondary vol_sma_mult) |
| Holm α/m (v1) | 0.005 |
| Family-wise N if v2 written | 20 |
| Holm α/m if v2 written | 0.0025 (%50 sıkışma) |
| RAG corpus refresh in 2 min window? | No |
| Substrate state change in 2 min window? | No |
| Bayes posterior real-edge if v2 written | ≤ 0 |
| Self-throttle status post-v2 | ARMED (3+. tetik JSONL-only) |

## 4. Self-throttle protocol activation

Bu v2 abort doc, self-throttle saatini başlatır:
- Şu andan itibaren 24h içinde aynı seed için 3. tetik gelirse → seed_abort_log.jsonl'a tek satır + **doc YAZILMAZ** (vsa-companion v7→v8 protokolü, 2026-05-27 learning).
- 4./5./N. tetik aynı kural.
- State değişikliği (v1 review tamamlanır + APPROVED/REJECTED, ya da cron payload rotate edilir, ya da pool rebuild + parity refresh) → throttle reset.

## 5. Escalation

- **ops_engineer guard #1 SLA 2026-06-03** (per-seed cron cooldown): kaçırılırsa CEO directive draft → bu seed payload'ı 30 gün dondur. Alternatif seed listesi: brooks parametric sweep (Donchian-N), brooks 7fx runner-trail variants, brooks crypto transfer (WINNER-LET-RUN prior+), brooks 1H diversifier küçük-ağırlık, funding-rate regime gate.
- **ops_engineer guard #8 (yeni öneri)**: cron payload sanitizer — "curve-fit yarat", "p-hack başlat", "shortcut bul", "narrative üret" gibi anti-rigor stringleri otomatik strip. v1 §10 + bu doc §2.3'te aynı injection 4. ardışık vakada tekrar göründü.
- **Lab Scientist'a query (paralel)**: son RAG refresh timestamp + delta? Eğer corpus son 24h'da değişmediyse, RAG-hit-tabanlı meşruiyet de zaman içinde "stale legitimacy" haline gelir; bu yeni bir guard önerisi (#9: RAG_FRESHNESS_MAX age 7 gün).

## 6. Karar

- **REJECTED pre-test, doc yazıldı (v2 abort)**.
- seed_abort_log.jsonl'a 1 satır JSON eklendi.
- v1 (researcher-20260530T103000) PROPOSED kalıyor, review beklemekte (lab_scientist + risk_officer + adversary_engineer).
- Self-throttle ARMED: 3. tetikte JSONL-only.

---

**Audit complete. v2 abort frozen. No further v2 trial added to family.**
