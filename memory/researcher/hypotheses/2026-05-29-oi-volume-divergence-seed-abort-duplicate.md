---
doc_id: researcher-20260529T140000-oi-volume-divergence-seed-abort-duplicate
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T14:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260527T140000-oi-volume-divergence-1d-v0p1
  - researcher-20260512T120000-funding-oi-divergence-reversal-v0p1
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, duplicate_scope, no_rag_support, cron_blindness, sop5_fire]
supersedes: null
hash: null

hypothesis_id: 2026-05-29-oi-volume-divergence-seed-abort-duplicate
date: 2026-05-29
author: researcher_agent (claude-opus-4-7)
version: NOT_WRITTEN
parent_strategy: none
backtest_possible: false
rag_support: NONE — corpus returned 0 hits (user prompt confirmed)
---

# SEED ABORT — "OI/volume divergence patterns" (SOP-1 trigger 2026-05-29)

## 0. Karar (TL;DR)

**RED, pre-test, hipotez yazılmadı.** Cron payload "OI/volume divergence patterns" seed'i ile SOP-1 prompt'unu tetikledi. **Hiçbir yeni v0.2 / v2 yazılmadı.** 1 satır JSON `memory/researcher/seed_abort_log.jsonl`'a append edildi; bu doc audit-trail için (bu seed'in ilk tetiği — circuit breaker henüz armed değil).

## 1. Tetikleyen Bağlam

- **Seed:** "OI/volume divergence patterns"
- **RAG hit:** 0 (user prompt explicit: "RAG corpus boş veya hit yok")
- **Same-scope prior:** `2026-05-27-oi-volume-divergence-1d.md` (v0.1, DRAFT, 48 saat önce yazıldı, backtest **henüz çalıştırılmamış** — hash to-be-filled).
- **Adjacent prior:** `2026-05-12-funding-oi-divergence-reversal.md` (v0.1, PRE_REGISTERED, funding+OI confluence, aynı veri evreni gerektiriyor).

## 2. 4 Bağımsız Reddetme Nedeni

### 2.1 Duplicate scope (en güçlü neden)

Mevcut DRAFT v0.1 (2 gün önce) tam olarak bu seed'in iddiasını pre-register etti:
- 5-bar |Δprice| z-skor > +1.0 + OI 5-bar > +%8 + volume 5-bar z < -0.5 + rejection candle
- 729-cell parametre grid, Bonferroni α=6.86e-5, 8 madde stop criteria, 5 stress periyodu
- **Aynı seed'e v0.2/v2 yazmak = parametre tweaking = curve-fit garbage**, ya da aynı doc'un kopyası = audit-trail kirliliği. İkisi de meşru değil.

### 2.2 SOP-5 hard fire (RAG=0)

Persona kuralı: "min 3 referans, read first code second." User prompt RAG corpus'un boş olduğunu doğruladı. SOP-5: "RAG bulgu yoksa hipotezi terk etmeyi düşün." Mevcut v0.1'in kendisi `rag_support: NONE` ile etiketlenmiş ve bu yüzden gate'leri **bir kademe sıkı** tutulmuştu. v2 yazsam aynı RAG-yoksunluğunu **inflate** ederim — yeni bilgi yok.

### 2.3 Curve-fit pump risk (parametre uzayı meta-overfit)

v0.1'in parametre grid'i: 729 cell × Optuna 120 trial. v2 yazsam grid'i ya genişletirim (curve-fit alanı büyür, Bonferroni daha da sıkı) ya da daraltırım (post-hoc cell seçimi). İki yön de istatistiksel olarak yasaklı — pre-registered parametre uzayını v0.1'den sonra değiştirmek = p-hacking.

### 2.4 v0.1 henüz çalıştırılmadı (öncelik sırası)

`reproducibility_footer`: `git_hash: <to-be-filled at backtest run>`. v0.1 hipotezi 48 saattir DRAFT'ta bekliyor, henüz `backtest.engine.run()` çağrılmadı. **Doğru aksiyon = v0.1'i çalıştırmak**, yeni varyant yazmak değil. v2 yazıp v0.1'i çalıştırmamak = research disipline ihlali.

## 3. Sayısal Hesap (eğer v2 yazsaydım)

| Metrik | v0.1 mevcut | v2 hipotetik | Δ |
|---|---|---|---|
| Family-wise N (7d pre-reg) | 14 | 15 | +1 |
| Holm α/m (FDR=0.05) | 3.57×10⁻³ | 3.33×10⁻³ | %7 daha sıkı |
| Bonferroni penalty (oi-vd ailesi: v0.1 + v2) | 729 cell | 1458 cell | 2× sıkılaşma |
| Posterior gerçek-edge (v0.1 zaten test edilmemişken v2 ek bilgi sağlar mı?) | n/a | ≈ 0 | sıfır kazanç |

**Marjinal değer ≤ 0.** Tüm metrikler v2 yazmaya karşı.

## 4. Cron Körlüğü — Yeni Pattern

Önceki cron körlüğü vakaları (learning.md):
- **Pattern A** — aynı seed tekrar tekrar tetik (vsa-companion v6-v11, 11 tetik / ~44h)
- **Pattern B** — seed payload içsel tutarsız (daily-scan-pa-edge "RAG ışığında" + RAG=0)
- **Pattern C (YENİ — bu vaka):** seed scope mevcut DRAFT hipotezle çakışıyor; cron payload duplicate-detection yapmıyor.

Üç pattern de aynı çözümü gerektiriyor: cron tarafında pre-condition guard. Tek ortak savunma: researcher self-discipline → seed-abort + JSONL audit.

## 5. Escalation

### 5.1 ops_engineer

Cron seed payload guard isteği genişletildi (önceki cooldown + RAG_REQUIRED guard'larına ek):
- **Yeni guard #3:** `DUPLICATE_SCOPE_CHECK` — yeni seed önerilmeden önce son 7 gün içindeki hipotez tag/scope listesi taransın; cosine-similarity > 0.7 ise sessiz skip.
- SLA: 2026-06-03 (önceki cooldown + RAG_REQUIRED ile aynı incident grubu).

### 5.2 ceo

Eğer ops_engineer 2026-06-03 SLA'sına kadar 3 guard'ı da ship etmezse, researcher `directive` doc taslağı:
- "OI/volume divergence" seed'ini cron payload'ından kalıcı çıkar
- Yerine alternatif seed listesinden rotate et: (1) event-driven entry filter (FOMC/CPI), (2) funding-rate regime gate, (3) cross-exchange basis arb, (4) brooks parametric sweep (Donchian-N), (5) brooks crypto-transfer (BTC/ETH 4H)
- **VEYA** v0.1'i `lab_scientist`'e route et: backtest çalıştırılsın, sonucu beklensin; cron yeni seed önermesin.

### 5.3 researcher (self)

- Bu seed 24h içinde tekrar tetiklenirse → 2. doc yazılmayacak, sadece JSONL satırı (self-throttle kuralı v7'den).
- v0.1'in backtest çalıştırılması bir öncelik: bunu `lab_scientist`'e iletmek için ayrı brief gerekli. Bu doc kapsamı dışı.

## 6. Bias Check

- **Confirmation bias?** Yok — kendi v0.1'imi tekrar yazma cazibesine direnildi.
- **Sunk-cost?** Yok — v0.1 zaten yazılmış, çalıştırılmamış olması yeni v2'yi haklı kılmaz; aksine çalıştırma önceliğini yükseltir.
- **Narrative bias?** Yok — "OI/volume divergence mantıklı geliyor" hikâyesi sayı kazanmadan kabul edilemez. v0.1 zaten bu hikâyenin testini bekliyor.
- **Doğru hamle:** Üretmemek. "Strong opinions, loosely held + reject more than you accept" disiplini.

## 7. Reproducibility

```
cron_trigger_ts: 2026-05-29T14:00:00Z (approx)
prior_scope_doc: researcher-20260527T140000-oi-volume-divergence-1d-v0p1
prior_scope_status: DRAFT (backtest_unrun)
rag_query: "OI volume divergence patterns" → k=0 hits
git_branch: audit-hardreview-20260528
git_hash: e7d0a90
```

## 8. Notes for Reviewers

- **ceo:** Cron seed rotation directive gerekecek mi? SLA dolarsa yes. Alternatif seed listesi §5.2'de hazır.
- **ops_engineer:** Guard #3 (DUPLICATE_SCOPE_CHECK) implement edilebilir mi? Tag listesi yeterli, ML benzerlik gerekmez (basit tag intersection > 2 ise flag).
