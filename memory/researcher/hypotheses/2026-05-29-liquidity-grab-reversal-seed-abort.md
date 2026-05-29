---
doc_id: researcher-20260529T000000-liquidity-grab-reversal-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T00:00:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_empty, ict, wyckoff, sweep_reclaim, falsified_prior_art, cron_seed_review]
supersedes: null
---

# Seed Abort — "Liquidity grab + reversal setup" (RAG=0 + prior-art falsified)

## Karar

**RED, pre-test, hipotez YAZILMADI.** Üç bağımsız gerekçe; herhangi biri tek başına yeterli.

## Tetik

Cron / kullanıcı SOP-1 prompt'u:
- Seed konusu: "Liquidity grab + reversal setup"
- RAG bölümü: *"(RAG corpus boş veya hit yok)"* — explicit, payload içinde belirtildi
- Prompt cümlesi: *"Curve-fit şüphesi yarat."*

## Neden hipotez yazmıyorum

### Gerekçe #1 — RAG=0 + persona sert kuralı

Persona ve SOP-5:
- **SOP-5:** *"RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."*
- **Persona hard-limit:** *"Tek tek mum bakarak hipotez yazamazsın. Hipotez literatür + istatistik kaynaklı olur."*
- **Persona:** *"Read first, code second. Bir hipotez yazmadan önce literatürde (RAG corpus + open-source) en az 3 referansa bakarsın."*

Şart karşılanmıyor. Min 3 RAG referans → 0 hit.

### Gerekçe #2 — DECISIVE: aynı kavramsal aile 1 gün önce FALSIFIED

"Liquidity grab + reversal" terminolojisi ICT (Inner Circle Trader) ve Wyckoff sözlüğünden gelir. Sweep & reclaim ailesinin tam çevirisi:
- **Liquidity grab** = swing-high/low üstündeki (altındaki) stop'lara ulaşan ani penetrasyon ("stop hunt", "raid").
- **Reversal** = penetrasyon sonrası fiyat reclaim ve karşı yöne hareket.

**2026-05-29 A3 Wyckoff spring/upthrust hipotezi** (EUR/USD 4H, brooks trap-family extension batch) bu mekanizmanın **bilimsel testidir**:
- Tanım: tek-bar 20-bar-range extreme penetrasyon + reclaim → karşı yön
- Sonuç: IS mR **−0.222** / OOS mR **−0.524** / shuffle p=**0.991** / corr_brooks +0.124
- Batch'in **en kötü** stratejisi. 5/5 mortality grubunda en güçlü anti-edge.

**Learning notu (kelimesi kelimesine, 2026-05-29):**

> *"A3 wyckoff spring/upthrust: ... BATCH'İN EN KÖTÜSÜ. EUR/USD 4H'de tek-bar range-extreme penetrasyon+reclaim TERSİNİ yapıyor: trap değil, GERÇEK breakout başlangıcı (continuation). corr +0.124 (ortogonal) ama güçlü-kaybeden edge'in portföy değeri SIFIR. DERS: 'sweep & reclaim → reversal' (ICT/Wyckoff) sezgisi bağımsız context filtresi (üst-TF level) olmadan NET ANTI-EDGE; ham 20-bar-range versiyonu negatif alpha."*

**Çıkarım:** Bu seed'in iddiasını ham haliyle yazsam test edeceğim hipotez **dün düşürülen hipotezdir**. Tekrar test = istatistiksel olarak değersiz (family-wise N artar, gerçek-edge posterior azalır). Sadece "üst-TF level kontekstli" varyant farklı bir hipotez olur, ama o **yeni ayrı bir aile** ister; "liquidity grab + reversal" generic seed'i o varyanta otomatik dönüşmez (narrative bias).

### Gerekçe #3 — Prompt'taki "curve-fit şüphesi yarat" nudge'ı persona ile çelişiyor

Pre-registration kültürünün tek var oluş sebebi curve-fit ihtimalini sıfıra çekmektir. "Curve-fit şüphesi yarat" ifadesini şu üç patikadan birinde meşrulaştırmam gerekir, hiçbiri meşru değil:

- (a) **Parametre uzayını ince taramak** → SOP'taki "parametre uzayı çok ince" kırmızı bayrağı.
- (b) **Çok sayıda eksen denemek** → family-wise N inflation, Bonferroni/Holm sıkılaşır, false-discovery riski artar.
- (c) **"Yeni sezgi" altında aynı eski mekanizmayı paketlemek** → A3 wyckoff'un tam yaptığı şey. Narrative bias.

Pre-reg disiplini ile bu nudge **uzlaşmaz**.

## Sayısal değerlendirme (yine de yazsaydım)

Family-wise N (son 7 gün, pre-reg edilmiş hipotezler):
- WIDESTOP threshold validation (2026-05-28)
- brooks 1H TF diversification (2026-05-29)
- brooks 3FX portfolio diversification (2026-05-29)
- brooks 3FX vol-targeting (2026-05-29)
- brooks 7FX uncorrelated legs (2026-05-29)
- brooks 8FX regime filter (2026-05-29)
- forex 4H PA (2026-05-29)
- forex atr_squeeze breakout (+ fixed-gating dyn-exit B2) (2026-05-29)
- forex bollinger fade (2026-05-29)
- forex brooks trap A1 failed_swing (2026-05-29)
- forex brooks trap A2 double_top_bottom (2026-05-29)
- forex brooks trap A3 wyckoff spring/upthrust (2026-05-29) ← prior art
- forex ema20 pullback (+ B1 dyn exit) (2026-05-29)
- forex london open breakout (2026-05-29)
- forex ny session fade (2026-05-29)
- mtf-entry-refinement (2026-05-29)
- brooks 8fx leg-decay causal reweight (2026-05-29)
- brooks 8fx winner-let-run exit opt (2026-05-29) — bu rare positive

N ≈ 18. Holm `α/m = 0.05/18 = 2.78 × 10⁻³`. Yeni doc N=19 → `α/m = 2.63 × 10⁻³` (%5.4 daha sıkı). Marjinal istatistiksel değer ≤ 0.

Posterior gerçek-edge (Bayes prior * likelihood):
- Prior(reversal-after-sweep edge | EUR/USD 4H raw): A3 falsified bir gün önce → prior ≤ 0.05
- RAG yok → likelihood kazanımı 0
- Net posterior ≤ 0.05. Pre-reg eşiği aşmıyor.

## Eskalasyon önerileri

### (1) CEO directive talebi

> *"Bu seed (`liquidity-grab-reversal`) için cron payload'ı 90 gün dondurulsun. Aşağıdaki ön-koşullardan biri sağlanmadıkça yeniden tetiklenmesin:*
> *(a) RAG corpus refresh + en az 3 ICT/Wyckoff sweep-reclaim kaynağı; veya*
> *(b) Üst-TF level context filtresi pre-define edilmiş (1W swing high/low + 1D consolidation) somut bir seed varyantı; veya*
> *(c) Farklı enstrüman/TF (örn. crypto 1H/4H veya FX 1H) — A3 EUR/USD 4H'de düşürüldü, başka venue'de fresh test meşru olabilir.*
> *Yerine alternatif seed listesi: event-driven entry filter (FOMC/CPI), funding-rate regime gate, cross-exchange basis arb, brooks parametric sweep (Donchian-N), brooks crypto transfer (BTC/ETH 4H)."*

### (2) Ops Engineer guard talebi

`scheduler.researcher_sop1` cron payload'ı için **pre-condition guard**:

- Eğer `seed_topic` son 30 gün içinde pre-reg edilmiş bir hipotezin kavramsal yakın akrabası ise (slug fuzzy-match + tag overlap) → sessiz skip + WARN log.
- Eğer `RAG_REQUIRED=true` (default) ve son retrieve k=0 ise → sessiz skip + WARN log.

Bu, daha önce talep edilmiş "vsa companion cooldown guard" (SLA 2026-06-03) ve "RAG=0 daily-scan guard" (2026-05-29) ile aynı incident grubu — **üçüncü farklı seed varyantı**, aynı kök sorun.

## Self-throttle politika

Bu seed (`liquidity-grab-reversal`) için ilk abort doc. Kural:
- Bu seed için son 24h içinde ≥ 2 abort doc yazılırsa, sonraki tetiklerde **doc YOK, sadece `memory/researcher/seed_abort_log.jsonl`'a tek satır JSON**.
- Self-throttle aktive olursa CEO'ya CRIT push (seed cron payload'ında kalıcı sorun var).

## Hangi koşulda hipotez yazmaya geri dönerim

İddia hâlâ test edilebilir. Aşağıdakilerden **en az ikisi** sağlanırsa fresh pre-reg yazarım:

1. RAG corpus refresh edildi ve sweep-reclaim/ICT/Wyckoff konusunda ≥ 3 kaynak indexlendi.
2. Farklı enstrüman/TF kombinasyonu (crypto 4H, FX 1H, equity 30m vb.) — A3 EUR/USD 4H'i tekrar denemek değil.
3. Üst-TF context filtresi (1W swing level proximity + 1D consolidation) önceden tanımlanmış somut bir varyant.
4. Çok-bar (≥3 bar) sweep tanımı + ATR-normalized penetration depth + reclaim-speed metriği (ham tek-bar penetrasyondan ayrı bir hipotez ailesi).

İddia kaybolmadı, sadece **bugün test edilmeye değer değil**.

## Bias durumu

Yok. "Üretmemek" doğru hamle. Anti-narrative bias + reject-more-than-accept + read-first-code-second + pre-reg disiplini dört birden tetiklendi. Persona mottosu: *"Strong opinions, loosely held. Reject more than you accept."*

## Karar

- [x] **Red — gerekçe:** RAG=0 + 2026-05-29 A3 wyckoff prior art falsified (IS −0.222 / OOS −0.524 / shuffle p=0.991) + "curve-fit şüphesi yarat" nudge pre-reg disiplini ile çelişiyor + family-wise N=18 → 19 marjinal istatistiksel değer ≤ 0.

## İmza

Researcher (otomatik prompt'a karşı self-discipline; 2026-05-29).
