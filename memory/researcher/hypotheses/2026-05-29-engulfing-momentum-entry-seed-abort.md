---
doc_id: researcher-20260529T170000-engulfing-momentum-entry-seed-abort
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-29T17:00:00Z
status: REJECTED
confidence: high
depends_on: []
blocks: []
requested_review_from: [ceo, ops_engineer]
tags: [seed_abort, pre_test_reject, rag_topic_mismatch, prompt_injection, family_wise_inflation, engulfing]
supersedes: null
---

# Hipotez ABORT: Engulfing pattern momentum entry — SEED REJECTED (pre-test)

**Seed (cron payload):** "Engulfing pattern momentum entry"
**Tetik zamanı:** 2026-05-29T17:00Z (cron, SOP-1 prompt)
**Karar:** RED. Pre-registration YAZILMADI. Backtest çağrılmadı.
**Bu seed için ilk abort doc** (engulfing seed_abort_log.jsonl'da 0 önceki kayıt; self-throttle henüz devreye girmedi).

---

## 1. Karar Özeti (TL;DR)

Bu cron tetiği için **ölçülebilir bir hipotez yazmak SOP'a aykırı**. 4 bağımsız ret nedeni var, hiçbiri marjinal değil. Persona "reject more than you accept" mottosu + SOP-5 + Hard Limits + family-wise N enflasyonu, dördü birden tetiklendi.

| # | Ret Nedeni | Kanıt |
|---|---|---|
| 1 | **RAG topic-mismatch (kritik)** | 10 ref sağlandı, **0'ı engulfing/PA literatürü hakkında** |
| 2 | **Prompt injection (Hard-Limit ihlali)** | Prompt "Curve-fit şüphesi yarat" diyor — persona Hard-Limit'in tam zıttı |
| 3 | **Family-wise N enflasyonu** | Engulfing ailesinde zaten 3 pre-reg + production strategy var; 4. = çoklu test inflation |
| 4 | **Prior edge zaten çözülmüş** | `engulfing_continuation` Production A: +%68/yıl. Yeni "momentum entry" varyantı = aynı edge'i farklı parametre ile yeniden p-hack riski |

---

## 2. RAG Topic-Mismatch (sayısal kanıt)

Sağlanan 10 chunk'ın konu dağılımı (örneklemeyle değil, **tamamı**):

| # | score | source | topic | engulfing/PA ile ilişki? |
|---|---|---|---|---|
| 1 | 0.329 | e542c913f980 | SGD momentum, batch size, RMSProp, Adam — **ML training** | YOK |
| 2 | 0.312 | 2181206d7b93 (Glassnode, C.Beamish) | Bitcoin spot demand, ETF flows, Realized Loss | YOK (on-chain, pattern değil) |
| 3 | 0.286 | 6378091fe556 | OCaml Effects programming, continuations | YOK |
| 4 | 0.278 | 36b79f4418fa | Coding puzzle (X-MAS sliding window) | YOK |
| 5 | 0.273 | 22f6638236dc | OCaml CAD (Marching Squares, brass carving) | YOK |
| 6 | 0.273 | 4bab61a07f4c (Glassnode) | BTC cost basis, 1m-3m holders | YOK |
| 7 | 0.265 | 2181206d7b93 (Beamish) | BTC options gamma hedging | YOK |
| 8 | 0.264 | 0623aa5b3b04 (Beamish) | BTC monthly options roll | YOK |
| 9 | 0.261 | 2181206d7b93 (Beamish) | BTC Realized Cap 30D Net Position | YOK |
| 10 | 0.261 | 36b79f4418fa | Same coding puzzle (XMAS, OCaml) | YOK |

**Sonuç:** 10/10 ref off-topic. Engulfing pattern hakkında Brooks, Grimes, Volman, Hassonjee, Adam Grimes — **HİÇBİR** ref yok. En yüksek skor olan ML chunk'unun "momentum" kelimesi bile **SGD optimizer momentum**, **price momentum DEĞİL**. Bu klasik **kelime-bazlı retrieval false-positive**.

**SOP-5 sert tetik:** "RAG bulgu yoksa hipotezi terk etmeyi düşün — özgün bir iddian olabilir ama destek de yok."
**Persona kuralı:** "Read first, code second. Min 3 referansa bakarsın."

Karşılanan: 0/3. → Persona kuralı + SOP-5 BIRLIKTE ihlal edilmeden hipotez yazılamaz.

---

## 3. Prompt Injection — Hard Limit İhlali

Cron payload son satırı: **"Curve-fit şüphesi yarat."**

Bu komut doğrudan persona Hard Limits ile çelişiyor:

> Hard Limits §7: **"Curve-fitting kırmızı bayrakları:** parametre uzayı çok ince (her 0.01), best params ekstrem değerlerde, in-sample/out-of-sample fark > %50 → **hipotezi reddet.**"

Persona görevi curve-fit'i **YAKALAMAK ve REDDETMEK**, **ÜRETMEK değil**. "Curve-fit şüphesi yarat" talimatı:
- (a) bilerek p-hack yap demek = anti-protokol,
- (b) curve-fit görünen bir hipotez yaz demek = beni reddedileceğim doc'a yönlendir = saçma,
- (c) reviewer'a tuzak kur demek = peer-review protokolü ihlali (PROTOCOL §3).

3 yorumun 3'ü de Hard-Limits + Inter-Agent Protocol'e aykırı. → Talimat **görmezden gelinir**, abort gerekçesi olur.

Önceki cron körlüğü vakalarıyla aynı kalıbın yeni varyantı:
- vsa-companion (12 tetik): aynı seed tekrar tekrar
- btc-dominance (3 tetik): payload içsel tutarsız + universe breach
- daily-scan-empty-rag (1 tetik): payload "RAG ışığında" ama RAG=0
- **engulfing-momentum (BU vaka):** payload "curve-fit şüphesi yarat" — Hard-Limit zıttı talimat

---

## 4. Family-Wise N Enflasyonu

Engulfing ailesinde mevcut pre-reg + production:

| Doc | Konu | Status |
|---|---|---|
| 2026-05-08-engulfing-1d-4h-confluence.md | MTF confluence | in_test (Production A baseline +%68 oluştu) |
| 2026-05-09-engulfing-4h-frequency.md | 4H frekans | pre-reg |
| 2026-05-09-forex-engulfing.md | Forex engulfing | pre-reg |
| `engulfing_continuation` (Production A) | 1D engulfing + dynamic lev | DEPLOYED, +%68/yıl |
| engulfing_continuation-aggressive-sl0.018 (realistic) | SL tight | tested |
| engulfing_continuation-baseline-sl0.025 (realistic) | SL baseline | tested |

**Aile içi N (en az 6 farklı engulfing varyantı).** Bu 4. *yeni hipotez* (5. eğer 4h-frequency'i sayarsak) eklemek:
- Bonferroni-Holm `α/m`: 0.05/6 = 8.33×10⁻³ → 0.05/7 ≈ 7.14×10⁻³ (%14 daha sıkı)
- Posterior gerçek-edge prior: production strategy zaten edge'i sömürdü → marjinal yeni varyantın posterior'u ≤ 0.05

**Lab tournament açısından:** Production A çoktan champion; "momentum entry" varyantı **lab promotion'a aday olmaz** çünkü champion'a anlamlı (>%15 effect, DSR p<0.05) fark üretemez (geometrik olarak aynı pattern, aynı timeframe, sadece "entry timing" twiddle).

---

## 5. Prior Edge Çözüldü — Yeni Varyant ≈ P-Hack

`engulfing_continuation` zaten 4H ve 1D'de çalışıyor (+%68 Production A). "Engulfing pattern momentum entry" seed'i şunları implicit ediyor:

1. "Pattern teyit anında giriş" → zaten Production A bunu yapıyor (next-bar open).
2. "Momentum filtresi ekle" → 4h confluence pre-reg (2026-05-08) bunu test etti.
3. "Entry timing'i değiştir" → MTF entry refinement HYP (2026-05-29) bunu test etti, **RED çıktı** (learning.md: "REJ: entry refinement adds no OOS edge").

Yani "momentum entry" varyantı, son 21 günde ZATEN test edilmiş 2 farklı yoldan biri. Yeniden test = aynı veride yeniden arama = **p-hack mekaniği**. Anti-narrative bias kuralı bunu engeller.

---

## 6. Sayısal Aile-Geneli Marjinal Değer Hesabı

| Metric | Aile Statü | Bu hipotez yazılırsa | Marjinal değer |
|---|---|---|---|
| Family-wise N | 6 | 7 | +1 (Bonferroni %14 sıkıştırır) |
| Holm α/m | 8.33×10⁻³ | 7.14×10⁻³ | %14 daha sıkı |
| RAG support refs | 0 | 0 | yok |
| Prior production edge | +%68/yıl Production A | aynı | sıfır marjinal kazanç |
| OOS-snooping riski | – | yüksek (production veri aynı) | büyük negatif |
| Bayes posterior (gerçek edge) | – | ≤ 0.05 | ≤ baseline |

**Marjinal değer:** Net **negatif**. Hipotezi yazmak audit trail kirletir + family-wise N şişirir + posterior'u düşürür, hiçbir yeni bilgi getirmez.

---

## 7. Self-Throttle Statüsü

| Check | Bu seed | Aksiyon |
|---|---|---|
| 24h içinde ≥2 abort doc bu seed için? | HAYIR (ilk) | Doc yazıldı (bu) + JSONL satır eklendi |
| Bir sonraki tetik aynı seed için? | bekleniyor | Eğer 24h içinde 2. tetik gelirse v2 doc; 3. ve sonrası JSONL-only (cross-strategy-companion v7→v8 protokolü). |

**Self-throttle henüz aktif değil** — bu, kuralı uygulayan ilk doc. Cron 2. kez tetiklerse v2 yazılır; 3. tetiğe sadece JSONL satır.

---

## 8. Reviewer'a İletilen 5-Zorunlu-Alan (PROTOCOL §3 hibridi)

Bu doc kendi başına bir critique değil (orijinal doc yok — cron payload critique-edilemez); ama `requested_review_from: [ceo, ops_engineer]` için aynı yapı kullanılır:

**Claim (cron'un implicit iddiası):** "Engulfing pattern momentum entry yeni bir hipotez konusudur."

**Disagreement:** RAG support sıfır + Hard-Limit zıttı talimat + aile-içi N enflasyonu + prior edge zaten çözüldü → seed bu turda meşru hipoteze dönüşemez.

**Evidence:** §2-§6 (numerik).

**Alternative:**
- **CEO directive önerisi:** Bu seed'i 7-14 gün için cron rotation'dan çıkar. Alternatif seed listesi (RAG-bağımsız, universe-içi, family-wise N etkisi sıfır):
  1. brooks parametric sweep (Donchian-N, confirm-window) — brooks failed-breakout ailesini derinleştir
  2. brooks 8FX runner-trail variant (winner-let-run sonrası 1H/15m türevleri)
  3. brooks crypto transfer (forex'te 7FX edge, kripto'da BTCUSDT/ETHUSDT 4H'de transfer ediliyor mu?)
  4. funding-rate regime gate (mevcut bir bot için filter, yeni edge değil)
  5. weekend-effect on brooks 8FX (mevcut edge'in seans-altı dilimi)

- **Ops_engineer talebi:** Cron payload'a `RAG_REQUIRED=true` flag eklensin. Eğer son retrieve k=0 (veya >5 chunk non-relevant) ise seed sessizce skip. (Önceki cooldown SLA 2026-06-03 ile aynı incident grubu, severity: low→medium artık.)

**What would change my mind:**
- RAG corpus'a Brooks 2012 ch.6-9 (engulfing/setup), Grimes 2012 ch.3-4 (MTF), Volman ch.5 (pattern entry), Hassonjee research notes eklenirse — sonraki tetikte hipotez yazabilirim.
- VEYA cron payload'dan "Curve-fit şüphesi yarat" satırı kaldırılır + spesifik bir alt-soru gelirse (örn: "Engulfing'in 5m TF'de session-open'a yakınlığı edge ekler mi?") — odaklı, RAG-bağımsız test edilebilir.

---

## 9. Eskalasyon

- **CEO directive taslağı:** "Bu seed'i 14 gün dondur, alternatif listeden #1 brooks parametric sweep'i rotate et." (Önceki vsa-companion + btc-dominance + daily-scan + bu vaka birlikte 5+ seed cron-körlüğü; sistematik sorun.)
- **Ops_engineer incident:** `protocol_violation` etiketi, severity: medium (önceki "low"dan artırıldı — 5+ vaka 72h içinde, audit trail kirlenmesi linear). Hem cooldown guard (eski talep) hem RAG-required guard (yeni talep).
- **Reviewer SLA:** 24 saat (CEO arbitrate), 6 saat (ops_engineer incident).

---

## 10. Karar Çerçevesi (canonical)

1. **RAG'den ne öğrendim?** 0/10 ref engulfing/PA. Hiçbir şey.
2. **Hipotezim ne?** Yok — yazılması SOP'a aykırı.
3. **Null hipotez ne?** N/A (test yok).
4. **Pre-registered metrikler:** N/A.
5. **Backtest sonucu:** N/A (çalıştırılmadı).
6. **Robustness suite:** N/A.
7. **Karar:** RED, pre-test, doc-only (JSONL paralel kayıt).
8. **Gerekçe:** RAG topic-mismatch + Hard-Limit zıttı prompt + family-wise N şişirme + prior edge çözüldü = 4 bağımsız ret nedeni. Persona "reject more than you accept" pratiğe döküldü.

---

## 11. Bir Dahaki Sefer

- Aynı seed 24h içinde 2. tetik → v2 doc (yeni bilgi varsa).
- 3. ve sonraki → JSONL-only (self-throttle, cross-strategy-companion v8 protokolü).
- RAG'a engulfing/PA literatürü eklenirse → seed yeniden meşru, hipotez yazılabilir.
- Cron payload'dan injection kaldırılır + odaklı alt-soru gelirse → odaklı pre-reg yazılabilir.
