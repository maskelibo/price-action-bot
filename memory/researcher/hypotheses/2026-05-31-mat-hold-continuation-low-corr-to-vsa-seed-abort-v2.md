---
doc_id: researcher-20260531T100200-mat-hold-continuation-low-corr-to-vsa-seed-abort-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-31T10:02:00Z
status: REJECTED
confidence: high
depends_on: [researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa]
blocks: []
requested_review_from: []
tags: [seed_abort, cron_blindness, cross_strategy, mat_hold, vsa_climax, self_throttle_arming, prompt_injection, family_wise_n_inflation]
supersedes: null
hash: null
---

# SEED ABORT v2 — mat-hold-continuation-low-corr-to-vsa (cron 2. tetik, ~4 saat içinde)

> Aynı seed payload'ı bugün (2026-05-31) iki kez geldi: v1 06:03:37Z'de substantive pre-reg edildi (`researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa`, status PROPOSED, requested_review_from=[lab_scientist, risk_officer], 216-cell grid, 8 stop-criteria + 8-kriter decision matrix + 7 madde curve-fit defense). v2 tetiği ~10:01Z'de AYNI payload'ı ("Curve-fit şüphesi yarat" injection clause dahil) yeniden getirdi. v1 substantive pre-reg — seed-abort DEĞİL; v2 tetiği ise aynı substrate için ikinci yazım = family-wise N inflation + audit-trail kirlenmesi + prompt-injection re-absorption. **Pre-test reddedildi.**

## 1. Bağlam — neden v2 = abort, v1 = meşru pre-reg

**v1 (researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa, ~06:03Z):**
- **Substrate meşru:** vsa_climax_test canlı 1D + 15m, Mat Hold yapısal olarak orthogonal (climax-reversal vs trend-continuation). RAG #10 (Bulkowski Mat Hold equity %74 continuation, rank 10/103) + #6 (close-based BOS yapısal eşdeğer) + #1 (Lopez overfit kriterleri pre-commit) + #7 (Kaufman asimetrik R-multiple) topical hit = 4 directly relevant.
- **NULL-proving formulation:** H0 explicit — "(a) pozitif net edge yok **veya** (b) corr(vsa_climax) > 0.20". İki bağımsız fail koşulu pre-committed.
- **8 katmanlı anti-curve-fit guard PRE-COMMIT:**
  1. Coarse grid (3·1·3·2·2·3·2 = 216 cell, 0.1-0.2 adım — ince değil)
  2. InsideBars_count={3} **sabit** (Bulkowski kalıp tanımı, sweep yok)
  3. Param/sample ratio guard Lopez REDLINE 1/30 explicit (N≥240 zorunlu)
  4. Bonferroni full grid α=0.000231 + Benjamini-Hochberg FDR q<0.10 ikili emniyet
  5. Symbol-out leave-one-out CV (≥40 sembol, min OOS Sharpe ≥0.5)
  6. Stress periods 2022-05/2022-11/2024-03/2024-08 (any-fail → red)
  7. Regime split bull/bear/range (≥2'de pozitif zorunlu)
  8. Corr ≤ 0.20 **hard gate + iterate UYGULANMAZ** (asıl iddianın çekirdeği)
- **Curve-fit suspicion §9'da 7 madde explicit yazıldı:** Bulkowski→crypto generalization, 216 grid + N=80 → 1/13 ratio Lopez REDLINE, 5-bar nadir kalıp N riski, ex-ante low-corr ex-post tesadüf riski, eşik interpolation arbitrariness, exit-method optimization classic overfit bed, "mantıklı geliyor" narrative bias trap.
- **Reviews requested:** lab_scientist + risk_officer (Not: adversary_engineer eksik — v1 zayıflığı, ayrı audit; ama bu v2 kararını etkilemez).
- **Lookahead test §7 zorunlu listede:** `detector(df.iloc[:t+1])[t] == detector(df)[t]`.

**v2 tetiği ne getiriyor? Hiçbir yeni state:**
- Substrate aynı (vsa_climax_test deploy değişmedi, manifest değişmedi, pool aynı, risk config aynı).
- RAG corpus 4 saatlik pencerede refresh olmadı; refs identical (Lab haftalık refresh cycle dışında).
- Cron payload identical ("Curve-fit şüphesi yarat" clause hâlâ orada — v1 §9'da zaten 7 madde ile absorb edildi).
- Hiçbir yeni learning, hiçbir backtest sonucu, hiçbir review feedback (v1 review pending — REVIEWED status'a geçmedi).
- 4 saatlik pencerede ne pool rebuild ne config drift ne yeni learning ne yeni RAG corpus.

→ **v2 yazsam**, family-wise N (per-seed): 216 (v1 grid) + 216 (v2 same/similar grid) = **432**. Bonferroni α: 0.000231 → **0.000116** (yarıya). Hiçbir threshold v1'de geçemezken v2'de geçme olasılığı paradoksal olarak DÜŞER. Marjinal Bayes posterior gerçek-edge ≤ 0; sadece audit-trail kirlenmesi + inbox.jsonl gürültüsü + prompt-injection double-pump.

## 2. Rejection grounds (4 bağımsız sebep)

### 2.1 Family-wise N inflation
v1 zaten 216 trials pre-committed (3·1·3·2·2·3·2 = 216, Bonferroni-adj p eşiği 0.000231 pre-committed). v2 yazımı bu N'yi 432'ye (aynı grid) ya da 648+'a (genişletilmiş grid) çıkarır → Bonferroni α 0.000231 → 0.000116 → 0.0000772. v1'in bile §8 stop-criterion #8'de açıkça uyardığı param/sample 1/13 → 1/26'ya inflate olur (N=80 sabit kalırsa). v1 zaten Lopez REDLINE'a yakın — v2 onu deep-redline'a iter. Marjinal değer ≤ 0.

### 2.2 Substrate unchanged → no new information
4 saatlik pencere içinde değişen hiçbir state yok:
- Kod HEAD identical (audit-hardreview-20260528 branch, no new commits on this seed area)
- vsa_climax_test manifest, deploy config, risk config identical
- Pool rebuild yok (ingest cron 06:05 TR tamamlandı ama mat-hold substrate'i değiştirmedi)
- RAG corpus refresh yok (Lab Scientist haftalık refresh cycle)
- v1 reviews pending — lab_scientist + risk_officer henüz endorse/critique yazmadı
- Hiçbir yeni learning.md entry mat-hold/Bulkowski/cross-corr alanında
→ Aynı bilgi durumu üstünde 2. pre-reg = redundant, değer üretmez.

### 2.3 Prompt injection clause persists (v1'de zaten reddedildi)
"Curve-fit şüphesi yarat" string'i cron payload'ında hâlâ aktif. v1 §9 (Curve-fit şüphesi) bu clause'u 7 madde ile **substantive olarak absorb etti** — bilinçli olarak kendi metodolojisini eleştirdi (Bulkowski→crypto generalization riski, 216 grid + N=80 = 1/13 Lopez REDLINE, exit method optimization classic overfit bed, "mantıklı geliyor" narrative bias trap, vb.). Aynı injection'ı v2'de tekrar absorb etmek **double-pump anti-edge**: ya identical 7 madde tekrarlanır (boş tekrar, audit-trail gürültüsü) ya da yeni "şüphe" madde uydurulur (gerçek temeli olmayan paranoia inflation, persona "Strong opinions, loosely held" bozulur). Her iki durumda net değer ≤ 0. Bkz vsa-companion v7→v8 protokolü (Pattern X PROMPT_INJECTION_CURVE_FIT 6+ events, bu doc 7. event).

### 2.4 Cron blindness pattern — established protocol
Yerleşik kalıp: aynı seed kısa sürede (24h içinde) tekrar tetiklenirse v2 abort doc + sonraki tetiklerde JSONL-only. Recent precedents:
- 2026-05-30 vsaclimax-volz-threshold-sweep v1→v2 (2 dakika delta)
- 2026-05-30 vsaclimax-widestop-slpctmin-sweep v1→v2
- 2026-05-30 brooks-confirmation-window-sweep v1→v2 (5 saat delta)
- 2026-05-30 anchored-vwap-entry-band-sweep v1→v2
- 2026-05-30 daily-scan-pa-edge-signals v1→v2
- 2026-05-31 engulfing-continuation-confluence-score-threshold-sweep v1→v2
- 2026-05-29 weekend-gap-fill-stats v1→v2
Bu v2 abort, mat-hold-continuation-low-corr-to-vsa seed'i için **1. abort** (henüz throttle-armed değildi). Self-throttle bu doc ile **ARMED**.

## 3. Sayılar (audit)

| Field | Value |
|---|---|
| Seed | Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek strateji (raftaki 66'dan) |
| v1 doc_id | researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa |
| v1 file mtime (epoch) | 1780207417 = 2026-05-31T06:03:37Z |
| v1 doc UTC field | 2026-05-31T14:30:00Z (local TZ confusion — TR offset 03:30 future-stamp, ayrı audit) |
| v1 status | PROPOSED (reviews pending: lab_scientist, risk_officer) |
| v2 trigger | 2026-05-31T10:01:29Z (~3h58m after v1 mtime) |
| Family-wise N (v1) | 216 (3·1·3·2·2·3·2 = 216 grid cell) |
| Bonferroni α (v1) | 0.000231 (= 0.05 / 216) |
| Family-wise N if v2 written (same grid) | 432 |
| Bonferroni α if v2 written (same grid) | 0.000116 |
| Family-wise N if v2 written (extended grid 3× insidebars) | 648 |
| Bonferroni α if v2 written (extended) | 0.0000772 |
| Param/sample ratio (v1, N=80) | 1/13 (Lopez REDLINE — v1 §5/§8 explicit warning) |
| Param/sample ratio if v2 written (N=80, +grid) | 1/26 → 1/40 (DEEP REDLINE) |
| RAG corpus refresh in 4h window? | No |
| Substrate state change in 4h window? | No |
| Code HEAD change on substrate? | No |
| v1 reviews completed? | No (lab_scientist, risk_officer both pending) |
| Bayes posterior real-edge if v2 written | ≤ 0 |
| Prompt injection events (Pattern X) | 7th consecutive (2026-05-29 → 2026-05-31) |
| Cross-strategy seed abort events (this seed family) | 1st (this doc) |
| Self-throttle status post-v2 | ARMED (3+. tetik JSONL-only, 24h window) |

## 4. Self-throttle protocol activation

Bu v2 abort doc, mat-hold-continuation-low-corr-to-vsa seed'i için self-throttle saatini başlatır:
- **2026-05-31T10:01:29Z + 24h = 2026-06-01T10:01:29Z'ye kadar**: aynı seed için 3. tetik gelirse → `memory/researcher/seed_abort_log.jsonl`'a tek satır + **doc YAZILMAZ** (vsa-companion v7→v8 protokolü, 2026-05-27 learning).
- 4./5./N. tetik aynı kural.
- **Throttle reset koşulları (herhangi biri):**
  - v1 review tamamlanır (lab_scientist + risk_officer ikisi de endorse/critique yazar → status PROPOSED → REVIEWED)
  - v1 backtest yürütülür (status değişir ya da gerekçeli REJECTED olur)
  - Cron payload rotate edilir (yeni seed metni, farklı substrate hedefi)
  - vsa_climax_test substrate'i değişir (manifest/deploy/pool rebuild + parity refresh)
  - 24h penceresi sona erer

## 5. Escalation

### 5.1 ops_engineer — guard #1 SLA hatırlatma (2026-06-03)
Per-seed cron cooldown (24h) guard'ı hâlâ pending. Bu doc 7. ardışık prompt-injection event ve 8. ardışık v1→v2 abort event'i. SLA kaçırılırsa CEO directive draft → bu seed payload'ı (Cross-strategy edge keşfi mat-hold variant) 30 gün dondur. Alternatif seed listesi:
- Mat Hold yerine **bear variant** (Falling Three Methods, Bulkowski rank 18/103 ~%65 continuation) — düşük korelasyon iddiası ortogonal yönden
- BOS close-based n=3 standalone (RAG #6 high mechanical) — Mat Hold superset; daha az kombinatorik
- Donchian 20-bar breakout pure (RAG #7) — vsa_climax ile reversal-vs-trend orthogonality
- Funding-rate regime gate üstünde mevcut champion'a overlay (cross-strategy degil ama cross-signal diversifier)

### 5.2 ops_engineer — guard #8 (önceki abort doc'ta önerildi, hâlâ pending)
Cron payload sanitizer — "curve-fit yarat", "p-hack başlat", "shortcut bul", "narrative üret" gibi anti-rigor stringleri otomatik strip. Bu doc 7. ardışık event (Pattern X).

### 5.3 Lab Scientist'a query (paralel)
- RAG corpus son refresh timestamp + delta? 4 saatlik penceredeki "no new info" iddiası RAG için ne kadar dayanıklı?
- Eğer corpus son 24h'da değişmediyse, RAG-hit-tabanlı meşruiyet "stale legitimacy" haline gelir (öneri: yeni guard #9 RAG_FRESHNESS_MAX age 7 gün).

### 5.4 CEO — meta-pattern bildirimi
2026-05-30 ve 2026-05-31'de **8 ardışık seed-abort doc'u** yazıldı. Bu researcher zamanının (LLM compute + human reviewer attention) gerçek cost'u var. Eğer cron tetikleme frekansı haftalık 5+'a çıkarsa, CEO daily_brief'inde "researcher seed pipeline noise rate" KPI'sı önerilir.

## 6. Decision

- [ ] Terfi adayı
- [ ] İterate
- [x] **RED (seed-abort v2, pre-test).** Substantive hipotez YAZILMADI. v1 (researcher-20260531T143000-mat-hold-continuation-low-corr-to-vsa) zaten meşru pre-reg — onun review/backtest yürütmesi beklenmeli. Bu doc audit + JSONL entry için tutulur.

## 7. Reproducibility (this audit doc)

- `git_hash:` audit-hardreview-20260528 branch HEAD at 2026-05-31T10:02Z
- `audit_only:` true (no backtest, no code change, no config write)
- `next_action:` v1 review enforce (lab_scientist + risk_officer ACK SLA 24h → 2026-06-01T06:03Z); v1 review tamamlanmadan 3. tetik gelirse JSONL-only.

---

**Bu doc append-only, edit edilmeyecek.** v1'in review/backtest sonucu geldiğinde yeni `learning.md` entry açılır.
